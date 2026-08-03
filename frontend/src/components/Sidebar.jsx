import React, { useState } from "react";
import { fmtDateTime } from "../format";
import { stageLabel } from "../stages";

export default function Sidebar({ collapsed, onToggle, history, activeId, onSelect, onNew, job, onBackToJob, onDelete }) {
  const [confirmingId, setConfirmingId] = useState(null);
  const [deletingId, setDeletingId] = useState(null);
  const [deleteError, setDeleteError] = useState("");
  const items = history.items || [];

  const askDelete = (e, id) => {
    e.stopPropagation();
    setDeleteError("");
    setConfirmingId(String(id));
  };

  const cancelDelete = (e) => {
    e.stopPropagation();
    setConfirmingId(null);
    setDeleteError("");
  };

  const confirmDelete = async (e, it) => {
    e.stopPropagation();
    const id = String(it.id);
    setDeleteError("");
    setDeletingId(id);
    try {
      await onDelete(it.id);
      setConfirmingId(null);
    } catch (err) {
      setConfirmingId(null);
      setDeleteError((err && err.message) || "删除失败，请稍后重试");
    } finally {
      setDeletingId(null);
    }
  };

  const jobState = job ? job.status : null;
  const jobPct = job && Number.isFinite(Number(job.pct)) ? Math.round(Number(job.pct)) : 0;

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
      {/* 新建分析：收敛为侧栏唯一主按钮 */}
      <button className="btn btn-accent new-btn" onClick={onNew} title="新建分析">
        <span className="new-icon">＋</span>
        <span className="new-text">新建分析</span>
      </button>

      {/* 运行中任务指示器：任何视图下任务不丢失，可一键回到分析 / 查看结果 */}
      {jobState === "queued" || jobState === "running" ? (
        <div className="job-indicator running">
          <div className="ji-title">
            <span className="ji-spinner" />
            分析进行中 {jobPct}%
          </div>
          <div className="ji-stage">· {stageLabel(job.stage)}</div>
          <button className="btn btn-accent btn-sm ji-btn" onClick={onBackToJob}>回到分析</button>
        </div>
      ) : jobState === "done" ? (
        <div className="job-indicator done">
          <div className="ji-title">✓ 分析已完成</div>
          <button className="btn btn-accent btn-sm ji-btn" onClick={onBackToJob}>查看分析结果</button>
        </div>
      ) : jobState === "error" ? (
        <div className="job-indicator error">
          <div className="ji-title">⚠ 分析失败</div>
          <button className="btn btn-outline btn-sm ji-btn" onClick={onBackToJob}>查看失败原因</button>
        </div>
      ) : null}

      <div className="history">
        <div className="history-title">历史分析</div>
        {deleteError ? <div className="sidebar-del-error">{deleteError}</div> : null}
        {history.loading ? (
          <div className="sidebar-empty">正在加载历史记录…</div>
        ) : history.error ? (
          <div className="sidebar-empty">{history.error}</div>
        ) : items.length === 0 ? (
          history.offline ? (
            <div className="sidebar-empty">后端未连接，历史记录暂不可用（离线预览）</div>
          ) : (
            <div className="sidebar-empty">
              暂无历史分析记录
              <br />
              完成一次分析后会自动保存在这里
            </div>
          )
        ) : (
          items.map((it) => {
            // S3：API 契约比率一律小数，展示必须 ×100 加 %；null 显示 —
            const raw = Number(it.total_return_pct);
            const hasRet = Number.isFinite(raw);
            const ret = hasRet ? raw * 100 : null;
            const retText = !hasRet
              ? "—"
              : `${it.is_partial ? "区间 " : ""}${ret >= 0 ? "+" : ""}${ret.toFixed(2)}%`;
            const isActive = String(activeId) === String(it.id);
            return (
              <div
                key={String(it.id)}
                role="button"
                tabIndex={0}
                className={`history-item${isActive ? " active" : ""}${confirmingId === String(it.id) ? " confirming" : ""}`}
                onClick={() => onSelect(it.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(it.id);
                  }
                }}
              >
                <div className="hist-top">
                  <span className="hist-time">{fmtDateTime(it.timestamp)}</span>
                  {confirmingId === String(it.id) ? null : (
                    <button
                      className="hist-del"
                      title="删除该记录"
                      disabled={deletingId !== null}
                      onClick={(e) => askDelete(e, it.id)}
                    >
                      <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                        <path d="M3 6h18" />
                        <path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2" />
                        <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      </svg>
                    </button>
                  )}
                </div>
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
                {confirmingId === String(it.id) ? (
                  <div className="hist-confirm">
                    <span className="hist-confirm-text">确认删除「{it.filename || "该记录"}」？</span>
                    <button
                      className="btn btn-danger btn-xs"
                      disabled={deletingId !== null}
                      onClick={(e) => confirmDelete(e, it)}
                    >
                      {deletingId === String(it.id) ? "删除中…" : "确认删除"}
                    </button>
                    <button className="btn btn-ghost btn-xs" disabled={deletingId !== null} onClick={cancelDelete}>
                      取消
                    </button>
                  </div>
                ) : null}
              </div>
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
