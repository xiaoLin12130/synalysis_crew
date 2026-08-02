# -*- coding: utf-8 -*-
"""历史分析记录存储（Issue #4 / A4）。

目录结构：data/analyses/{时间戳}/{meta.json, metrics.json, analysis.json}
读写均健壮：文件缺失 / 损坏 / 非法 id 时返回空结构，绝不抛异常。
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_SAFE_ID = re.compile(r"^[0-9A-Za-z._-]+$")


def _analyses_root() -> Path:
    """分析记录根目录；可用环境变量 SYNALYSIS_DATA_DIR 覆盖（测试/隔离用）。"""
    override = os.environ.get("SYNALYSIS_DATA_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[2] / "data" / "analyses"


def _ensure_root() -> Path:
    root = _analyses_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _read_json(path: Path) -> Any:
    try:
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _now_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _unique_dir(root: Path, stamp: str) -> Path:
    candidate = root / stamp
    n = 1
    while candidate.exists():
        n += 1
        candidate = root / f"{stamp}-{n}"
    return candidate


def save_analysis(meta: dict, timestamp: Optional[str] = None) -> str:
    """保存一次分析记录，返回记录 id（时间戳目录名）。

    meta 中可携带 "metrics"/"analysis" 键，会被拆分写入
    metrics.json / analysis.json；meta.json 只保留元信息摘要。
    兼容两种调用形式：save_analysis(meta) 或 save_analysis(meta, timestamp)。
    """
    root = _ensure_root()
    meta = dict(meta or {})
    metrics = meta.pop("metrics", None)
    analysis = meta.pop("analysis", None)
    stamp = timestamp or meta.pop("timestamp", None) or _now_stamp()
    meta.setdefault("timestamp", stamp)
    meta.setdefault("created_at", datetime.now().isoformat(timespec="seconds"))
    entry = _unique_dir(root, str(stamp))
    entry.mkdir(parents=True, exist_ok=True)
    _write_json(entry / "meta.json", meta)
    if metrics is not None:
        _write_json(entry / "metrics.json", metrics)
    if analysis is not None:
        _write_json(entry / "analysis.json", analysis)
    return entry.name


def _safe_id(record_id: Any) -> Optional[str]:
    record_id = str(record_id or "").strip()
    if not record_id or not _SAFE_ID.match(record_id) or record_id in {".", ".."}:
        return None
    return record_id


def list_analyses() -> list:
    """按时间倒序返回历史摘要列表；任何损坏项自动跳过，绝不抛异常。"""
    root = _analyses_root()
    if not root.is_dir():
        return []
    results = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        meta = _read_json(entry / "meta.json")
        if not isinstance(meta, dict) or not meta:
            meta = {"timestamp": entry.name}
        meta = dict(meta)
        meta.setdefault("id", entry.name)
        meta.setdefault("timestamp", entry.name)
        if "file_name" not in meta:
            meta["file_name"] = "(未知文件)"
        results.append(meta)
    results.sort(key=lambda m: str(m.get("timestamp", "")), reverse=True)
    return results


def load_analysis(record_id: Any) -> dict:
    """按 id 读取一条记录：{"id", "meta", "metrics", "analysis"}；缺失返回空 dict。"""
    safe = _safe_id(record_id)
    if safe is None:
        return {}
    entry = _analyses_root() / safe
    if not entry.is_dir():
        return {}
    return {
        "id": safe,
        "meta": _read_json(entry / "meta.json") or {},
        "metrics": _read_json(entry / "metrics.json") or {},
        "analysis": _read_json(entry / "analysis.json") or {},
    }
