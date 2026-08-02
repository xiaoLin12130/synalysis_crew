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
  const [view, setView] = useState("upload");
  const [job, setJob] = useState(null);
  const [result, setResult] = useState(null);
  const [history, setHistory] = useState({ items: [], loading: true, error: null, offline: false });
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState(null);
  const pollRef = useRef(null);

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

  const handleNew = useCallback(() => {
    stopPolling();
    setJob(null);
    setResult(null);
    setDetailError(null);
    setView("upload");
  }, [stopPolling]);

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
              setResult({
                record_id: r.record_id || jobId,
                filename: snap.filename || filename,
                metrics,
                analysis: normalizeAnalysis(r.analysis),
                meta: r.meta || metrics.meta || {},
                offline: offlineFlag,
              });
              setView("dashboard");
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
      try {
        const res = await api.analyzeFile(file);
        beginPolling(res.job_id, file.name, !!res.offline);
      } catch (err) {
        setJob((prev) => ({ ...(prev || {}), status: "error", error: err.message || "上传失败" }));
      }
    },
    [beginPolling]
  );

  const handleDemo = useCallback(() => {
    setDetailError(null);
    setJob({
      id: null,
      filename: "离线演示.xlsx",
      status: "queued",
      stage: "queued",
      pct: 0,
      message: "正在启动离线演示…",
      analysts_done: 0,
      analysts_total: 0,
      offline: true,
    });
    const res = api.startOfflineJob("离线演示.xlsx");
    beginPolling(res.job_id, "离线演示.xlsx", true);
  }, [beginPolling]);

  const handleSelectHistory = useCallback(
    async (id) => {
      stopPolling();
      setJob(null);
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
    [stopPolling, history.items]
  );

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

  const jobRunning = job && (job.status === "queued" || job.status === "running");
  const jobError = job && job.status === "error";
  const showUpload = !jobRunning && !jobError && (view === "upload" || !result);
  const title = showUpload
    ? "上传交割单"
    : result
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
        />
        <main className="main">
          <header className="topbar">
            <div className="topbar-title">
              {title}
              {result && result.meta && result.meta.is_partial ? <span className="badge partial topbar-badge">区间分析</span> : null}
              {result && result.offline ? <span className="pill offline topbar-badge">离线演示</span> : null}
            </div>
            <button className="btn btn-outline btn-sm" onClick={handleNew}>＋ 新建分析</button>
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
            ) : jobRunning || jobError ? (
              <ProgressOverlay job={job} onNew={handleNew} />
            ) : showUpload ? (
              <UploadView onUpload={handleUpload} onDemo={handleDemo} busy={!!job} />
            ) : result ? (
              <Dashboard result={result} onNew={handleNew} />
            ) : null}
          </div>
        </main>
      </div>
    </ErrorBoundary>
  );
}
