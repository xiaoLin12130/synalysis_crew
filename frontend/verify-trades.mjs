// 轻量断言：node verify-trades.mjs（不引入测试框架）
// 验证 src/tradeUtils.js 的盈亏比例计算与排序（需求 1.9）+ 阶段中文映射。
import assert from "node:assert/strict";
import { sortTrades, tradePnlRatio } from "./src/tradeUtils.js";
import { stageLabel } from "./src/stages.js";
import { fmtPct } from "./src/format.js";

const t = (over) => ({
  code: "600519",
  name: "贵州茅台",
  buy_qty: 100,
  buy_amount: 150000,
  sell_qty: 100,
  sell_amount: 131250,
  pnl: -18750,
  holding_days: 12,
  start_date: "2025-03-03",
  end_date: "2025-03-15",
  status: "closed",
  ...over,
});

// ---- 盈亏比例：pnl ÷ buy_amount；buy_amount 0/缺失 → null（显示 —） ----
assert.equal(tradePnlRatio(t({})), -0.125);
assert.equal(tradePnlRatio(t({ pnl: 1000, buy_amount: 20000 })), 0.05);
assert.equal(tradePnlRatio(t({ buy_amount: 0 })), null);
assert.equal(tradePnlRatio(t({ buy_amount: null })), null);
assert.equal(tradePnlRatio(t({ buy_amount: undefined })), null);
assert.equal(tradePnlRatio(t({ pnl: null })), null);
assert.equal(tradePnlRatio(t({ pnl: "abc" })), null);
// 字符串数值兼容 + 展示格式（+10.0% / -12.5% / 0.0%）
assert.equal(tradePnlRatio(t({ pnl: "500", buy_amount: "5000" })), 0.1);
assert.equal(fmtPct(0.1, { signed: true, digits: 1 }), "+10.0%");
assert.equal(fmtPct(-0.125, { signed: true, digits: 1 }), "-12.5%");
assert.equal(fmtPct(0, { signed: true, digits: 1 }), "0.0%");

// ---- 排序：默认盈亏降序；null 沉底；同值按 end_date 降序 ----
const rows = [
  t({ code: "A", pnl: 100, end_date: "2025-01-10" }),
  t({ code: "B", pnl: -50, end_date: "2025-02-01" }),
  t({ code: "C", pnl: 100, end_date: "2025-02-01" }),
  t({ code: "D", pnl: null, end_date: "2025-03-01" }),
];
assert.deepEqual(sortTrades(rows, "pnl", "desc").map((r) => r.code), ["C", "A", "B", "D"]);
assert.deepEqual(sortTrades(rows, "pnl", "asc").map((r) => r.code), ["B", "C", "A", "D"]);
assert.deepEqual(sortTrades(rows).map((r) => r.code), ["C", "A", "B", "D"], "默认按盈亏降序");
assert.deepEqual(sortTrades(undefined).map((r) => r.code), [], "非数组输入返回空数组");

// ---- 盈亏比例排序（null 沉底） ----
const ratioRows = [
  t({ code: "R1", pnl: 1000, buy_amount: 10000 }), // +10%
  t({ code: "R2", pnl: -500, buy_amount: 10000 }), // -5%
  t({ code: "R3", pnl: 300, buy_amount: 0 }), // null
];
assert.deepEqual(sortTrades(ratioRows, "pnl_ratio", "desc").map((r) => r.code), ["R1", "R2", "R3"]);
assert.deepEqual(sortTrades(ratioRows, "pnl_ratio", "asc").map((r) => r.code), ["R2", "R1", "R3"]);

// ---- 持股天数 / 买入金额 / 卖出金额排序 ----
const h1 = t({ code: "H1", holding_days: 30, buy_amount: 100000, sell_amount: 120000 });
const h2 = t({ code: "H2", holding_days: 5, buy_amount: 20000, sell_amount: 15000 });
assert.deepEqual(sortTrades([h1, h2], "holding_days", "asc").map((r) => r.code), ["H2", "H1"]);
assert.deepEqual(sortTrades([h1, h2], "buy_amount", "desc").map((r) => r.code), ["H1", "H2"]);
assert.deepEqual(sortTrades([h1, h2], "sell_amount", "asc").map((r) => r.code), ["H2", "H1"]);

// ---- 阶段中文映射（侧栏指示器「当前阶段」） ----
assert.equal(stageLabel("analysts"), "分析师点评");
assert.equal(stageLabel("moderator"), "主持人");
assert.equal(stageLabel("parse_trades"), "解析交割单");
assert.equal(stageLabel("queued"), "排队等待");
assert.equal(stageLabel("done"), "完成");

console.log("ALL TRADE ASSERTIONS PASSED");
