// 轻量断言：node verify-pnl.mjs（不引入测试框架）
// 验证 src/pnlUtils.js 的 500 元步长盈亏分箱（需求 2.2）。
import assert from "node:assert/strict";
import { buildPnlDistribution } from "./src/pnlUtils.js";

const t = (pnl) => ({ code: "X", name: "测试", pnl });

const bins = buildPnlDistribution([
  t(-10001), // 开区间 ≤-10000
  t(-10000), // [-10000,-9500)
  t(-9500), // [-9500,-9000)
  t(-501), // [-1000,-500)
  t(-500), // [-500,500) 0 档
  t(0), // 0 档
  t(499), // 0 档
  t(500), // [500,1000)
  t(9999), // [9500,10000)
  t(10000), // 开区间 >10000
  t(12000), // 开区间 >10000
  t(null), // 忽略
  t("abc"), // 忽略
]);

// 41 档：开区间 + 19 负档 + 0 档 + 19 正档 + 开区间
assert.equal(bins.length, 41);
assert.equal(bins[0].label, "≤ -10000");
assert.equal(bins[0].count, 1);
assert.equal(bins[1].label, "-10000~-9500");
assert.equal(bins[1].count, 1);

const zero = bins.find((b) => b.zero);
assert.equal(zero.label, "-500~500");
assert.equal(zero.count, 3); // -500 / 0 / 499
assert.equal(zero.positive, false);

const posBin = bins.find((b) => b.label === "500~1000");
assert.equal(posBin.count, 1);
assert.equal(posBin.positive, true);

const negBin = bins.find((b) => b.label === "-1000~-500");
assert.equal(negBin.count, 1);
assert.equal(negBin.positive, false);

const lastInner = bins.find((b) => b.label === "9500~10000");
assert.equal(lastInner.count, 1);
assert.equal(bins[bins.length - 1].label, "> 10000");
assert.equal(bins[bins.length - 1].count, 2); // 10000 / 12000

// 总数核对：11 个有效值全部落箱
assert.equal(bins.reduce((s, b) => s + b.count, 0), 11);

// 不重叠：任一数值只落一个箱（用 -2500 与 2500 抽查）
const pick = (v) => bins.filter((b) => v >= b.min && v < b.max);
assert.equal(pick(-2500).length, 1);
assert.equal(pick(2500).length, 1);

// 空输入 / 非数组
assert.equal(buildPnlDistribution([]).reduce((s, b) => s + b.count, 0), 0);
assert.equal(buildPnlDistribution(undefined).reduce((s, b) => s + b.count, 0), 0);

console.log("ALL PNL ASSERTIONS PASSED");
