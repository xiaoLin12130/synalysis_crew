// 轻量断言：node verify-normalize.mjs（不引入测试框架）
// 直接验证 src/normalize.js 纯函数对 v2 API 契约的映射。
import assert from "node:assert/strict";
import { normalizeAnalysis, normalizeHoldingPeriodDistribution, normalizeMetrics } from "./src/normalize.js";
import { fmtDateTime, fmtPct } from "./src/format.js";

// ---- S1：AnalysisResult 真实结构映射 ----
const a = normalizeAnalysis({
  final_report: "# 报告正文",
  overall_tags: ["满仓选手"],
  analysts: [
    { skill_name: "严谨派·老周", skill_id: "rigorous", analysis: "分析内容", suggestion: "优化建议", tags: ["数据控"] },
  ],
  debate_history: [
    { round: 1, topic: "集中度风险？", responses: [{ skill_name: "风控官·陈姐", response: "仓位过高" }] },
  ],
  disclaimer: "免责",
  degraded: true,
  round_count: 1,
});
assert.equal(a.report_markdown, "# 报告正文");
assert.deepEqual(a.tags, ["满仓选手"]);
assert.equal(a.analysts[0].name, "严谨派·老周");
assert.equal(a.analysts[0].id, "rigorous");
assert.equal(a.analysts[0].analysis, "分析内容");
assert.equal(a.analysts[0].suggestion, "优化建议");
assert.deepEqual(a.analysts[0].tags, ["数据控"]);
assert.equal(a.debate.length, 1);
assert.equal(a.debate[0].round, 1);
assert.equal(a.debate[0].topic, "集中度风险？");
assert.equal(a.debate[0].responses[0].skill_name, "风控官·陈姐");
assert.equal(a.debate[0].responses[0].response, "仓位过高");
assert.equal(a.degraded, true);
assert.equal(a.round_count, 1);

// ---- S1：兼容旧字段形态（report_markdown / name+content / speaker+point）----
const legacy = normalizeAnalysis({
  report_markdown: "旧报告",
  humor_tags: ["旧标签"],
  analysts: [{ name: "张三", content: "旧内容" }],
  debate: [{ speaker: "张三", point: "旧观点" }],
});
assert.equal(legacy.report_markdown, "旧报告");
assert.deepEqual(legacy.tags, ["旧标签"]);
assert.equal(legacy.analysts[0].name, "张三");
assert.equal(legacy.analysts[0].analysis, "旧内容");
assert.equal(legacy.debate[0].responses[0].skill_name, "张三");
assert.equal(legacy.debate[0].responses[0].response, "旧观点");

// ---- S2：holding_period_distribution dict → 数组 + 中文标签 ----
const dist = normalizeHoldingPeriodDistribution({ le_1d: 3, "2_5d": 2, "6_20d": 4, gt_20d: 1 });
assert.deepEqual(dist, [
  { label: "≤1天", count: 3 },
  { label: "2–5天", count: 2 },
  { label: "6–20天", count: 4 },
  { label: ">20天", count: 1 },
]);

// ---- S2/M7：metrics 归一化（dict 形状、null 比率保留 NaN 不落 0）----
const m = normalizeMetrics({
  account: { total_return_rate: null, total_return_rate_net: undefined, annualized_return_rate: null },
  pnl: {
    win_rate: null,
    win_count: null,
    loss_count: null,
    return_curve: [{ month: "2025-03", date: "2025-03-31", return_rate: 0.123 }],
  },
  trading: { avg_holding_period_days: null },
  behavior: {
    holding_period_distribution: { le_1d: 1, "2_5d": 0, "6_20d": 0, gt_20d: 0 },
    monthly_activity: [{ month: "2025-03", total_count: 8, buy_count: 4, sell_count: 4 }],
    max_position: { ratio: 0.23, code: "600519", name: "贵州茅台", date: "2025-06-12" },
    top5_concentration: 0.42,
    favorite_stocks_top10: [{ code: "600519", name: "贵州茅台", count: 3, amount: 123456 }],
  },
  meta: { is_partial: true },
});
assert.ok(Number.isNaN(m.account.total_return_rate), "total_return_rate null 必须保留 NaN");
assert.ok(Number.isNaN(m.account.total_return_rate_net));
assert.ok(Number.isNaN(m.account.annualized_return_rate));
assert.ok(Number.isNaN(m.pnl.win_rate));
assert.ok(Number.isNaN(m.pnl.win_count));
assert.ok(Number.isNaN(m.trading.avg_holding_period_days));
assert.deepEqual(m.behavior.holding_period_distribution, [
  { label: "≤1天", count: 1 },
  { label: "2–5天", count: 0 },
  { label: "6–20天", count: 0 },
  { label: ">20天", count: 0 },
]);
assert.equal(m.behavior.monthly_activity[0].count, 8);
assert.equal(m.behavior.max_position.ratio, 0.23);
assert.equal(m.behavior.max_position.name, "贵州茅台");
assert.equal(m.behavior.favorite_stocks_top10[0].amount, 123456);
assert.equal(m.meta.is_partial, true);
assert.equal(m.pnl.return_curve[0].return_rate, 0.123);

// 比率非空时保持小数（S3 由展示层 ×100）
const m2 = normalizeMetrics({ account: { total_return_rate: 0.5 } });
assert.equal(m2.account.total_return_rate, 0.5);

// ---- 数据字典兜底：null → 「—」；时间戳格式化 ----
assert.equal(fmtPct(null), "—");
assert.equal(fmtPct(undefined), "—");
assert.equal(fmtPct(0.5), "50.00%");
assert.equal(fmtDateTime("20260802-230951"), "2026-08-02 23:09");
assert.equal(fmtDateTime("20260802230951"), "2026-08-02 23:09");

console.log("ALL NORMALIZE ASSERTIONS PASSED");
