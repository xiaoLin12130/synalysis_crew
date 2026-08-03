import React from "react";
import { STAGES, stageIndex } from "../stages";

export default function ProgressOverlay({ job, onNew }) {
  const isError = job.status === "error";
  const idx = stageIndex(job.stage);
  const pct = Math.max(0, Math.min(100, Number(job.pct) || 0));

  if (isError) {
    return (
      <div className="card progress-card error-panel">
        <div className="error-icon">⚠️</div>
        <div className="error-title">分析失败</div>
        <div className="error-detail">{job.error || "发生未知错误，请稍后重试"}</div>
        <button className="btn btn-accent" onClick={onNew}>返回上传页</button>
      </div>
    );
  }

  return (
    <div className="card progress-card">
      <div className="progress-head">
        <div className="spinner" />
        <div className="progress-title">正在分析「{job.filename || "交割单"}」</div>
        {job.offline ? <span className="pill offline">离线 mock 模式（DEV 降级）</span> : null}
      </div>
      <p className="card-sub">后端任务每 1 秒自动刷新进度，请勿关闭页面</p>

      <div className="steps">
        {STAGES.map((s, i) => {
          const state = i < idx ? "done" : i === idx ? "current" : "pending";
          const label =
            s.key === "analyze"
              ? `分析师点评${job.analysts_total ? ` ${job.analysts_done || 0}/${job.analysts_total}` : ""}`
              : s.label;
          return (
            <div key={s.key} className={`step ${state}`}>
              <div className="step-dot">{i < idx ? "✓" : i === idx ? String(i + 1) : ""}</div>
              <div className="step-label">{label}</div>
            </div>
          );
        })}
      </div>

      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <div className="progress-pct">{pct}%</div>
      <div className="progress-msg">{job.message || "任务处理中…"}</div>

      <div className="progress-actions">
        <button className="btn btn-ghost btn-sm" onClick={onNew}>返回上传页（任务后台继续）</button>
      </div>
    </div>
  );
}
