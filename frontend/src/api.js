// API 客户端：fetch 封装 + 离线演示数据（mock 结构完全符合 v2 API 契约）
// 上传与历史使用真实接口；开发期（DEV）后端不可用时自动降级为离线演示。

export class ApiError extends Error {
  constructor(message) {
    super(message);
    this.name = "ApiError";
  }
}

async function requestJson(path, options) {
  let res;
  try {
    res = await fetch(path, options);
  } catch {
    throw new ApiError("无法连接后端服务，请确认服务已启动（也可点击「载入演示数据」离线预览）");
  }
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = (data && (data.detail || data.message || data.error)) || "";
    } catch {
      /* 非 JSON 错误体 */
    }
    throw new ApiError(detail || `请求失败（HTTP ${res.status}）`);
  }
  return res.json();
}

// ---------- 真实接口 ----------
export async function analyzeFile(file) {
  const form = new FormData();
  form.append("file", file);
  let res;
  try {
    res = await fetch("/api/analyze", { method: "POST", body: form });
  } catch {
    if (import.meta.env.DEV) return startOfflineJob(file.name);
    throw new ApiError("无法连接后端服务，请确认服务已启动");
  }
  if (!res.ok) {
    let detail = "";
    try {
      const data = await res.json();
      detail = (data && (data.detail || data.message || data.error)) || "";
    } catch {
      /* 非 JSON 错误体 */
    }
    // 开发期后端未启动（vite 代理返回 5xx）时自动进入离线演示
    if (import.meta.env.DEV && res.status >= 500) return startOfflineJob(file.name);
    throw new ApiError(detail || `上传失败（HTTP ${res.status}），请检查文件格式`);
  }
  return res.json();
}

export function getJob(jobId) {
  if (mockJobs.has(jobId)) return Promise.resolve(pollMockJob(jobId));
  return requestJson(`/api/jobs/${encodeURIComponent(jobId)}`);
}

export async function listAnalyses() {
  try {
    const items = await requestJson("/api/analyses");
    return { items, offline: false };
  } catch (err) {
    if (import.meta.env.DEV) return { items: [], offline: true };
    throw err;
  }
}

export function getAnalysis(id) {
  return requestJson(`/api/analyses/${encodeURIComponent(id)}`);
}

// ---------- 离线演示任务（模拟进度，结构同 GET /api/jobs/{id}） ----------
const MOCK_STEPS = [
  { stage: "parse_trades", pct: 12, msg: "正在解析交割单文件…" },
  { stage: "parse_trades", pct: 25, msg: "解析完成，识别到 38 条成交记录" },
  { stage: "compute_metrics", pct: 38, msg: "正在计算收益指标、回撤与现金流调整…" },
  { stage: "analysts", pct: 48, done: 1, msg: "分析师 1/5 · 严谨派·老周 完成点评" },
  { stage: "analysts", pct: 57, done: 2, msg: "分析师 2/5 · 乐观派·小林 完成点评" },
  { stage: "analysts", pct: 65, done: 3, msg: "分析师 3/5 · 数据控·阿凯 完成点评" },
  { stage: "analysts", pct: 73, done: 4, msg: "分析师 4/5 · 风控官·陈姐 完成点评" },
  { stage: "analysts", pct: 80, done: 5, msg: "分析师 5/5 · 幽默派·大熊 完成点评" },
  { stage: "moderator", pct: 86, msg: "主持人正在汇总各方观点…" },
  { stage: "debate", pct: 92, msg: "分析师辩论进行中…" },
  { stage: "report", pct: 97, msg: "正在生成最终报告…" },
  { stage: "done", pct: 100, msg: "分析完成" },
];

const mockJobs = new Map();
let mockSeq = 0;

export function startOfflineJob(filename) {
  const jobId = `mock-${Date.now()}-${mockSeq++}`;
  mockJobs.set(jobId, { step: -1, filename: filename || "离线演示.xlsx" });
  return { job_id: jobId, offline: true };
}

