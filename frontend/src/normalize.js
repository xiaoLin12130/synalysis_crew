import { num } from "./format.js";

export const arr = (v) => (Array.isArray(v) ? v : []);
const n = (v, d = 0) => num(v, d);
const nullable = (v) => n(v, NaN);

export function normalizeJob(job = {}) {
  return {
    job_id: job.job_id || null,
    filename: job.filename || "",
    status: job.status || "queued",
    stage: job.stage || "queued",
    pct: n(job.pct),
    message: job.message || "",
    analysts_done: n(job.analysts_done),
    analysts_total: n(job.analysts_total, 5),
    result: job.result || null,
    error: job.error || "",
    offline: !!job.offline,
  };
}

export function normalizeMetrics(raw = {}) {
  const m = raw && typeof raw === "object" ? raw : {};
  const account = m.account || {};
  const pnl = m.pnl || {};
  const trading = m.trading || {};
  const behavior = m.behavior || {};
  const lb = pnl.stock_leaderboard || {};
  return {
    account: {
      initial_balance: nullable(account.initial_balance),
      ending_balance: nullable(account.ending_balance),
      net_transfer_in: nullable(account.net_transfer_in),
      gross_deposit: nullable(account.gross_deposit),
      gross_withdraw: nullable(account.gross_withdraw),
      opening_asset_value: nullable(account.opening_asset_value),
      total_return_rate: nullable(account.total_return_rate),
      total_return_rate_net: nullable(account.total_return_rate_net),
      annualized_return_rate: nullable(account.annualized_return_rate),
      realized_pnl: nullable(account.realized_pnl),
      total_cost: nullable(account.total_cost),
      total_cost_ratio: n(account.total_cost_ratio, NaN),
      holding_market_value: nullable(account.holding_market_value),
      holding_cost_value: nullable(account.holding_cost_value),
      unrealized_pnl: nullable(account.unrealized_pnl),
      market_value_source: account.market_value_source || "",
    },
    trading: {
      total_amount: nullable(trading.total_amount),
      total_count: n(trading.total_count),
      buy_count: n(trading.buy_count),
      sell_count: n(trading.sell_count),
      distinct_stock_count: n(trading.distinct_stock_count),
      current_holding_count: n(trading.current_holding_count),
      avg_holding_period_days: nullable(trading.avg_holding_period_days),
    },
    pnl: {
      realized_pnl: nullable(pnl.realized_pnl),
      win_count: nullable(pnl.win_count),
      loss_count: nullable(pnl.loss_count),
      win_rate: nullable(pnl.win_rate),
      total_profit: nullable(pnl.total_profit),
      total_loss: nullable(pnl.total_loss),
      profit_loss_ratio: nullable(pnl.profit_loss_ratio),
      max_single_profit: n(pnl.max_single_profit),
      max_single_loss: n(pnl.max_single_loss),
      double_count: n(pnl.double_count),
      halved_count: n(pnl.halved_count),
      unmatched_sell_amount: nullable(pnl.unmatched_sell_amount),
      monthly_pnl: arr(pnl.monthly_pnl).map((p) => ({ month: (p && p.month) || "", pnl: n(p && p.pnl) })),
      equity_curve: arr(pnl.equity_curve).map((p) => ({ month: (p && p.month) || "", date: (p && p.date) || "", equity: n(p && p.equity) })),
      return_curve: arr(pnl.return_curve).map((p) => ({ month: (p && p.month) || "", date: (p && p.date) || "", return_rate: nullable(p && p.return_rate) })),
      max_drawdown: nullable(pnl.max_drawdown),
      stock_leaderboard: {
        top_profit: arr(lb.top_profit),
        top_loss: arr(lb.top_loss),
      },
    },
    behavior: {
      // S2：后端为 dict {le_1d, 2_5d, 6_20d, gt_20d}，统一转成图表消费的数组
      holding_period_distribution: normalizeHoldingPeriodDistribution(behavior.holding_period_distribution),
      monthly_activity: arr(behavior.monthly_activity).map((b) => ({
        month: (b && b.month) || "",
        count: n(b && (b.total_count ?? b.count ?? b.trade_count)),
        buy_count: n(b && b.buy_count),
        sell_count: n(b && b.sell_count),
      })),
      max_position: {
        ratio: nullable(behavior.max_position && behavior.max_position.ratio),
        code: (behavior.max_position && behavior.max_position.code) || "",
        name: (behavior.max_position && behavior.max_position.name) || "",
        date: (behavior.max_position && behavior.max_position.date) || "",
      },
      top5_concentration: nullable(behavior.top5_concentration),
      favorite_stocks_top10: arr(behavior.favorite_stocks_top10).map((b) => ({
        code: (b && b.code) || "",
        name: (b && b.name) || "",
        count: n(b && (b.count ?? b.trade_count)),
        amount: nullable(b && (b.amount ?? b.total_pnl)),
      })),
      style: behavior.style,
      special_operations: behavior.special_operations || {},
    },
    stocks: arr(m.stocks),
    trades: arr(m.trades).map((t) => ({ ...(t || {}), pnl: t && t.pnl != null ? n(t.pnl) : null })),
    meta: { ...(m.meta || {}) },
  };
}

