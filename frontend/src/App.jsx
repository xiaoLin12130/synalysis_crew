import React, { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import { normalizeAnalysis, normalizeMetrics } from "./normalize";
import Sidebar from "./components/Sidebar";
import UploadView from "./components/UploadView";
import ProgressOverlay from "./components/ProgressOverlay";
import Dashboard from "./components/Dashboard";

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, message: error && error.message ? error.message : String(error) };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="error-boundary">
          <div className="error-icon">⚠️</div>
          <div className="error-title">页面出现异常</div>
          <div className="error-detail">{this.state.message || "未知错误，请返回重试"}</div>
          <button
            className="btn btn-accent"
            onClick={() => {
              this.setState({ hasError: false, message: "" });
              if (this.props.onReset) this.props.onReset();
            }}
          >
            返回上传页
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function App() {
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("synalysis.sidebarCollapsed") === "1";
    } catch {
      return false;
    }
  });
  // 视图：upload（上传页） | progress（进度页） | dashboard（结果页）
  const [view, setView] = useState("upload");
  // job 全局保留：切换视图不停止轮询、不丢失运行中任务（需求 1.8）
  const [job, setJob] = useState(null);
  // 后台任务完成后的结果，供侧栏「查看分析结果」一键返回
  const [jobResult, setJobResult] = useState(null);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState({ items: [], loading: true, error: null, offline: false });
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const pollRef = useRef(null);
  const viewRef = useRef(view);

  useEffect(() => {
    viewRef.current = view;
  }, [view]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setHistory((h) => ({ ...h, loading: true, error: null }));
    try {
      const res = await api.listAnalyses();
      const items = Array.isArray(res) ? res : (res && res.items) || [];
      setHistory({ items, loading: false, error: null, offline: !!(res && res.offline) });
    } catch (err) {
      setHistory({ items: [], loading: false, error: err.message || "历史记录加载失败", offline: false });
    }
  }, []);

  useEffect(() => {
    loadHistory();
  }, [loadHistory]);

  useEffect(() => () => stopPolling(), [stopPolling]);

  // 「新建分析」（侧栏唯一入口）：只切换视图，进行中的任务继续轮询不丢失
  const handleNew = useCallback(() => {
    setResult(null);
    setDetailError(null);
    setView("upload");
  }, []);

  const beginPolling = useCallback(
    (jobId, filename, offlineFlag) => {
      setJob((prev) => ({ ...(prev || {}), id: jobId, filename, offline: offlineFlag }));
      stopPolling();
      pollRef.current = setInterval(async () => {
        try {
          const snap = await api.getJob(jobId);
          setJob((prev) => ({ ...(prev || {}), ...snap, offline: offlineFlag }));
          if (snap.status === "done" || snap.status === "error") {
            stopPolling();
            if (snap.status === "done") {
              const r = snap.result || {};
              // M8：job result 无 meta 时回退 metrics.meta（区间徽章/分析区间）
              const metrics = normalizeMetrics(r.metrics);
              const fresh = {
                record_id: r.record_id || jobId,
                filename: snap.filename || filename,
                metrics,
                analysis: normalizeAnalysis(r.analysis),
                meta: r.meta || metrics.meta || {},
                offline: offlineFlag,
              };
              setJobResult(fresh);
              // 停留在进度页则自动进入结果页；其他视图由侧栏指示器一键返回
              if (viewRef.current === "progress") {
                setResult(fresh);
                setView("dashboard");
              }
              loadHistory();
            }
          }
        } catch (err) {
          stopPolling();
          setJob((prev) => ({
            ...(prev || {}),
            status: "error",
            error: err.message || "轮询任务状态失败",
          }));
        }
      }, 1000);
    },
    [stopPolling, loadHistory]
  );

  const handleUpload = useCallback(
    async (file) => {
      setDetailError(null);
      setJobResult(null);
      setJob({
        id: null,
        filename: file.name,
        status: "queued",
        stage: "queued",
        pct: 0,
        message: "正在提交文件…",
        analysts_done: 0,
        analysts_total: 0,
        offline: false,
      });
      setView("progress");
      try {
        const res = await api.analyzeFile(file);
        beginPolling(res.job_id, file.name, !!res.offline);
      } catch (err) {
        setJob((prev) => ({ ...(prev || {}), status: "error", error: err.message || "上传失败" }));
      }
    },
    [beginPolling]
  );

  // 运行中点击历史记录：只切换展示内容，轮询继续（需求 1.8）
  const handleSelectHistory = useCallback(
    async (id) => {
      setDetailError(null);
      setDetailLoading(true);
      try {
        const r = await api.getAnalysis(id);
        // M8：历史记录同样兜底 metrics.meta
        const metrics = normalizeMetrics(r.metrics);
        const meta = r.meta || metrics.meta || {};
        const historyItem = history.items.find((it) => String(it.id) === String(id));
        setResult({
          record_id: id,
          filename: meta.filename || (historyItem && historyItem.filename) || "历史分析",
          metrics,
          analysis: normalizeAnalysis(r.analysis),
          meta,
          offline: false,
        });
        setView("dashboard");
      } catch (err) {
        setDetailError(err.message || "历史分析加载失败");
      } finally {
        setDetailLoading(false);
      }
    },
    [history.items]
  );

  // 删除历史记录：成功后刷新列表；删除当前正在查看的记录回到上传页（需求 1.8）
  const handleDeleteHistory = useCallback(
    async (id) => {
      await api.deleteAnalysis(id);
      await loadHistory();
      if (result && result.record_id != null && String(result.record_id) === String(id)) {
        setResult(null);
        setDetailError(null);
        setView("upload");
      }
    },
    [loadHistory, result]
  );

  // 侧栏指示器：进行中 → 回到进度页；已完成 → 查看结果页
  const handleBackToJob = useCallback(() => {
    if (!job) return;
    if (job.status === "done" && jobResult) {
      setResult(jobResult);
      setJob(null);
      setView("dashboard");
      return;
    }
    setView("progress");
  }, [job, jobResult]);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem("synalysis.sidebarCollapsed", next ? "1" : "0");
      } catch {
        /* 忽略存储异常 */
      }
      return next;
    });
  }, []);

  const jobActive = job && (job.status === "queued" || job.status === "running");
  const title =
    view === "progress" && job
      ? "分析进行中"
      : view === "dashboard" && result
        ? `分析结果${result.filename ? ` · ${result.filename}` : ""}`
        : "上传交割单";

  return (
    <ErrorBoundary onReset={handleNew}>
      <div className="app">
        <Sidebar
          collapsed={collapsed}
          onToggle={toggleCollapsed}
          history={history}
          activeId={result ? result.record_id : null}
          onSelect={handleSelectHistory}
          onNew={handleNew}
          job={job}
          onBackToJob={handleBackToJob}
          onDelete={handleDeleteHistory}
        />
        <main className="main">
          <header className="topbar">
            <div className="topbar-title">
              {title}
              {view === "dashboard" && result && result.meta && result.meta.is_partial ? (
                <span className="badge partial topbar-badge">区间分析</span>
              ) : null}
              {view === "dashboard" && result && result.offline ? (
                <span className="pill offline topbar-badge">离线 mock</span>
              ) : null}
            </div>
          </header>
          <div className="content">
            {detailLoading ? (
              <div className="card loading-card">
                <div className="spinner" />
                <div>正在加载历史分析…</div>
              </div>
            ) : detailError ? (
              <div className="card error-panel">
                <div className="error-icon">⚠️</div>
                <div className="error-title">加载失败</div>
                <div className="error-detail">{detailError}</div>
                <div className="error-actions">
                  <button className="btn btn-outline" onClick={() => loadHistory()}>刷新历史记录</button>
                  <button className="btn btn-accent" onClick={handleNew}>返回上传页</button>
                </div>
              </div>
            ) : view === "progress" && job ? (
              <ProgressOverlay job={job} onNew={handleNew} />
            ) : view === "dashboard" && result ? (
              <Dashboard result={result} />
            ) : (
              <UploadView onUpload={handleUpload} busy={!!jobActive} />
            )}
          </div>
        </main>
      </div>
    </ErrorBoundary>
  );
}
