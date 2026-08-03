# -*- coding: utf-8 -*-
"""后端 FastAPI 集成测试（B2 / S4 + M8 + 建议项）。

覆盖：
- GET /api/health → 200
- POST /api/analyze 上传合成 xlsx → {job_id} → 轮询 /api/jobs/{id} 至 done
  （无 Key 走规则引擎降级，最终 status=done、pct=100，result 含
  record_id/metrics/analysis/meta（M8））→ GET /api/analyses 含该记录
  → GET /api/analyses/{id} 返回 meta/metrics/analysis
- 错误路径：空文件 400、坏文件 job status=error 且 message 中文、非法 job 404、
  非法 record 404
- 建议项：扩展名校验 400、上传大小上限 413、JOBS 终态任务 TTL 清理

隔离策略：
- SYNALYSIS_DATA_DIR 指向 .tmp/ 下临时目录，绝不写仓库 data/analyses
- 与 tests/test_e2e.py 同模式：导入 backend.main（→ graph → llm）前置空
  DEEPSEEK_API_KEY，保证无 Key 规则引擎降级；并禁用行情拉取，离线确定性。
"""

from __future__ import annotations

import os
import shutil
import sys
import time
import uuid
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
_BACKEND = _PROJECT_ROOT / "backend"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ── 无 Key 降级路径：必须在导入 synalysis_crew / backend.main 之前置空 ──
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ.pop("OPENAI_API_KEY", None)

for _path in (_PROJECT_ROOT, _SRC, _BACKEND, _FIXTURES):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import synalysis_crew.metrics as metrics_module  # noqa: E402
import synalysis_crew.storage as storage_module  # noqa: E402

import backend.main as main  # noqa: E402
from synthetic_trades import build_xlsx  # noqa: E402


