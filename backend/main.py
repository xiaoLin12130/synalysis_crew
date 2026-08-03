"""Synalysis Crew 后端 API（FastAPI）：上传交割单 → 异步分析任务（带进度） → 历史记录。

- POST /api/analyze：multipart 上传，落盘 .tmp/uploads/{uuid}.xlsx，异步任务返回 {job_id}
- GET  /api/jobs/{job_id}：任务状态（queued/running/done/error）+ 分步进度
- GET  /api/analyses、/api/analyses/{id}：历史记录（非法 id → 404）
- DELETE /api/analyses/{id}：删除历史记录（成功 204 无 body；非法/不存在 → 404 中文）
- GET  /api/health；frontend/dist 存在时静态托管前端

任务线程：parse_trades → compute_metrics → analyze(progress 回调) → save_analysis；
所有异常转为 status=error + 中文 message，绝不 500 崩线程；上传临时文件用后即删。
健壮性（B2 建议项）：JOBS 终态任务 TTL 清理（>1h 移除、保留最近 50 条）、上传大小上限
（默认 50MB，超限 413）、扩展名校验（xlsx/xls/csv，其他 400）；job result 携带 meta
（M8：filename/is_partial/start_date/end_date/label/tags，供前端区间徽章）。
契约注释：total_return_pct 始终为**小数比率**（0.5 = 50%），前端负责 ×100 展示。
"""

from __future__ import annotations

import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from synalysis_crew.graph import analyze  # noqa: E402
from synalysis_crew.metrics import compute_metrics  # noqa: E402
from synalysis_crew.parser import ParseError, parse_trades  # noqa: E402
from synalysis_crew.storage import (  # noqa: E402
    delete_analysis,
    list_analyses,
    load_analysis,
    save_analysis,
)

app = FastAPI(title="Synalysis Crew API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = ROOT / ".tmp" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_SUFFIXES = {".xlsx", ".xls", ".csv"}  # 支持的上传格式
MAX_UPLOAD_MB = 50  # 上传大小上限（默认 50MB）
JOB_TTL_SECONDS = 3600  # 终态任务（done/error）超过 1 小时移除
MAX_JOBS = 50  # JOBS 字典保留的终态任务上限（保留最近 N 条）

_lock = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}
# graph.analyze 内部使用模块级进度钩子，多任务并发时会互相覆盖；
# 用本锁串行化 analyze 调用，保证每个 job 的进度回调只写自己的 JOBS 条目。
_ANALYZE_LOCK = threading.Lock()


def _max_upload_bytes() -> int:
    """上传大小上限（字节）；可用 SYNALYSIS_MAX_UPLOAD_MB 覆盖（测试用小限值）。"""
    try:
        mb = int(os.getenv("SYNALYSIS_MAX_UPLOAD_MB", str(MAX_UPLOAD_MB)))
    except (TypeError, ValueError):
        mb = MAX_UPLOAD_MB
    return max(1, mb) * 1024 * 1024


def _prune_jobs(now: Optional[float] = None) -> None:
    """JOBS TTL 清理：终态（done/error）任务超过 JOB_TTL_SECONDS 移除；
    字典超过 MAX_JOBS 时淘汰最旧的终态任务。进行中任务永不主动移除。"""
    if now is None:
        now = time.monotonic()
    with _lock:
        stale = [
            jid
            for jid, job in JOBS.items()
            if job.get("status") in ("done", "error")
            and job.get("_finished") is not None
            and now - job["_finished"] > JOB_TTL_SECONDS
        ]
        for jid in stale:
            JOBS.pop(jid, None)
        terminal = sorted(
            (
                (jid, job.get("_finished", 0.0))
                for jid, job in JOBS.items()
                if job.get("status") in ("done", "error")
            ),
            key=lambda item: item[1],
        )
        for jid, _ in terminal[: max(0, len(JOBS) - MAX_JOBS)]:
            JOBS.pop(jid, None)


def _update(job_id: str, **kwargs: Any) -> None:
    with _lock:
        JOBS[job_id].update(kwargs)


def _progress_cb(job_id: str):
    """构造 analyze() 的进度回调：analysts 阶段解析 n/total，其余阶段保留上次值。"""

    def progress(stage: str, pct: int, message: str) -> None:
        updates: dict[str, Any] = {"stage": stage, "pct": pct, "message": message}
        if stage == "analysts":
            mt = re.search(r"(\d+)/(\d+)", message or "")
            if mt:
                updates["analysts_done"] = int(mt.group(1))
                updates["analysts_total"] = int(mt.group(2))
        _update(job_id, **updates)

    return progress


