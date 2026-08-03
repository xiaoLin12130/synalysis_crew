import React, { useMemo, useState } from "react";
import { cnStatus, fmtDate, fmtMoney, fmtPct, fmtQty, fmtSignedMoney, moneyClass } from "../format";
import { sortTrades, tradePnlRatio } from "../tradeUtils";

// 可排序列（需求 1.9）：盈亏、盈亏比例、持股天数、买入金额、卖出金额；默认盈亏降序
const SORTABLE_COLUMNS = [
  { key: "buy_amount", label: "买入（量 / 金额）" },
  { key: "sell_amount", label: "卖出（量 / 金额）" },
  { key: "pnl_ratio", label: "盈亏比例" },
  { key: "pnl", label: "盈亏" },
  { key: "holding_days", label: "持股天数" },
];

export default function TradeTable({ trades }) {
  // M10：交易明细仅展示完整交易（trades 契约全部 closed，无「持有中」）
  const list = (Array.isArray(trades) ? trades : []).filter((t) => t && t.status === "closed");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [sortKey, setSortKey] = useState("pnl");
  const [sortDir, setSortDir] = useState("desc");

  const handleSort = (key) => {
    if (key === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir(key === "pnl" ? "desc" : "asc");
    }
  };

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = list.filter((t) => {
      if (status === "closed" && t.status !== "closed") return false;
      if (q && !String(t.code || "").toLowerCase().includes(q) && !String(t.name || "").toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
    return sortTrades(filtered, sortKey, sortDir);
  }, [list, query, status, sortKey, sortDir]);

  return (
    <div className="card table-card">
      <div className="search-row">
        <input
          className="search-input"
          placeholder="搜索股票代码或名称…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select className="filter-select" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="all">全部状态</option>
          <option value="closed">已清仓</option>
        </select>
        <span className="search-meta">完整交易 {list.length} 笔（全部已清仓）</span>
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>股票</th>
              {SORTABLE_COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className={`sortable${sortKey === c.key ? " active" : ""}`}
                  onClick={() => handleSort(c.key)}
                  title={`点击按${c.label.replace(/（.*/, "")}排序`}
                >
                  {c.label}
                  {sortKey === c.key ? <span className="sort-arrow">{sortDir === "asc" ? "▲" : "▼"}</span> : null}
                </th>
              ))}
              <th>起止日期</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => {
              const ratio = tradePnlRatio(t);
              return (
                <tr key={`${t.code || ""}-${t.start_date || ""}-${i}`}>
                  <td>
                    <div className="cell-main">{t.name || "—"}</div>
                    <div className="cell-sub">{t.code || ""}</div>
                  </td>
                  <td>
                    <div className="num">{fmtQty(t.buy_qty)} 股</div>
                    <div className="cell-sub num">{fmtMoney(t.buy_amount)}</div>
                  </td>
                  <td>
                    <div className="num">{fmtQty(t.sell_qty)} 股</div>
                    <div className="cell-sub num">{fmtMoney(t.sell_amount)}</div>
                  </td>
                  <td className={`num ${moneyClass(ratio)}`}>
                    {ratio === null ? "—" : fmtPct(ratio, { signed: true, digits: 1 })}
                  </td>
                  <td className={`num ${moneyClass(t.pnl)}`}>{fmtSignedMoney(t.pnl)}</td>
                  <td className="num">{t.holding_days != null ? `${t.holding_days} 天` : "—"}</td>
                  <td className="num">
                    {fmtDate(t.start_date)} ～ {fmtDate(t.end_date)}
                  </td>
                  <td>
                    <span className="badge closed">{cnStatus(t.status)}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 ? (
          <div className="table-empty">没有符合条件的交易（完整交易 = 个股首次买入至清仓的闭环）</div>
        ) : null}
      </div>
      <div className="table-note">
        注：盈亏已扣除买入费用（计入买入金额）与卖出费用（从卖出金额扣减）；盈亏比例 = 盈亏 ÷ 买入金额；分红、逆回购、银行转账等操作不在此表展示。点击列头可排序（默认按盈亏降序）。
      </div>
    </div>
  );
}
