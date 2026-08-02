import React from "react";
import { fmtCny, fmtDate, fmtPct } from "../format";
import { HoldingPeriodChart, MonthlyActivityChart } from "./Charts";

// M5：special_operations 键名中文映射（与后端 Schema 六键一致）
const SPECIAL_LABELS = {
  dividend: "分红",
  reverse_repo: "逆回购",
  interest: "利息",
  bonus: "红股",
  bonus_share: "红股",
  ipo: "打新",
  other: "其他",
};

// M5：style 键名中文映射
const STYLE_LABELS = {
  holding_style: "持仓风格",
  concentration: "集中度",
  risk_style: "风险偏好",
  label: "综合标签",
};

function normalizeStyle(style) {
  if (Array.isArray(style)) return style.filter(Boolean);
  if (typeof style === "string") return style ? [style] : [];
  if (style && typeof style === "object") {
    return Object.entries(style)
      .filter(([, v]) => v)
      .map(([k, v]) => `${STYLE_LABELS[k] || k}：${v}`);
  }
  return [];
}

function normalizeSpecials(ops) {
  if (!ops || typeof ops !== "object") return [];
  return Object.entries(ops)
    .map(([key, v]) => {
      const label = SPECIAL_LABELS[key] || key;
      if (v && typeof v === "object") {
        return {
          key,
          label,
          count: Number(v.count) || 0,
          amount: Number(v.amount) || 0,
          qty: Number(v.qty) || 0, // bonus_share 用 qty（股）
        };
      }
      if (typeof v === "number" || typeof v === "string") {
        return { key, label, count: Number(v) || 0, amount: 0, qty: 0 };
      }
      return null;
    })
    .filter(Boolean)
    .filter((s) => s.count > 0 || s.amount > 0 || s.qty > 0);
}

export default function BehaviorProfile({ metrics }) {
  const behavior = metrics.behavior || {};
  const trading = metrics.trading || {};
  const style = normalizeStyle(behavior.style);
  const specials = normalizeSpecials(behavior.special_operations);
  const favorites = Array.isArray(behavior.favorite_stocks_top10) ? behavior.favorite_stocks_top10 : [];
  const conc = Number(behavior.top5_concentration) || 0;
  const hasConc = Number.isFinite(Number(behavior.top5_concentration));
  const maxFavCount = Math.max(1, ...favorites.map((f) => Number(f.count) || 0));
  const maxPos = behavior.max_position || {};

  return (
    <div className="grid" style={{ gap: 16 }}>
      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-title">持仓周期分布</h3>
          <p className="card-sub">
            按完整交易统计 · 平均持仓 {Number.isFinite(Number(trading.avg_holding_period_days)) ? `${trading.avg_holding_period_days} 天` : "—"} · 涉及{" "}
            {trading.distinct_stock_count || 0} 只个股
          </p>
          <HoldingPeriodChart distribution={behavior.holding_period_distribution} />
        </div>
        <div className="card">
          <h3 className="card-title">月度活跃度</h3>
          <p className="card-sub">按交易发生月份统计（中文月份）</p>
          <MonthlyActivityChart activity={behavior.monthly_activity} />
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-title">风格标签</h3>
          <p className="card-sub">由指标引擎根据持仓周期、集中度与交易频率自动生成</p>
          {style.length ? (
            <div className="style-badges">
              {style.map((t) => (
                <span key={t} className="style-badge">{t}</span>
              ))}
            </div>
          ) : (
            <div className="empty">暂无风格标签</div>
          )}
        </div>
        <div className="card">
          <h3 className="card-title">特殊操作统计</h3>
          <p className="card-sub">独立展示，不计入完整交易与盈亏统计</p>
          {specials.length ? (
            <div className="spec-grid">
              {specials.map((s) => (
                <div key={s.key} className="spec-block">
                  <div className="spec-name">{s.label}</div>
                  <div className="spec-count">{s.count}<span className="spec-unit"> 次</span></div>
                  {s.qty > 0 ? (
                    <div className="spec-amount">{s.qty.toLocaleString("zh-CN", { maximumFractionDigits: 0 })} 股</div>
                  ) : s.amount > 0 ? (
                    <div className="spec-amount">¥{s.amount.toLocaleString("zh-CN", { maximumFractionDigits: 2 })}</div>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="empty">本期未检测到分红 / 逆回购 / 利息等特殊操作</div>
          )}
        </div>
      </div>

      <div className="grid grid-2">
        <div className="card">
          <h3 className="card-title">Top5 集中度</h3>
          <p className="card-sub">前 5 大个股成交金额占总成交金额比例（买卖合计口径）</p>
          <div className="conc-num">{hasConc ? `${(conc * 100).toFixed(1)}%` : "—"}</div>
          <div className="conc-bar">
            <div className="conc-fill" style={{ width: `${Math.min(100, conc * 100)}%` }} />
          </div>
          {maxPos && (maxPos.name || maxPos.code || Number.isFinite(Number(maxPos.ratio)) || maxPos.date) ? (
            <div className="kpi-sub" style={{ marginTop: 8 }}>
              历史单票最大仓位：{maxPos.name || "—"}
              {maxPos.code ? `（${maxPos.code}）` : ""}
              {" · "}
              {fmtPct(maxPos.ratio)}
              {" · "}
              {fmtDate(maxPos.date)}
            </div>
          ) : null}
        </div>
        <div className="card">
          <h3 className="card-title">偏爱个股 Top10</h3>
          <p className="card-sub">按交易次数排序，展示累计成交金额</p>
          {favorites.length === 0 ? (
            <div className="empty">暂无数据</div>
          ) : (
            <div className="rank-list">
              {favorites.map((f, i) => {
                const width = Math.max(4, (Number(f.count) / maxFavCount) * 100);
                return (
                  <div key={`${f.code}-${i}`} className="rank-row">
                    <div className="rank-head">
                      <div>
                        <span className="rank-no">{i + 1}</span> <b>{f.name || "—"}</b>{" "}
                        <span className="cell-sub">{f.code || ""}</span>
                      </div>
                      <div>
                        <span className="cell-sub">{f.count} 次</span>{" "}
                        <span className="rank-val">{fmtCny(f.amount)}</span>
                      </div>
                    </div>
                    <div className="bar-track">
                      <div className="bar-fill" style={{ width: `${width}%` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
