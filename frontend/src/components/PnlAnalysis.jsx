import React from "react";
import { fmtCny, fmtCount, fmtDate, fmtPct, fmtRatio, fmtSignedCny, moneyClass } from "../format";
import { PnlDistributionChart } from "./Charts";

function RankCard({ title, note, rows, negative }) {
  const list = Array.isArray(rows) ? rows : [];
  const maxAbs = Math.max(1, ...list.map((r) => Math.abs(Number(r.total_pnl) || 0)));
  return (
    <div className="card">
      <h3 className="card-title">{title}</h3>
      <p className="card-sub">{note}</p>
      {list.length === 0 ? (
        <div className="empty">暂无数据</div>
      ) : (
        <div className="rank-list">
          {list.map((r, i) => {
            const v = Number(r.total_pnl) || 0;
            const width = Math.max(4, (Math.abs(v) / maxAbs) * 100);
            return (
              <div key={`${r.code}-${i}`} className="rank-row">
                <div className="rank-head">
                  <div>
                    <span className="rank-no">{i + 1}</span> <b>{r.name || "—"}</b>{" "}
                    <span className="cell-sub">{r.code || ""}</span>
                  </div>
                  <div className={`rank-val ${moneyClass(v)}`}>{fmtSignedCny(v)}</div>
                </div>
                <div className="bar-track">
                  <div className={`bar-fill${negative ? " loss" : ""}`} style={{ width: `${width}%` }} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function PnlAnalysis({ metrics }) {
  const pnl = metrics.pnl || {};
  const leaderboard = pnl.stock_leaderboard || {};
  const closed = (Array.isArray(metrics.trades) ? metrics.trades : []).filter((t) => t.pnl != null);
  // v2.3：翻倍/腰斩事件清单（按日期升序）
  const eventList = [
    ...(Array.isArray(pnl.double_events) ? pnl.double_events.map((e) => ({ ...e, type: "double" })) : []),
    ...(Array.isArray(pnl.halved_events) ? pnl.halved_events.map((e) => ({ ...e, type: "halved" })) : []),
  ]
    .filter((e) => e && e.date)
    .sort((a, b) => String(a.date).localeCompare(String(b.date)));

  const stats = [
    // M7：无完整交易时 win_rate/win_count/loss_count 为 null → 「—」
    { label: "胜率", value: fmtPct(pnl.win_rate), sub: `${fmtCount(pnl.win_count)} 胜 / ${fmtCount(pnl.loss_count)} 负（按完整交易）` },
    {
      label: "盈亏比",
      value: fmtRatio(pnl.profit_loss_ratio),
      sub: `口径：总盈利/总亏损 = ${fmtCny(pnl.total_profit)} / ${fmtCny(Math.abs(pnl.total_loss))}`,
    },
    {
      label: "单笔最大盈利",
      value: fmtSignedCny(pnl.max_single_profit),
      sub: "完整交易中单笔最高",
      cls: moneyClass(pnl.max_single_profit),
    },
    {
      label: "单笔最大亏损",
      value: fmtSignedCny(pnl.max_single_loss),
      sub: "完整交易中单笔最大回吐",
      cls: moneyClass(pnl.max_single_loss),
    },
    {
      label: "未配对卖出金额",
      value: fmtCny(pnl.unmatched_sell_amount),
      sub: "期初持仓卖出单列，不计入完整交易",
    },
  ];

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="kpi-grid">
        {stats.map((s) => (
          <div key={s.label} className="kpi">
            <div className="kpi-label">{s.label}</div>
            <div className={`kpi-value${s.cls ? ` ${s.cls}` : ""}`}>{s.value}</div>
            {s.sub ? <div className="kpi-sub">{s.sub}</div> : null}
          </div>
        ))}
      </div>

      <div className="grid grid-2">
        <div className="hl-card up">
          <div className="hl-label">账户翻倍次数</div>
          <div className="hl-num">
            {pnl.double_count ?? 0}
            <span className="hl-unit"> 次</span>
          </div>
          <div className="hl-sub">基于收益率曲线：累计收益率达到 +100% 记为一次独立翻倍</div>
        </div>
        <div className="hl-card down">
          <div className="hl-label">账户腰斩次数</div>
          <div className="hl-num">
            {pnl.halved_count ?? 0}
            <span className="hl-unit"> 次</span>
          </div>
          <div className="hl-sub">基于收益率曲线：（1+R）自运行高点回撤 ≥ 50% 记为一次独立腰斩</div>
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">翻倍 / 腰斩事件</h3>
        <p className="card-sub">基于 TWR 收益率曲线逐日模拟的事件明细（日期为触发阈值当日）</p>
        {eventList.length === 0 ? (
          <div className="empty">本期无翻倍 / 腰斩事件</div>
        ) : (
          <div className="event-list">
            {eventList.map((e, i) => (
              <div key={`${e.type}-${e.date}-${i}`} className={`event-item ${e.type}`}>
                <span className={`event-badge ${e.type}`}>{e.type === "double" ? "翻倍" : "腰斩"}</span>
                <span className="event-date">{fmtDate(e.date)}</span>
                <span className={`event-rate ${e.type === "double" ? "pos" : "neg"}`}>
                  {fmtPct(e.return_rate, { signed: true })}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="card-title">盈亏分布</h3>
        <p className="card-sub">按完整交易（已清仓）的单笔盈亏分档统计（500 元步长，超出 ±1 万合并开区间）</p>
        <PnlDistributionChart trades={closed} />
      </div>

      <div className="grid grid-2">
        <RankCard title="个股盈利榜 Top10" note="按总盈亏降序排列" rows={leaderboard.top_profit} negative={false} />
        <RankCard title="个股亏损榜 Top10" note="按总盈亏升序排列（亏损最多在前）" rows={leaderboard.top_loss} negative />
      </div>
    </div>
  );
}
