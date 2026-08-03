// 交易明细纯函数：盈亏比例计算与排序（需求 1.9），不依赖 React，可被 node 直接断言

// 盈亏比例 = pnl ÷ buy_amount；buy_amount 为 0 / 缺失 / 非数时返回 null（显示 —）
export function tradePnlRatio(t) {
  if (!t) return null;
  const pnl = t.pnl == null || t.pnl === "" ? NaN : Number(t.pnl);
  const buy = t.buy_amount == null || t.buy_amount === "" ? NaN : Number(t.buy_amount);
  if (!Number.isFinite(pnl) || !Number.isFinite(buy) || buy <= 0) return null;
  return pnl / buy;
}

// 排序取值：pnl_ratio 走比例计算，其余取数值字段；缺失 / 非数一律 null（排序沉底）
export function tradeSortValue(t, key) {
  if (!t) return null;
  if (key === "pnl_ratio") return tradePnlRatio(t);
  const v = t[key];
  if (v == null || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

// 排序：dir = "asc" | "desc"；null 恒沉底；同值时按 end_date 降序 → code 升序保持稳定次序
export function sortTrades(trades, key = "pnl", dir = "desc") {
  const list = Array.isArray(trades) ? trades.slice() : [];
  const sign = dir === "asc" ? 1 : -1;
  list.sort((a, b) => {
    const va = tradeSortValue(a, key);
    const vb = tradeSortValue(b, key);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    if (va !== vb) return (va < vb ? -1 : 1) * sign;
    const da = a.end_date || a.start_date || "";
    const db = b.end_date || b.start_date || "";
    if (da !== db) return da > db ? -1 : 1;
    return String(a.code || "").localeCompare(String(b.code || ""));
  });
  return list;
}