function pollMockJob(jobId) {
  const job = mockJobs.get(jobId);
  if (!job) throw new ApiError("演示任务不存在");
  job.step += 1;
  const idx = Math.min(job.step, MOCK_STEPS.length - 1);
  const s = MOCK_STEPS[idx];
  if (idx === MOCK_STEPS.length - 1) {
    const built = buildMockResult();
    return {
      job_id: jobId,
      filename: job.filename,
      status: "done",
      stage: "done",
      pct: 100,
      message: "分析完成",
      analysts_done: 5,
      analysts_total: 5,
      error: null,
      result: { record_id: "mock-record-001", metrics: built.metrics, analysis: built.analysis },
    };
  }
  return {
    job_id: jobId,
    filename: job.filename,
    status: "running",
    stage: s.stage,
    pct: s.pct,
    message: s.msg,
    analysts_done: s.done || 0,
    analysts_total: 5,
    error: null,
    result: null,
  };
}

// ---------- 演示数据生成（自洽：由交易明细推导各项统计） ----------
function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const STOCK_POOL = [
  ["600519", "贵州茅台"],
  ["300750", "宁德时代"],
  ["002594", "比亚迪"],
  ["300308", "中际旭创"],
  ["300059", "东方财富"],
  ["600036", "招商银行"],
  ["600900", "长江电力"],
  ["000858", "五粮液"],
  ["002475", "立讯精密"],
  ["603259", "药明康德"],
  ["601919", "中远海控"],
  ["002230", "科大讯飞"],
  ["601012", "隆基绿能"],
  ["601899", "紫金矿业"],
  ["600276", "恒瑞医药"],
  ["600031", "三一重工"],
  ["002415", "海康威视"],
  ["601318", "中国平安"],
];

function addDays(base, days) {
  const d = new Date(base);
  d.setDate(d.getDate() + days);
  return d;
}

function isoDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const round2 = (v) => Math.round(v * 100) / 100;
const round4 = (v) => Math.round(v * 1e4) / 1e4;
const round6 = (v) => Math.round(v * 1e6) / 1e6;