def _run_job(job_id: str, path: Path, filename: str) -> None:
    try:
        _update(job_id, status="running", stage="parsing", pct=2, message="解析交割单…")
        trades = parse_trades(str(path))
        _update(
            job_id,
            stage="metrics",
            pct=8,
            message=f"指标计算（{len(trades)} 笔成交）…",
        )
        metrics = compute_metrics(trades)
        with _ANALYZE_LOCK:
            res = analyze(trades, metrics, progress=_progress_cb(job_id))
        # M8：meta 从 metrics 提炼，随 job result 返回（前端实时分析后渲染区间徽章）；
        # total_return_pct 保持小数比率（0.5 = 50%），前端负责 ×100。
        meta = {
            "filename": filename,
            "source": "upload",
            "total_return_pct": metrics["account"].get("total_return_rate"),
            "is_partial": bool(metrics["meta"].get("is_partial")),
            "start_date": metrics["meta"].get("start_date"),
            "end_date": metrics["meta"].get("end_date"),
            "label": "区间收益" if metrics["meta"].get("is_partial") else "总收益",
            "tags": (res.get("overall_tags") or [])[:3],
        }
        record_id = save_analysis({**meta, "metrics": metrics, "analysis": res})
        _update(
            job_id,
            status="done",
            pct=100,
            message="分析完成",
            result={
                "record_id": record_id,
                "meta": meta,
                "metrics": metrics,
                "analysis": res,
            },
            _finished=time.monotonic(),
        )
    except ParseError as exc:
        _update(
            job_id,
            status="error",
            message=str(exc),
            error=str(exc),
            _finished=time.monotonic(),
        )
    except Exception as exc:  # noqa: BLE001
        text = f"分析失败：{exc}"
        _update(
            job_id,
            status="error",
            message=text,
            error=text,
            _finished=time.monotonic(),
        )
    finally:
        try:
            path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze")
async def create_job(file: UploadFile = File(...)) -> dict[str, str]:
    filename = (file.filename or "trades.xlsx").strip() or "trades.xlsx"
    job_id = uuid.uuid4().hex[:12]
    try:
        # 扩展名校验：仅允许 xlsx/xls/csv（小写归一），其他格式直接 400 中文提示
        suffix = Path(filename).suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=400,
                detail="上传失败：仅支持 xlsx/xls/csv 格式文件",
            )
        path = UPLOAD_DIR / f"{job_id}{suffix}"
        # 大小上限：一次性读取 limit+1 字节，超限即 413，避免无限读入
        limit = _max_upload_bytes()
        data = await file.read(limit + 1)
        if not data:
            raise HTTPException(status_code=400, detail="上传失败：文件为空")
        if len(data) > limit:
            raise HTTPException(
                status_code=413,
                detail=f"上传失败：文件超过 {limit // (1024 * 1024)}MB 大小限制",
            )
        try:
            path.write_bytes(data)
        except Exception as exc:  # noqa: BLE001
            try:
                path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass
            raise HTTPException(status_code=500, detail=f"上传失败：{exc}") from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"上传失败：{exc}") from exc
    finally:
        await file.close()
    _prune_jobs()
    with _lock:
        JOBS[job_id] = {
            "job_id": job_id,
            "filename": filename,
            "status": "queued",
            "stage": "queued",
            "pct": 0,
            "message": "等待开始",
            "analysts_done": 0,
            "analysts_total": 5,
            "result": None,
            "error": None,
            "_created": time.monotonic(),
        }
    try:
        threading.Thread(
            target=_run_job,
            args=(job_id, path, filename),
            daemon=True,
        ).start()
    except Exception:  # noqa: BLE001
        with _lock:
            JOBS.pop(job_id, None)
        path.unlink(missing_ok=True)
        raise
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    _prune_jobs()
    with _lock:
        job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    # 内部字段（以下划线开头）不对外暴露
    return {key: value for key, value in job.items() if not key.startswith("_")}


@app.get("/api/analyses")
def analyses() -> list[dict[str, Any]]:
    """历史摘要列表，按 API 契约归一化（兼容旧记录缺失字段的情况）。
    契约注释：total_return_pct 为**小数比率**（0.5 = 50%，与
    metrics.account.total_return_rate 一致），前端负责 ×100 展示；
    is_partial/label/tags 供区间徽章与标签渲染。"""
    result: list[dict[str, Any]] = []
    for item in list_analyses():
        if not isinstance(item, dict):
            continue
        record = dict(item)
        is_partial = bool(record.get("is_partial", False))
        normalized = {
            "id": str(record.get("id") or record.get("timestamp") or ""),
            "timestamp": str(record.get("timestamp") or ""),
            "filename": str(record.get("filename") or record.get("file_name") or "(未知文件)"),
            "total_return_pct": record.get("total_return_pct"),
            "is_partial": is_partial,
            "label": record.get("label") or ("区间收益" if is_partial else "总收益"),
            "tags": list(record.get("tags") or record.get("overall_tags") or [])[:3],
        }
        normalized.update({k: v for k, v in record.items() if k not in normalized})
        result.append(normalized)
    return result


@app.get("/api/analyses/{record_id}")
def analysis(record_id: str) -> dict[str, Any]:
    try:
        record = load_analysis(record_id)
    except Exception:  # noqa: BLE001
        record = {}
    if not record.get("meta"):
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


@app.delete("/api/analyses/{record_id}", status_code=204)
def delete_record(record_id: str) -> Response:
    """删除历史分析记录：成功 204（无 body）；非法/不存在 → 404 中文。"""
    if not delete_analysis(record_id):
        raise HTTPException(status_code=404, detail="记录不存在")
    return Response(status_code=204)


DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")
