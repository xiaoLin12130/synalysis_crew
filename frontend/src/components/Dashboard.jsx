import React, { useState } from "react";
import KpiCards from "./KpiCards";
import { MonthlyPnlChart, ReturnCurveChart } from "./Charts";
import TradeTable from "./TradeTable";
import PnlAnalysis from "./PnlAnalysis";
import BehaviorProfile from "./BehaviorProfile";
import AiReport from "./AiReport";
import { fmtDate, fmtPct } from "../format";

const TABS = [
  { key: "overview", label: "账户总览" },
  { key: "trades", label: "交易明细" },
  { key: "pnl", label: "盈亏分析" },
  { key: "behavior", label: "行为画像" },
  { key: "report", label: "AI 报告" },
];

function Overview({ metrics }) {
  const pnl = metrics.pnl || {};
  return (
    <div className="grid" style={{ gap: 16 }}>
      <KpiCards metrics={metrics} />
      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-title">收益率曲线</h3>
          <p className="card-sub">
            时间加权 TWR（逐日模拟），Y 轴为百分比 · 最大回撤 {fmtPct(pnl.max_drawdown)}
          </p>
          <ReturnCurveChart curve={pnl.return_curve} />
        </div>
        <div className="card">
          <h3 className="card-title">月度盈亏</h3>
          <p className="card-sub">按完整交易平仓月份统计，单位：元</p>
          <MonthlyPnlChart monthly={pnl.monthly_pnl} />
        </div>
      </div>
    </div>
  );
}

export default function Dashboard({ result, onNew }) {
  const [tab, setTab] = useState("overview");
  const metrics = result.metrics || {};
  const meta = result.meta || {};
  const analysis = result.analysis || {};

  return (
    <div>
      <div className="result-head">
        <div>
          <div className="result-head-title">交割单分析报告</div>
          <div className="result-head-sub">
            分析区间：{fmtDate(meta.start_date)} ～ {fmtDate(meta.end_date)}
            {meta.is_partial ? <span className="badge partial">区间分析</span> : <span className="badge closed">完整周期</span>}
            {Array.isArray(meta.tags)
              ? meta.tags.map((t) => (
                  <span key={t} className="tag-chip light">{t}</span>
                ))
              : null}
          </div>
        </div>
        <button className="btn btn-outline btn-sm" onClick={onNew}>＋ 新建分析</button>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={`tab${tab === t.key ? " active" : ""}`} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" ? <Overview metrics={metrics} /> : null}
      {tab === "trades" ? <TradeTable trades={metrics.trades} /> : null}
      {tab === "pnl" ? <PnlAnalysis metrics={metrics} /> : null}
      {tab === "behavior" ? <BehaviorProfile metrics={metrics} /> : null}
      {tab === "report" ? <AiReport analysis={analysis} meta={meta} /> : null}
    </div>
  );
}
