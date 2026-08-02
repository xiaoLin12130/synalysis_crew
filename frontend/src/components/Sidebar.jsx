import React from "react";
import { fmtDateTime } from "../format";

export default function Sidebar({ collapsed, onToggle, history, activeId, onSelect, onNew }) {
  const items = history.items || [];
  return (
    <aside className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="brand">
        <div className="brand-mark" title={collapsed ? "展开侧栏" : "Synalysis"} onClick={collapsed ? onToggle : undefined}>
          S
        </div>
        <div className="brand-text">
          <div className="brand-title">Synalysis</div>
          <div className="brand-sub">交割单智能分析 v2</div>
        </div>
      </div>
      <button className="btn btn-accent new-btn" onClick={onNew} title="新建分析">
        <span className="new-icon">＋</span>
        <span className="new-text">新建分析</span>
      </button>
      <div className="history">
        <div className="history-title">历史分析</div>
        {history.loading ? (
          <div className="sidebar-empty">正在加载历史记录…</div>
        ) : history.offline ? (
          <div className="sidebar-empty">后端未连接，历史记录暂不可用（离线预览）</div>
        ) : history.error ? (
          <div className="sidebar-empty">{history.error}</div>
        ) : items.length === 0 ? (
          <div className="sidebar-empty">
            暂无历史分析记录
            <br />
            完成一次分析后会自动保存在这里
          </div>
        ) : (
          items.map((it) => {
            // S3：API 契约比率一律小数，展示必须 ×100 加 %；null 显示 —
            const raw = Number(it.total_return_pct);
            const hasRet = Number.isFinite(raw);
            const ret = hasRet ? raw * 100 : null;
            const retText = !hasRet
              ? "—"
              : `${it.is_partial ? "区间 " : ""}${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`;
            return (
              <button
                key={String(it.id)}
                className={`history-item${String(activeId) === String(it.id) ? " active" : ""}`}
                onClick={() => onSelect(it.id)}
              >
                <div className="hist-time">{fmtDateTime(it.timestamp)}</div>
                <div className="hist-name" title={it.filename}>{it.filename || "未命名分析"}</div>
                <div className="hist-return">
                  <span className={ret == null ? "" : ret >= 0 ? "pos" : "neg"}>{retText}</span>
                  {it.label ? <span className="tag-chip">{it.label}</span> : null}
                </div>
                {it.tags && it.tags.length ? (
                  <div className="hist-tags">
                    {it.tags.slice(0, 3).map((t) => (
                      <span key={t} className="tag-chip">{t}</span>
                    ))}
                  </div>
                ) : null}
              </button>
            );
          })
        )}
      </div>
      <div className="sidebar-footer">
        <button className="collapse-btn" onClick={onToggle} title={collapsed ? "展开侧栏" : "收起侧栏"}>
          <span className="collapse-icon">{collapsed ? "☰" : "◀"}</span>
          <span className="collapse-text">{collapsed ? "展开" : "收起侧栏"}</span>
        </button>
      </div>
    </aside>
  );
}