const HOLDING_PERIOD_KEYS = [
  { key: "le_1d", label: "≤1天" },
  { key: "2_5d", label: "2–5天" },
  { key: "6_20d", label: "6–20天" },
  { key: "gt_20d", label: ">20天" },
];

// S2：dict {le_1d, 2_5d, 6_20d, gt_20d} → [{label, count}]；兼容旧数组形态
export function normalizeHoldingPeriodDistribution(raw) {
  if (!raw || typeof raw !== "object") return [];
  if (Array.isArray(raw)) {
    return raw.map((b) => ({
      label: (b && (b.label || b.range)) || "",
      count: n(b && (b.count ?? b.value)),
    }));
  }
  return HOLDING_PERIOD_KEYS.map(({ key, label }) => ({
    label,
    count: n(raw[key]),
  }));
}

const DEFAULT_DISCLAIMER = "本报告由 AI 自动生成，仅供学习与娱乐参考，不构成任何投资建议。市场有风险，入市需谨慎。";

export function normalizeAnalysis(raw = {}) {
  const a = raw && typeof raw === "object" ? raw : {};
  // S1：严格按 AnalysisResult 结构映射
  //   final_report → 正文；overall_tags → 标签徽章；
  //   analysts[{skill_name, skill_id, analysis, suggestion, tags}] → 折叠卡片；
  //   debate_history[{round, topic, responses[{skill_name, response}]}] → 辩论区
  const analysts = arr(a.analysts || a.analyst_reports).map((x, i) => ({
    id: (x && (x.skill_id ?? x.id)) || `a${i + 1}`,
    name: (x && (x.skill_name || x.name)) || `分析师${i + 1}`,
    role: (x && (x.role || (x.skill_id ? `技能 ${x.skill_id}` : ""))) || "AI 分析师",
    tag: (x && x.tag) || "",
    tags: arr(x && x.tags),
    verdict: (x && x.verdict) || "",
    score: x && x.score != null ? n(x.score) : null,
    analysis: (x && (x.analysis || x.content || x.report || x.comment)) || "",
    suggestion: (x && x.suggestion) || "",
  }));
  return {
    report_markdown: a.final_report || a.report_markdown || a.report || a.markdown || "",
    tags: arr(a.overall_tags ?? a.humor_tags ?? a.tags),
    disclaimer: a.disclaimer || DEFAULT_DISCLAIMER,
    degraded: !!a.degraded,
    degraded_reason: a.degraded_reason || "",
    analysts,
    round_count: n(a.round_count),
    debate: normalizeDebateHistory(a.debate_history || a.debate || a.debate_log),
  };
}

// S1：debate_history[{round, topic, responses[{skill_name, response}]}] → 统一轮次结构；
// 兼容旧扁平形态 {speaker, role, point}
export function normalizeDebateHistory(raw) {
  const list = arr(raw);
  const rounds = [];
  list.forEach((d, i) => {
    if (!d || typeof d !== "object") return;
    if (Array.isArray(d.responses) || d.round != null || d.topic != null) {
      rounds.push({
        round: n(d.round) || i + 1,
        topic: d.topic || "",
        responses: arr(d.responses).map((r) => ({
          skill_name: (r && (r.skill_name || r.name || r.speaker)) || "",
          response: (r && (r.response || r.point || r.content)) || "",
        })),
      });
    } else {
      // 旧形态：单条 {speaker, role, point}
      rounds.push({
        round: i + 1,
        topic: "",
        responses: [
          {
            skill_name: (d.speaker || d.name) || "",
            response: (d.point || d.content) || "",
          },
        ],
      });
    }
  });
  return rounds;
}