function buildMockMetrics() {
  const rng = mulberry32(20260802);
  const startBase = new Date(2025, 2, 3); // 2025-03-03
  const trades = [];
  for (let i = 0; i < 28; i += 1) {
    const [code, name] = STOCK_POOL[Math.floor(rng() * STOCK_POOL.length)];
    const start = addDays(startBase, Math.floor(rng() * 200));
    const days = 2 + Math.floor(rng() * 58);
    const end = addDays(start, days);
    const qty = 100 + Math.floor(rng() * 20) * 100;
    const buyPrice = round2(6 + rng() * 170);
    const sellPrice = round2(buyPrice * (0.82 + rng() * 0.44));
    const buyAmount = round2(qty * buyPrice * 1.00025);
    const sellAmount = round2(qty * sellPrice * 0.9997);
    trades.push({
      code,
      name,
      buy_qty: qty,
      buy_amount: buyAmount,
      sell_qty: qty,
      sell_amount: sellAmount,
      pnl: round2(sellAmount - buyAmount),
      holding_days: days,
      start_date: isoDate(start),
      end_date: isoDate(end),
      status: "closed",
    });
  }

  // 按个股聚合
  const groups = new Map();
  for (const t of trades) {
    let g = groups.get(t.code);
    if (!g) {
      g = {
        code: t.code,
        name: t.name,
        trade_count: 0,
        closed_count: 0,
        win_count: 0,
        loss_count: 0,
        buy_amount: 0,
        sell_amount: 0,
        realized_pnl: 0,
        unrealized_pnl: 0,
        total_pnl: 0,
        holding_days: 0,
        holding_cost_value: 0,
        first_date: t.start_date,
        last_date: t.start_date,
      };
      groups.set(t.code, g);
    }
    g.trade_count += 1;
    g.buy_amount += t.buy_amount;
    g.sell_amount += t.sell_amount;
    if (t.start_date < g.first_date) g.first_date = t.start_date;
    if (t.end_date && t.end_date > g.last_date) g.last_date = t.end_date;
    if (t.status === "closed") {
      g.closed_count += 1;
      g.holding_days += t.holding_days;
      g.realized_pnl += t.pnl;
      g.total_pnl += t.pnl;
      if (t.pnl > 0) g.win_count += 1;
      else if (t.pnl < 0) g.loss_count += 1;
    }
  }

  const groupList = [...groups.values()];
  const stocks = groupList
    .slice()
    .sort((a, b) => a.code.localeCompare(b.code))
    .map((g) => ({
      code: g.code,
      name: g.name,
      buy_count: g.closed_count,
      sell_count: g.closed_count,
      buy_amount: round2(g.buy_amount),
      sell_amount: round2(g.sell_amount),
      realized_pnl: round2(g.realized_pnl),
      unrealized_pnl: round2(g.unrealized_pnl),
      total_pnl: round2(g.total_pnl),
      first_date: g.first_date,
      last_date: g.last_date,
      holding_days: g.closed_count ? Math.round(g.holding_days / g.closed_count) : null,
      status: "closed",
    }));

  const closed = trades.filter((t) => t.status === "closed");
  const wins = closed.filter((t) => t.pnl > 0);
  const losses = closed.filter((t) => t.pnl < 0);
  const totalProfit = wins.reduce((s, t) => s + t.pnl, 0);
  const totalLoss = losses.reduce((s, t) => s + t.pnl, 0);
  const winRate = wins.length + losses.length ? wins.length / (wins.length + losses.length) : 0;
  const profitLossRatio = totalLoss ? totalProfit / Math.abs(totalLoss) : 0;
  const maxSingleProfit = wins.length ? Math.max(...wins.map((t) => t.pnl)) : 0;
  const maxSingleLoss = losses.length ? Math.min(...losses.map((t) => t.pnl)) : 0;
  const avgDays = closed.length ? closed.reduce((s, t) => s + t.holding_days, 0) / closed.length : 0;

  // 月度盈亏 / 月度活跃度 / 持仓周期分布
  const monthMap = new Map();
  for (const t of closed) {
    const m = t.end_date.slice(0, 7);
    monthMap.set(m, (monthMap.get(m) || 0) + t.pnl);
  }
  const monthlyPnl = [...monthMap.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([month, pnl]) => ({ month, pnl: round2(pnl) }));

  const actMap = new Map();
  for (const t of trades) {
    const m = (t.end_date || t.start_date).slice(0, 7);
    const e = actMap.get(m) || { month: m, total_count: 0, buy_count: 0, sell_count: 0 };
    e.total_count += 1;
    e.buy_count += 1;
    e.sell_count += 1;
    actMap.set(m, e);
  }
  const monthlyActivity = [...actMap.values()].sort((a, b) => (a.month < b.month ? -1 : 1));

  // S2：持仓周期分布按后端 Schema 输出 dict {le_1d, 2_5d, 6_20d, gt_20d}
  const holdingPeriodDistribution = { le_1d: 0, "2_5d": 0, "6_20d": 0, gt_20d: 0 };
  for (const t of closed) {
    if (t.holding_days <= 1) holdingPeriodDistribution.le_1d += 1;
    else if (t.holding_days <= 5) holdingPeriodDistribution["2_5d"] += 1;
    else if (t.holding_days <= 20) holdingPeriodDistribution["6_20d"] += 1;
    else holdingPeriodDistribution.gt_20d += 1;
  }

  const pick = (g) => ({
    code: g.code,
    name: g.name,
    total_pnl: round2(g.total_pnl),
    win_count: g.win_count,
    loss_count: g.loss_count,
    trade_count: g.trade_count,
  });
  const topProfit = groupList.slice().sort((a, b) => b.total_pnl - a.total_pnl).slice(0, 10).map(pick);
  const topLoss = groupList.slice().sort((a, b) => a.total_pnl - b.total_pnl).slice(0, 10).map(pick);

  const favoriteStocksTop10 = groupList
    .slice()
    .sort((a, b) => b.trade_count - a.trade_count || Math.abs(b.total_pnl) - Math.abs(a.total_pnl))
    .slice(0, 10)
    .map((g) => ({ code: g.code, name: g.name, count: g.trade_count, amount: round2(g.buy_amount + g.sell_amount) }));

  // 账户与收益率曲线（现金流调整口径）
  const A0 = 500000;
  const grossDeposit = 150000;
  const grossWithdraw = 50000;
  const netTransferIn = grossDeposit - grossWithdraw;
  const endingBalance = 525700;
  const holdingCostValue = 231400;
  const holdingMarketValue = 248600;
  const totalAssets = endingBalance + holdingMarketValue;
  const startDate = trades.reduce((s, t) => (t.start_date < s ? t.start_date : s), trades[0].start_date);
  const endDate = trades.reduce((s, t) => (t.end_date && t.end_date > s ? t.end_date : s), startDate);
  const totalDays = Math.max(1, Math.round((new Date(endDate) - new Date(startDate)) / 86400000));
  const totalReturnRate = (totalAssets - netTransferIn - A0) / A0;
  const annualizedReturnRate = Math.pow(1 + totalReturnRate, 365 / totalDays) - 1;
  const totalCost = round2(trades.reduce((s, t) => s + t.buy_amount, 0));
  const totalAmount = round2(trades.reduce((s, t) => s + t.buy_amount + t.sell_amount, 0));

  const months = ["2025-03", "2025-04", "2025-05", "2025-06", "2025-07", "2025-08", "2025-09", "2025-10", "2025-11"];
  const monthEnds = ["2025-03-31", "2025-04-30", "2025-05-31", "2025-06-30", "2025-07-31", "2025-08-31", "2025-09-30", "2025-10-31", endDate];
  const equities = [497000, 521000, 561000, 538000, 592000, 689000, 655000, 718000, totalAssets];
  const cumNet = [0, 0, 50000, 50000, 50000, 150000, 150000, 150000, 150000];
  const returnCurve = months.map((month, i) => ({
    month,
    date: monthEnds[i],
    return_rate: round6((equities[i] - cumNet[i] - A0) / A0),
  }));
  const equityCurve = months.map((month, i) => ({ month, date: monthEnds[i], equity: equities[i] }));

  let peak = 0;
  let maxDrawdown = 0;
  for (const r of returnCurve) {
    const v = 1 + r.return_rate;
    peak = Math.max(peak, v);
    maxDrawdown = Math.max(maxDrawdown, 1 - v / peak); // 正值：0.5 = 50%
  }

  const realizedPnl = round2(closed.reduce((s, t) => s + t.pnl, 0));
  const pnl = {
    realized_pnl: realizedPnl,
    win_count: wins.length,
    loss_count: losses.length,
    win_rate: round6(winRate),
    total_profit: round2(totalProfit),
    total_loss: round2(totalLoss),
    profit_loss_ratio: round6(profitLossRatio),
    max_single_profit: round2(maxSingleProfit),
    max_single_loss: round2(maxSingleLoss),
    double_count: 1,
    halved_count: 0,
    unmatched_sell_amount: 0,
    monthly_pnl: monthlyPnl,
    equity_curve: equityCurve,
    return_curve: returnCurve,
    max_drawdown: round6(maxDrawdown),
    stock_leaderboard: { top_profit: topProfit, top_loss: topLoss },
  };

  const account = {
    initial_balance: A0,
    ending_balance: endingBalance,
    net_transfer_in: netTransferIn,
    gross_deposit: grossDeposit,
    gross_withdraw: grossWithdraw,
    opening_asset_value: A0,
    total_return_rate: round6(totalReturnRate),
    total_return_rate_net: round6((totalAssets - A0 - netTransferIn) / A0),
    annualized_return_rate: round6(annualizedReturnRate),
    realized_pnl: realizedPnl,
    total_cost: totalCost,
    total_cost_ratio: round6(totalCost / totalAmount),
    holding_market_value: holdingMarketValue,
    holding_cost_value: holdingCostValue,
    unrealized_pnl: round2(holdingMarketValue - holdingCostValue),
    market_value_source: "按成本估算",
  };

  const trading = {
    total_amount: totalAmount,
    total_count: trades.length * 2,
    buy_count: trades.length,
    sell_count: trades.length,
    distinct_stock_count: groups.size,
    current_holding_count: 0,
    avg_holding_period_days: round2(avgDays),
  };

  // M9：集中度按「前 5 大个股成交金额 / 总成交金额」（买卖合计），比率小数
  const totalTurnover = groupList.reduce((s, g) => s + g.buy_amount + g.sell_amount, 0);
  const top5Concentration = totalTurnover
    ? groupList
        .slice()
        .sort((a, b) => b.buy_amount + b.sell_amount - (a.buy_amount + a.sell_amount))
        .slice(0, 5)
        .reduce((s, g) => s + g.buy_amount + g.sell_amount, 0) / totalTurnover
    : 0;

  const maxPosGroup = groupList.slice().sort((a, b) => b.buy_amount - a.buy_amount)[0];
  const maxPosition = maxPosGroup
    ? {
        ratio: round4(maxPosGroup.buy_amount / Math.max(1, totalAssets)),
        code: maxPosGroup.code,
        name: maxPosGroup.name,
        date: maxPosGroup.last_date,
      }
    : { ratio: 0, code: null, name: null, date: null };

  // M5：style 按后端 Schema 输出对象（前端负责键名中文映射）
  const holdingStyle = avgDays <= 7 ? "短线" : avgDays <= 30 ? "波段" : "长线";
  const concentrationStyle = top5Concentration >= 0.5 ? "集中" : "分散";
  const riskStyle = maxPosition.ratio >= 0.5 || closed.length / Math.max(1, groups.size) > 2.2 ? "激进" : "均衡";
  const style = {
    holding_style: holdingStyle,
    concentration: concentrationStyle,
    risk_style: riskStyle,
    label: `${holdingStyle}·${concentrationStyle}·${riskStyle}`,
  };

  const behavior = {
    holding_period_distribution: holdingPeriodDistribution,
    monthly_activity: monthlyActivity,
    max_position: maxPosition,
    top5_concentration: round4(top5Concentration),
    favorite_stocks_top10: favoriteStocksTop10,
    style,
    special_operations: {
      reverse_repo: { count: 2, amount: 413.7 },
      dividend: { count: 3, amount: 1286.4 },
      bonus_share: { count: 1, qty: 20 },
      interest: { count: 1, amount: 96.5 },
      ipo: { count: 0, amount: 0 },
      other: { count: 0, amount: 0 },
    },
  };

  const meta = {
    is_partial: false,
    start_date: startDate,
    end_date: endDate,
    month_count: monthlyPnl.length,
    trade_count: trades.length,
    closed_count: closed.length,
    holding_count: 0,
    distinct_stock_count: groups.size,
    total_return_pct: round6(totalReturnRate), // 小数比率（0.5 = 50%）
    label: "完整周期",
    tags: ["演示数据", "离线预览"],
    filename: "离线演示.xlsx",
  };

  return { account, trading, pnl, behavior, stocks, trades, meta };
}