def _has_cjk(text: str) -> bool:
    """是否包含中文字符（错误信息中文断言）。"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in str(text))


def _poll_job(client, job_id: str, timeout: float = 120.0) -> dict:
    """轮询任务直到终态（done/error），上限 ~120s；超时抛断言。"""
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        resp = client.get(f"/api/jobs/{job_id}")
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last["status"] in ("done", "error"):
            return last
        time.sleep(0.5)
    raise AssertionError(f"轮询超时（>{timeout:.0f}s），最后状态：{last}")


@pytest.fixture()
def iso_dir():
    """.tmp/ 下隔离目录（0o777 显式创建，兼容本机沙箱 ACL），测试结束清理。"""
    base = _PROJECT_ROOT / ".tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"test_backend_{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o777)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def client(iso_dir, monkeypatch):
    """TestClient + 存储隔离：SYNALYSIS_DATA_DIR → .tmp/ 临时目录。"""
    monkeypatch.setenv("SYNALYSIS_DATA_DIR", str(iso_dir / "analyses"))
    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def no_price_fetch(monkeypatch):
    """禁用行情拉取：指标按成本兜底（market_value_source=cost），离线确定性。"""
    monkeypatch.setattr(
        metrics_module,
        "_fetch_latest_prices",
        lambda codes, timeout=15.0: None,
    )


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# S4 主链路：上传 → 轮询 → done → 历史 → 详情（含 M8 meta）
# ---------------------------------------------------------------------------


def test_upload_poll_done_history_detail(client, iso_dir, no_price_fetch):
    xlsx = build_xlsx(iso_dir / "synthetic.xlsx")
    resp = client.post(
        "/api/analyze",
        files={
            "file": (
                "synthetic.xlsx",
                xlsx.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert resp.status_code == 200, resp.text
    assert set(resp.json()) == {"job_id"}  # POST /api/analyze 契约：仅返回 {job_id}
    job_id = resp.json()["job_id"]
    assert job_id

    job = _poll_job(client, job_id)
    assert job["status"] == "done"
    assert job["pct"] == 100
    # 契约字段齐全，且内部字段（_created/_finished）不外泄
    for key in (
        "job_id",
        "filename",
        "status",
        "stage",
        "pct",
        "message",
        "analysts_done",
        "analysts_total",
        "result",
        "error",
    ):
        assert key in job, f"job 响应缺少契约字段 {key}"
    assert not any(key.startswith("_") for key in job)

    result = job["result"]
    assert result is not None
    record_id = result["record_id"]
    assert record_id
    for key in ("record_id", "metrics", "analysis", "meta"):
        assert key in result, f"result 缺少 {key}"

    # M8：result.meta 提供前端区间徽章所需字段
    meta = result["meta"]
    assert meta["filename"] == "synthetic.xlsx"
    assert meta["is_partial"] is True  # 合成夹具为「中途开始」场景
    assert meta["start_date"] == "2025-11-27"
    assert meta["end_date"] == "2026-01-13"
    assert meta["label"]
    assert isinstance(meta["tags"], list)
    # 契约：total_return_pct 保持小数比率（0.5 = 50%），前端负责 ×100
    trr = result["metrics"]["account"]["total_return_rate"]
    assert meta["total_return_pct"] == trr
    assert isinstance(trr, (int, float)) and abs(trr) < 10
    # 无 Key 时规则引擎降级
    assert result["analysis"]["degraded"] is True
    assert result["analysis"]["final_report"]

    # 历史列表包含该记录
    resp = client.get("/api/analyses")
    assert resp.status_code == 200
    records = resp.json()
    record = next((r for r in records if r.get("id") == record_id), None)
    assert record is not None, "历史列表未包含新分析记录"
    assert record["filename"] == "synthetic.xlsx"
    assert record["is_partial"] is True
    assert record["label"]
    assert isinstance(record["tags"], list)
    assert record["total_return_pct"] == trr  # 仍为小数，未被 ×100

    # 详情接口
    resp = client.get(f"/api/analyses/{record_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert {"meta", "metrics", "analysis"}.issubset(detail.keys())
    assert detail["meta"]["filename"] == "synthetic.xlsx"
    assert detail["meta"]["start_date"] == "2025-11-27"
    assert detail["metrics"]["meta"]["is_partial"] is True
    assert detail["analysis"]["final_report"]

    # 上传临时文件已清理
    uploads = _PROJECT_ROOT / ".tmp" / "uploads"
    assert not list(uploads.glob(f"{job_id}*"))


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


def test_empty_file_400(client):
    resp = client.post(
        "/api/analyze",
        files={"file": ("empty.xlsx", b"", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "文件为空" in resp.json()["detail"]


def test_bad_file_job_error_chinese(client):
    resp = client.post(
        "/api/analyze",
        files={"file": ("bad.xlsx", b"this is not a real xlsx file", "application/octet-stream")},
    )
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    job = _poll_job(client, job_id)
    assert job["status"] == "error"
    text = f"{job.get('message') or ''}{job.get('error') or ''}"
    assert text
    assert _has_cjk(text), f"错误信息应含中文，实际：{text!r}"
    assert "无法解析" in text


def test_invalid_job_404(client):
    resp = client.get("/api/jobs/does-not-exist")
    assert resp.status_code == 404
    assert "任务不存在" in resp.json()["detail"]


def test_invalid_record_404(client):
    for bad_id in ("does-not-exist", "..%5Cevil"):
        resp = client.get(f"/api/analyses/{bad_id}")
        assert resp.status_code == 404, bad_id
        assert "记录不存在" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# v2.2 历史记录删除：DELETE /api/analyses/{id}（H2）
# ---------------------------------------------------------------------------


def _save_delete_fixture(stamp: str) -> str:
    """在隔离目录直接落一条含 meta/metrics/analysis 的记录，返回 record id。"""
    return storage_module.save_analysis(
        {
            "filename": "delete-me.xlsx",
            "total_return_pct": 0.25,
            "is_partial": False,
            "label": "总收益",
            "tags": ["删除测试"],
            "metrics": {"meta": {"is_partial": False}},
            "analysis": {"final_report": "# 删除测试", "degraded": True},
        },
        timestamp=stamp,
    )


def test_delete_analysis_204_list_and_dir_gone(client, iso_dir):
    record_id = _save_delete_fixture("20990101-000000")
    entry = iso_dir / "analyses" / record_id
    for name in ("meta.json", "metrics.json", "analysis.json"):
        assert (entry / name).is_file(), name

    # 删除前：历史列表包含该记录
    assert record_id in {r["id"] for r in client.get("/api/analyses").json()}

    resp = client.delete(f"/api/analyses/{record_id}")
    assert resp.status_code == 204
    assert resp.content == b""  # 成功无 body

    # meta/metrics/analysis 所在目录一并删除
    assert not entry.exists()
    # 删除后：历史列表不再包含
    assert record_id not in {r["id"] for r in client.get("/api/analyses").json()}


def test_delete_analysis_again_404(client, iso_dir):
    record_id = _save_delete_fixture("20990101-000001")
    assert client.delete(f"/api/analyses/{record_id}").status_code == 204

    resp = client.delete(f"/api/analyses/{record_id}")
    assert resp.status_code == 404
    assert "记录不存在" in resp.json()["detail"]


def test_delete_analysis_invalid_id_404(client):
    for bad_id in ("does-not-exist", "..%5Cevil", "bad%20id", "bad;id"):
        resp = client.delete(f"/api/analyses/{bad_id}")
        assert resp.status_code == 404, bad_id
        assert "记录不存在" in resp.json()["detail"]


def test_delete_analysis_isolated_from_repo_data(client, iso_dir):
    """SYNALYSIS_DATA_DIR 隔离：删除只作用于隔离目录，不碰仓库 data/analyses。"""
    repo_root = _PROJECT_ROOT / "data" / "analyses"
    before = sorted(p.name for p in repo_root.iterdir()) if repo_root.is_dir() else []

    record_id = _save_delete_fixture("20990101-000002")
    assert (iso_dir / "analyses" / record_id).is_dir()
    assert record_id not in before  # 隔离目录中的记录本就不在仓库里

    assert client.delete(f"/api/analyses/{record_id}").status_code == 204
    assert not (iso_dir / "analyses" / record_id).exists()

    after = sorted(p.name for p in repo_root.iterdir()) if repo_root.is_dir() else []
    assert after == before


# ---------------------------------------------------------------------------
# 建议项：扩展名校验 / 上传大小上限
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["evil.txt", "trades.pdf", "noext"])
def test_extension_rejected_400(client, name):
    resp = client.post(
        "/api/analyze",
        files={"file": (name, b"whatever", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "仅支持 xlsx/xls/csv" in resp.json()["detail"]


def test_oversize_413(client, monkeypatch):
    # 用环境变量把上限调小（默认 50MB），避免测试构造 50MB+ 大文件
    monkeypatch.setenv("SYNALYSIS_MAX_UPLOAD_MB", "1")
    resp = client.post(
        "/api/analyze",
        files={"file": ("big.xlsx", b"x" * (1024 * 1024 + 1), "application/octet-stream")},
    )
    assert resp.status_code == 413
    assert "大小限制" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# 建议项：JOBS TTL 清理（终态 >1h 移除；保留最近 50 条；运行中任务不删）
# ---------------------------------------------------------------------------


def test_jobs_ttl_prunes_stale_terminal_only(monkeypatch):
    now = time.monotonic()
    for i in range(3):
        main.JOBS[f"ttl_stale_{i}"] = {"status": "done", "_finished": now - 7200.0}
    main.JOBS["ttl_running_old"] = {"status": "running", "_finished": now - 7200.0}
    main.JOBS["ttl_fresh"] = {"status": "done", "_finished": now - 60.0}
    try:
        main._prune_jobs(now=now)
        assert all(f"ttl_stale_{i}" not in main.JOBS for i in range(3))
        assert "ttl_running_old" in main.JOBS  # 进行中任务永不主动移除
        assert "ttl_fresh" in main.JOBS  # 1 小时内终态任务保留
    finally:
        for jid in [j for j in main.JOBS if j.startswith("ttl_")]:
            main.JOBS.pop(jid, None)


def test_jobs_cap_keeps_50_terminal(monkeypatch):
    now = time.monotonic()
    # 统计插入前已存在的终态任务（前面用例残留，容量淘汰时它们更新、优先保留）
    preexisting = [
        jid
        for jid, job in main.JOBS.items()
        if job.get("status") in ("done", "error") and job.get("_finished") is not None
    ]
    for i in range(60):
        main.JOBS[f"cap_{i:03d}"] = {"status": "done", "_finished": now - 60.0 + i}
    try:
        main._prune_jobs(now=now)
        remaining = sorted(jid for jid in main.JOBS if jid.startswith("cap_"))
        excess = max(0, len(preexisting) + 60 - main.MAX_JOBS)
        assert len(remaining) == 60 - excess  # 总量收敛到 MAX_JOBS
        assert remaining[0] == f"cap_{excess:03d}"  # 最旧的 cap_ 条目被淘汰
        assert "cap_059" in main.JOBS  # 最近任务保留
        for jid in preexisting:  # 更早完成的任务比 cap_ 更新，优先保留
            assert jid in main.JOBS
    finally:
        for jid in [j for j in main.JOBS if j.startswith("cap_")]:
            main.JOBS.pop(jid, None)
