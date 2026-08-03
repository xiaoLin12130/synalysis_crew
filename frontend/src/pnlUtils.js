// 盈亏分布纯函数（需求 2.2）：500 元步长分箱，超出 ±10000 合并开区间；
// 区间采用 [min, max) 不重叠口径；0 档为 [-500, 500) 中性灰。不依赖 React，可被 node 断言。

export const PNL_BIN_STEP = 500;
export const PNL_BIN_CAP = 10000;

export function pnlBinLabel(min, max) {
  if (min === -Infinity) return "≤ -10000";
  if (max === Infinity) return "> 10000";
  return `${min}~${max}`;
}

export function buildPnlDistribution(trades, step = PNL_BIN_STEP, cap = PNL_BIN_CAP) {
  const bins = [];
  const push = (min, max, positive, zero) => {
    bins.push({ min, max, positive, zero, count: 0 });
  };
  push(-Infinity, -cap, false, false);
  // 负区间 [-cap, -step) 与正区间 [step, cap) 各 19 档；0 档 [-step, step) 跨一个步长（含 0）
  for (let n = -cap; n < -step; n += step) push(n, n + step, false, false);
  push(-step, step, false, true);
  for (let n = step; n < cap; n += step) push(n, n + step, true, false);
  push(cap, Infinity, true, false);

  const list = Array.isArray(trades) ? trades : [];
  for (const t of list) {
    const raw = t && t.pnl;
    // 数据字典：null/undefined/空串 = 无数据，跳过（不得当作 0 计入 0 档）
    if (raw == null || raw === "") continue;
    const v = Number(raw);
    if (!Number.isFinite(v)) continue;
    // 线性扫描（41 档 × N 笔，N 很小）：避免零档跨步长导致的索引偏移
    for (const b of bins) {
      if (v >= b.min && v < b.max) {
        b.count += 1;
        break;
      }
    }
  }
  return bins.map((b) => ({ ...b, label: pnlBinLabel(b.min, b.max) }));
}