function buildMockAnalysis(m) {
  const account = m.account;
  const pnl = m.pnl;
  const trading = m.trading;
  const meta = m.meta;
  const behavior = m.behavior;
  const ratioTxt = pnl.profit_loss_ratio.toFixed(2);
  const concPct = (behavior.top5_concentration * 100).toFixed(1);
  const reportMarkdown = [
    "# Synalysis 投资行为报告",
    "",
    `> 分析区间：${meta.start_date} 至 ${meta.end_date} ｜ 完整交易 ${pnl.win_count + pnl.loss_count} 笔`,
    "",
    "## 一、收益概览",
    "",
    `- 累计收益率：**+${(account.total_return_rate * 100).toFixed(2)}%**（时间加权 TWR，逐日模拟）`,
    `- 年化收益率：+${(account.annualized_return_rate * 100).toFixed(2)}%`,
    `- 最大回撤：${(pnl.max_drawdown * 100).toFixed(2)}%`,
    `- 胜率：${(pnl.win_rate * 100).toFixed(1)}%（${pnl.win_count} 胜 / ${pnl.loss_count} 负，按完整交易）`,
    `- 盈亏比：**1 : ${ratioTxt}**（总盈利 / 总亏损）`,
    `- 账户翻倍 ${pnl.double_count} 次 / 腰斩 ${pnl.halved_count} 次`,
    "",
    "## 二、风格画像",
    "",
    `平均持仓周期 **${trading.avg_holding_period_days.toFixed(1)} 天**，属于中短线风格；交易涉及 ${trading.distinct_stock_count} 只个股。`,
    "偏好科技成长类标的，采用分批建仓、集中持有少数品种的策略。",
    "",
    "## 三、亮点与风险",
    "",
    "1. 收益主要由 8-10 月贡献，期间市场活跃度较高；",
    "2. 胜率接近六成、盈亏比大于 1，整体策略具备正期望；",
    `3. 前 5 大个股成交金额占比约 ${concPct}%，仓位集中，回撤风险需要关注；`,
    "4. 交易频率偏高，佣金与印花税等摩擦成本对收益有一定侵蚀。",
    "",
    "## 四、优化建议",
    "",
    "- 控制单一个股仓位上限，避免集中度过高；",
    "- 降低无效交易频率，优先在胜率较高的模式内出手；",
    "- 坚持止损纪律，本周期最大单笔亏损约 " + `¥${Math.abs(pnl.max_single_loss).toLocaleString("zh-CN")}` + "，可考虑设置更早的止损线。",
    "",
    "> 本报告由 AI 自动生成，仅供学习与娱乐参考，不构成任何投资建议。",
  ].join("\n");

  const analysts = [
    {
      skill_name: "严谨派·老周",
      skill_id: "rigorous",
      analysis: `**总体评价：** 收益质量中等，主要贡献集中在少数月份。\n\n- 累计收益率 +${(account.total_return_rate * 100).toFixed(2)}%，但月度分布不均；\n- 8 月与 10 月贡献了大部分盈利，其余月份整体平淡。`,
      suggestion: "建议关注月度归因，避免把行情 Beta 当成能力 Alpha；对单一月份贡献过大的收益保持警惕。",
      tags: ["数据控", "纪律派"],
    },
    {
      skill_name: "乐观派·小林",
      skill_id: "optimistic",
      analysis: `**乐观视角：** 胜率 ${(pnl.win_rate * 100).toFixed(1)}%、盈亏比 1 : ${ratioTxt}，说明策略具备正期望。\n\n- 持仓周期与市场节奏匹配；\n- 期末已无持仓，收益已落袋为安。`,
      suggestion: "保持现有纪律，在胜率较高的模式内继续出手，避免因短期波动频繁改弦更张。",
      tags: ["成长视角", "顺势而为"],
    },
    {
      skill_name: "数据控·阿凯",
      skill_id: "quant",
      analysis: `**量化视角：** 最大回撤 ${(pnl.max_drawdown * 100).toFixed(2)}%，处于可接受范围。\n\n- 账户翻倍 ${pnl.double_count} 次、腰斩 ${pnl.halved_count} 次；\n- 但换手偏高，摩擦成本约占成交额的 ${(account.total_cost_ratio * 100).toFixed(1)}%，存在优化空间。`,
      suggestion: "降低无效交易频率，优先在胜率较高的模式内出手，控制摩擦成本对收益的侵蚀。",
      tags: ["统计狂魔", "成本敏感"],
    },
    {
      skill_name: "风控官·陈姐",
      skill_id: "risk",
      analysis: `**风控视角：** 前 5 大个股成交金额占比约 ${concPct}%，集中度偏高。\n\n- 单一赛道波动会直接放大回撤；\n- 历史单票最大仓位 ${(behavior.max_position.ratio * 100).toFixed(1)}%（${behavior.max_position.name}），需重点关注。`,
      suggestion: "建议单只个股仓位上限控制在 20% 以内，并严格执行止损纪律。",
      tags: ["风险第一", "仓位管理"],
    },
    {
      skill_name: "幽默派·大熊",
      skill_id: "humor",
      analysis: `**幽默点评：** 翻倍 ${pnl.double_count} 次、腰斩 ${pnl.halved_count} 次，说明账户的命比散户的嘴硬。\n\n- 收益全靠加仓撑，回撤期在潜水；\n- 活着就是胜利。`,
      suggestion: "继续坚持纪律，别把运气当实力；下次回撤期记得关灯吃面也要看财报。",
      tags: ["气氛组", "人间清醒"],
    },
  ];

  // S1：辩论区按真实结构 [{round, topic, responses[{skill_name, response}]}]
  const debateHistory = [
    {
      round: 1,
      topic: "当前收益质量与集中度风险如何权衡？",
      responses: [
        { skill_name: "严谨派·老周", response: "收益率主要靠 8-10 月贡献，前三季度整体平庸，需要看月度归因。" },
        { skill_name: "风控官·陈姐", response: `单一个股仓位一度超过 40%，集中度偏高，回撤风险大于收益质量。` },
        { skill_name: "乐观派·小林", response: `胜率接近六成、盈亏比 1 : ${ratioTxt}，说明策略具备正期望，不必过度悲观。` },
        { skill_name: "数据控·阿凯", response: `平均持仓 ${trading.avg_holding_period_days.toFixed(1)} 天属于中短线，换手偏高，交易成本占成交额约 ${(account.total_cost_ratio * 100).toFixed(1)}%。` },
        { skill_name: "幽默派·大熊", response: `翻倍 ${pnl.double_count} 次说明运气还行，腰斩 ${pnl.halved_count} 次说明风控没躺平。` },
      ],
    },
    {
      round: 2,
      topic: "交易频率与摩擦成本是否需要优化？",
      responses: [
        { skill_name: "数据控·阿凯", response: "换手偏高导致摩擦成本侵蚀收益，建议把无效交易砍半。" },
        { skill_name: "风控官·陈姐", response: "同意，降低频率同时单票仓位上限控制在 20% 以内。" },
        { skill_name: "严谨派·老周", response: "综合来看：纪律尚可，集中度与手续费是下一步优化重点。" },
      ],
    },
  ];

  return {
    final_report: reportMarkdown,
    overall_tags: ["收益全靠加仓撑", "满仓选手", "割肉有纪律", "回撤期在潜水"],
    disclaimer: "本报告由 AI 基于交割单数据自动生成，仅供学习与娱乐参考，不构成任何投资建议。市场有风险，入市需谨慎。",
    degraded: false,
    round_count: debateHistory.length,
    analysts,
    debate_history: debateHistory,
  };
}

function buildMockResult() {
  const metrics = buildMockMetrics();
  return { metrics, analysis: buildMockAnalysis(metrics) };
}
