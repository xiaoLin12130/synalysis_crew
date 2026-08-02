import React from "react";

const STAGES = [
  { key: "parse", label: "解析交割单" },
  { key: "metrics", label: "指标计算" },
  { key: "analyze", label: "分析师点评" },
  { key: "moderator", label: "主持人" },
  { key: "debate", label: "辩论" },
  { key: "report", label: "生成报告" },
  { key: "done", label: "完成" },
];

function stageIndex(stage) {
  const s = String(stage || "").toLowerCase();
  // M1：后端 stage 枚举：parsing / metrics / profile / analysts / host / debate / report / done
  if (s.includes("pars") || s.includes("解析")) return 0; // parsing / parse_trades
  if (s.includes("metric") || s.includes("compute") || s.includes("指标")) return 1;
  if (s.includes("profile") || s.includes("analysts") || s.includes("点评")) return 2; // 必须匹配 analysts，不能用 analyz
  if (s.includes("host") || s.includes("moderator") || s.includes("主持")) return 3;
  if (s.includes("debat") || s.includes("辩论")) return 4;
  if (s.includes("report") || s.includes("生成")) return 5;
  if (s.includes("done") || s.includes("完成")) return 6;
  return 0;
}

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
        {job.offline ? <span className="pill offline">离线演示模式</span> : null}
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
        <button className="btn btn-ghost btn-sm" onClick={onNew}>取消并返回</button>
      </div>
    </div>
  );
}
