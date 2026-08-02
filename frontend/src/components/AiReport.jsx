import React from "react";
import MarkdownView from "./MarkdownView";

const AVATAR_CLASSES = ["", "v2", "v3", "v4", "v5"];

export default function AiReport({ analysis, meta }) {
  const a = analysis || {};
  // S1：overall_tags → 标签徽章
  const tags = Array.isArray(a.tags) ? a.tags : [];
  const analysts = Array.isArray(a.analysts) ? a.analysts : [];
  const debate = Array.isArray(a.debate) ? a.debate : [];
  const responseCount = debate.reduce((s, r) => s + (Array.isArray(r.responses) ? r.responses.length : 0), 0);

  return (
    <div className="grid" style={{ gap: 16 }}>
      {a.degraded ? (
        <div className="degraded-banner">
          ⚠️ 报告已降级生成：{a.degraded_reason || "部分分析师未返回完整点评，报告内容可能不完整"}
        </div>
      ) : null}

      <div className="card">
        <h3 className="card-title">AI 报告</h3>
        <p className="card-sub">
          由 AI 分析师点评、主持人总结与辩论后自动生成（{meta.start_date || "—"} ～ {meta.end_date || "—"}）
        </p>
        {tags.length ? (
          <div className="tag-badges" style={{ marginBottom: 14 }}>
            {tags.map((t) => (
              <span key={t} className="tag-badge">#{t}</span>
            ))}
          </div>
        ) : null}
        <div className="disclaimer">
          <span>⚠️</span>
          <div>
            <b>免责声明：</b>
            {a.disclaimer || "本报告由 AI 自动生成，仅供学习与娱乐参考，不构成任何投资建议。"}
          </div>
        </div>
        <div style={{ marginTop: 18 }}>
          <MarkdownView text={a.report_markdown} />
        </div>
      </div>

      <div className="card">
        <h3 className="card-title">{analysts.length || 5} 位分析师点评</h3>
        <p className="card-sub">点击卡片展开查看完整点评</p>
        {analysts.length ? (
          <div className="analyst-list">
            {analysts.map((an, i) => (
              <details key={an.id || i} className="analyst">
                <summary>
                  <span className={`avatar ${AVATAR_CLASSES[i % AVATAR_CLASSES.length]}`}>
                    {String(an.name || "分").slice(0, 1)}
                  </span>
                  <span>
                    <span className="a-name">{an.name || `分析师${i + 1}`}</span>
                    <br />
                    <span className="a-role">
                      {an.role || "AI 分析师"}
                      {an.tag ? ` · ${an.tag}` : ""}
                    </span>
                  </span>
                  {Array.isArray(an.tags) && an.tags.length ? (
                    <span className="a-tags">
                      {an.tags.map((t) => (
                        <span key={t} className="tag-chip">{t}</span>
                      ))}
                    </span>
                  ) : null}
                  {an.verdict ? <span className="a-verdict">{an.verdict}</span> : null}
                  {an.score != null ? (
                    <span className="a-score">
                      {an.score}
                      <span style={{ fontSize: 11, color: "var(--text-2)" }}> 分</span>
                    </span>
                  ) : null}
                </summary>
                <div className="analyst-content">
                  <MarkdownView text={an.analysis || "（暂无点评内容）"} />
                  {an.suggestion ? (
                    <div className="a-suggestion">
                      <div className="a-suggestion-title">💡 优化建议</div>
                      <MarkdownView text={an.suggestion} />
                    </div>
                  ) : null}
                </div>
              </details>
            ))}
          </div>
        ) : (
          <div className="empty">后端未返回分析师点评记录</div>
        )}
      </div>

      <div className="debate-block">
        <details>
          <summary>
            🗣️ 辩论过程（{debate.length} 轮 / {responseCount} 条）
            {a.round_count ? ` · 共 ${a.round_count} 轮` : ""}
          </summary>
          <div>
            {debate.length ? (
              debate.map((r, ri) => (
                <div key={ri} className="debate-round">
                  <div className="debate-round-head">
                    第 {r.round || ri + 1} 轮{r.topic ? ` · ${r.topic}` : ""}
                  </div>
                  {(Array.isArray(r.responses) ? r.responses : []).map((resp, i) => (
                    <div key={i} className="debate-item">
                      <span className="debate-speaker">{resp.skill_name || `分析师 ${i + 1}`}</span>
                      <div style={{ marginTop: 4 }}>{resp.response || ""}</div>
                    </div>
                  ))}
                </div>
              ))
            ) : (
              <div className="empty">本期无辩论记录</div>
            )}
          </div>
        </details>
      </div>
    </div>
  );
}
