import React, { useMemo, useState } from "react";
import { cnStatus, fmtDate, fmtMoney, fmtQty, fmtSignedMoney, moneyClass } from "../format";

export default function TradeTable({ trades }) {
  // M10：交易明细仅展示完整交易（trades 契约全部 closed，无「持有中」）
  const list = (Array.isArray(trades) ? trades : []).filter((t) => t && t.status === "closed");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = list.filter((t) => {
      if (status === "closed" && t.status !== "closed") return false;
      if (q && !String(t.code || "").toLowerCase().includes(q) && !String(t.name || "").toLowerCase().includes(q)) {
        return false;
      }
      return true;
    });
    return filtered.slice().sort((a, b) => {
      const da = a.end_date || a.start_date || "";
      const db = b.end_date || b.start_date || "";
      if (da === db) return String(a.code).localeCompare(String(b.code));
      return da > db ? -1 : 1;
    });
  }, [list, query, status]);

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
              <th>买入（量 / 金额）</th>
              <th>卖出（量 / 金额）</th>
              <th>盈亏</th>
              <th>持股天数</th>
              <th>起止日期</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t, i) => {
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
        注：盈亏已扣除买入费用（计入买入金额）与卖出费用（从卖出金额扣减）；分红、逆回购、银行转账等操作不在此表展示。
      </div>
    </div>
  );
}
