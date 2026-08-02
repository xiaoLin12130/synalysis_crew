"""Synalysis Crew 后端 API（FastAPI）：上传交割单 → 异步分析任务（带进度） → 历史记录。"""

from __future__ import annotations

import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from synalysis_crew.graph import analyze  # noqa: E402
from synalysis_crew.metrics import compute_metrics  # noqa: E402
from synalysis_crew.parser import ParseError, parse_trades  # noqa: E402
from synalysis_crew.storage import list_analyses, load_analysis, save_analysis  # noqa: E402

app = FastAPI(title="Synalysis Crew API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = ROOT / ".tmp" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}


def _update(job_id: str, **kwargs: Any) -> None:
    with _lock:
        JOBS[job_id].update(kwargs)


def _run_job(job_id: str, path: Path, filename: str) -> None:
    def progress(stage: str, pct: int, message: str) -> None:
        done: Optional[int] = None
        total: Optional[int] = None
        if stage == "analysts":
            mt = re.search(r"(\d+)/(\d+)", message or "")
            if mt:
                done, total = int(mt.group(1)), int(mt.group(2))
        _update(
            job_id,
            stage=stage,
            pct=pct,
            message=message,
            analysts_done=done,
            analysts_total=total,
        )

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
        res = analyze(trades, metrics, progress=progress)
        meta = {
            "filename": filename,
            "source": "upload",
            "total_return_pct": metrics["account"].get("total_return_rate"),
            "is_partial": bool(metrics["meta"].get("is_partial")),
            "label": "区间收益" if metrics["meta"].get("is_partial") else "总收益",
            "tags": (res.get("overall_tags") or [])[:3],
        }
        record_id = save_analysis({**meta, "metrics": metrics, "analysis": res})
        _update(
            job_id,
            status="done",
            pct=100,
            message="分析完成",
            result={"record_id": record_id, "metrics": metrics, "analysis": res},
        )
    except ParseError as exc:
        _update(job_id, status="error", message=str(exc))
    except Exception as exc:  # noqa: BLE001
        _update(job_id, status="error", message=f"分析失败：{exc}")
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
    filename = file.filename or "trades.xlsx"
    suffix = Path(filename).suffix or ".xlsx"
    job_id = uuid.uuid4().hex[:12]
    path = UPLOAD_DIR / f"{job_id}{suffix}"
    path.write_bytes(await file.read())
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
        }
    threading.Thread(
        target=_run_job,
        args=(job_id, path, filename),
        daemon=True,
    ).start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict[str, Any]:
    with _lock:
        job = JOBS.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@app.get("/api/analyses")
def analyses() -> list[dict[str, Any]]:
    return list_analyses()


@app.get("/api/analyses/{record_id}")
def analysis(record_id: str) -> dict[str, Any]:
    record = load_analysis(record_id)
    if not record.get("meta"):
        raise HTTPException(status_code=404, detail="记录不存在")
    return record


DIST = ROOT / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="frontend")
