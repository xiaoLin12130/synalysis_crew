// 格式化工具：全中文展示口径（需求 1.7）
export function num(v, fallback = 0) {
  // null / undefined / 空串 → 兜底（数据字典：None 显示 —，禁止变 0）
  if (v === null || v === undefined || v === "") return fallback;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : fallback;
}

function compactCny(abs, sign, digits = 2) {
  if (abs >= 1e8) return `${sign}${(abs / 1e8).toFixed(digits)}亿`;
  if (abs >= 1e4) return `${sign}${(abs / 1e4).toFixed(digits)}万`;
  return `${sign}${abs.toFixed(digits)}`;
}

export function fmtMoney(v, digits = 2) {
  const n = num(v, NaN);
  if (!Number.isFinite(n)) return "—";
  return `¥${n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function fmtSignedMoney(v, digits = 2) {
  const n = num(v, NaN);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return `${sign}¥${Math.abs(n).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

export function fmtCny(v) {
  const n = num(v, NaN);
  if (!Number.isFinite(n)) return "—";
  return compactCny(Math.abs(n), n < 0 ? "-" : "");
}

export function fmtSignedCny(v) {
  const n = num(v, NaN);
  if (!Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : n < 0 ? "-" : "";
  return compactCny(Math.abs(n), sign);
}

export function fmtPct(v, { digits = 2, signed = false, fallback = "—" } = {}) {
  const n = num(v, NaN);
  if (!Number.isFinite(n)) return fallback;
  const sign = signed && n > 0 ? "+" : "";
  return `${sign}${(n * 100).toFixed(digits)}%`;
}

// 盈亏比：1 : N（如 1 : 1.04）
export function fmtRatio(v) {
  const n = num(v, NaN);
  if (!Number.isFinite(n) || n <= 0) return "—";
  return `1 : ${n.toFixed(2)}`;
}

// 月份统一「2025年11月」格式
export function fmtMonth(m) {
  if (!m) return "—";
  const match = String(m).trim().match(/^(\d{4})[-/](\d{1,2})/);
  if (match) return `${match[1]}年${Number(match[2])}月`;
  return String(m);
}

// 日期统一「2025-11-27」格式
export function fmtDate(d) {
  if (!d) return "—";
  const match = String(d).trim().match(/^(\d{4})-(\d{2})-(\d{2})/);
  return match ? `${match[1]}-${match[2]}-${match[3]}` : String(d).slice(0, 10);
}

export function fmtDateTime(ts) {
  if (!ts) return "—";
  const s = String(ts).trim();
  // 紧凑时间戳：20260802-230951 / 20260802_230951 / 20260802230951 → YYYY-MM-DD HH:MM
  const compact = s.match(/^(\d{4})(\d{2})(\d{2})[-_/]?(\d{2})(\d{2})(\d{2})$/);
  if (compact) return `${compact[1]}-${compact[2]}-${compact[3]} ${compact[4]}:${compact[5]}`;
  const dateOnly = s.match(/^(\d{4})(\d{2})(\d{2})$/);
  if (dateOnly) return `${dateOnly[1]}-${dateOnly[2]}-${dateOnly[3]}`;
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return String(ts).slice(0, 16);
  const p = (x) => String(x).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

// 可空计数：null / undefined / NaN → 「—」（数据字典：None 一律显示 —）
export function fmtCount(v) {
  const n = num(v, NaN);
  return Number.isFinite(n) ? n.toLocaleString("zh-CN") : "—";
}

export function cnStatus(s) {
  const v = String(s || "").toLowerCase();
  if (!v) return "—";
  if (v.includes("hold") || v === "open" || v.includes("持有")) return "持有中";
  return "已清仓";
}

export function cnSource(s) {
  const v = String(s || "").toLowerCase();
  if (v.includes("market") || v.includes("实时")) return "实时行情";
  return "按成本估算";
}

export function fmtQty(v) {
  const n = num(v, NaN);
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString("zh-CN");
}

export function moneyClass(v) {
  const n = num(v, NaN);
  if (!Number.isFinite(n) || n === 0) return "";
  return n > 0 ? "pos" : "neg";
}
