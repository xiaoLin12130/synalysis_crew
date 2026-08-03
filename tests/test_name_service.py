# -*- coding: utf-8 -*-
"""股票名称补充服务单元测试（N1，全离线，不联网）。

覆盖：
- A 股（code/name）与 ETF（代码/名称、基金代码/基金简称）列提取与合并；
- 缓存读写 / TTL（7 天）：新鲜缓存不拉取、过期缓存重新拉取并刷新；
- 拉取失败回退已有缓存（哪怕过期）、无缓存返回空 dict、损坏缓存自愈；
- 拉取超时与异常 -> 空 dict（守护线程 + timeout 模式）；
- enrich_names：只填空名、不动已有名、未命中保持空白；
- 真实解析链路冒烟：涨乐 CSV -> parse_trades -> enrich_names。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import time
import types
import uuid
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
for _path in (_SRC, _FIXTURES):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pandas as pd  # noqa: E402

from synalysis_crew import parse_trades  # noqa: E402
from synalysis_crew.name_service import (  # noqa: E402
    CACHE_TTL_SECONDS,
    _extract_names,
    _fetch_etf_names,
    _fetch_stock_names,
    _fetch_with_timeout,
    enrich_names,
    get_code_name_map,
)
from synalysis_crew.parser import TradeRecord  # noqa: E402
from synthetic_trades import build_zhangle_csv  # noqa: E402


@pytest.fixture()
def tmp_path():
    """自建临时目录（替代 pytest 内置 tmp_path，兼容本机沙箱 ACL）。"""
    base = Path(tempfile.gettempdir())
    path = base / f"synalysis_names_{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o777)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _fake_ak(stock_frame=None, etf_frame=None) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        stock_info_a_code_name=lambda: stock_frame,
        fund_etf_spot_em=lambda: etf_frame,
    )


# ---------------------------------------------------------------------------
# 列提取（A 股 + ETF 两种表头 / 脏值容错）
# ---------------------------------------------------------------------------


def test_fetch_stock_names_extracts_code_name():
    ak = _fake_ak(
        stock_frame=pd.DataFrame(
            {
                "code": ["000630", "600519", "688001"],
                "name": ["铜陵有色", "贵州茅台", "科创测试"],
            }
        )
    )
    assert _fetch_stock_names(ak) == {
        "000630": "铜陵有色",
        "600519": "贵州茅台",
        "688001": "科创测试",
    }


def test_fetch_etf_names_both_column_schemas():
    # 表头方案一：代码/名称
    ak_a = _fake_ak(
        etf_frame=pd.DataFrame(
            {"代码": ["159559", "512480"], "名称": ["央企红利ETF", "半导体ETF"]}
        )
    )
    # 表头方案二：基金代码/基金简称
    ak_b = _fake_ak(
        etf_frame=pd.DataFrame(
            {"基金代码": ["515220", "560830"], "基金简称": ["煤炭ETF", "双创ETF"]}
        )
    )
    assert _fetch_etf_names(ak_a) == {"159559": "央企红利ETF", "512480": "半导体ETF"}
    assert _fetch_etf_names(ak_b) == {"515220": "煤炭ETF", "560830": "双创ETF"}


def test_extract_names_tolerates_dirty_values_and_skips_empty():
    frame = pd.DataFrame(
        {
            "code": ["000001", 630, 600519.0, "600519.SH", "", None],
            "name": ["平安银行", "铜陵有色", None, "贵州茅台", "  ", float("nan")],
        }
    )
    names = _extract_names(
        frame,
        code_candidates=("code",),
        name_candidates=("name",),
    )
    # 数字/浮点/带后缀代码归一化；空名称/NaN 行跳过
    assert names == {
        "000001": "平安银行",
        "000630": "铜陵有色",
        "600519": "贵州茅台",
    }


def test_extract_names_missing_columns_returns_empty():
    frame = pd.DataFrame({"证券代码": ["000630"], "证券名称": ["铜陵有色"]})
    assert (
        _extract_names(
            frame,
            code_candidates=("code",),
            name_candidates=("name",),
        )
        == {}
    )
    assert _extract_names(None, ("code",), ("name",)) == {}


# ---------------------------------------------------------------------------
# 拉取（合并 + 超时 + 异常）
# ---------------------------------------------------------------------------


def test_fetch_with_timeout_merges_stock_and_etf(monkeypatch):
    ak = _fake_ak()
    monkeypatch.setattr("synalysis_crew.name_service._import_akshare", lambda: ak)
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_stock_names",
        lambda module: {"000630": "铜陵有色", "600519": "贵州茅台"},
    )
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_etf_names",
        lambda module: {"159559": "央企红利ETF", "512480": "半导体ETF"},
    )
    assert _fetch_with_timeout(timeout=5.0) == {
        "000630": "铜陵有色",
        "600519": "贵州茅台",
        "159559": "央企红利ETF",
        "512480": "半导体ETF",
    }


def test_fetch_with_timeout_exception_returns_empty(monkeypatch):
    ak = _fake_ak()
    monkeypatch.setattr("synalysis_crew.name_service._import_akshare", lambda: ak)

    def boom(module):
        raise RuntimeError("akshare 挂了")

    monkeypatch.setattr("synalysis_crew.name_service._fetch_stock_names", boom)
    assert _fetch_with_timeout(timeout=5.0) == {}


def test_fetch_with_timeout_slow_worker_returns_empty(monkeypatch):
    """守护线程 + timeout：超时立即返回空 dict，不抛异常、不阻塞。"""
    ak = _fake_ak()
    monkeypatch.setattr("synalysis_crew.name_service._import_akshare", lambda: ak)

    def slow(module):
        time.sleep(0.5)
        return {}

    monkeypatch.setattr("synalysis_crew.name_service._fetch_stock_names", slow)
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_etf_names", lambda module: {}
    )
    started = time.monotonic()
    assert _fetch_with_timeout(timeout=0.05) == {}
    assert time.monotonic() - started < 0.3  # 远小于 worker 睡眠时长


# ---------------------------------------------------------------------------
# get_code_name_map：缓存 TTL / 回退 / 原子写
# ---------------------------------------------------------------------------


def _patch_cache(monkeypatch, tmp_path, data: dict | None = None) -> Path:
    path = tmp_path / "code_names.json"
    if data is not None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    monkeypatch.setattr("synalysis_crew.name_service.CACHE_FILE", path)
    return path


def test_get_code_name_map_missing_cache_fetches_and_writes(monkeypatch, tmp_path):
    cache_path = _patch_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_with_timeout",
        lambda timeout: {"000630": "铜陵有色", "159559": "央企红利ETF"},
    )

    names = get_code_name_map(timeout=3.0)
    assert names == {"000630": "铜陵有色", "159559": "央企红利ETF"}

    # 缓存已原子写入（临时文件已 rename，无残留）
    assert cache_path.is_file()
    assert not cache_path.with_name(cache_path.name + ".tmp").exists()
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert set(data) == {"updated_at", "names"}
    assert data["names"] == names
    assert isinstance(data["updated_at"], (int, float))


def test_get_code_name_map_fresh_cache_skips_fetch(monkeypatch, tmp_path):
    _patch_cache(
        monkeypatch,
        tmp_path,
        {"updated_at": time.time(), "names": {"000630": "铜陵有色"}},
    )

    def should_not_fetch(timeout):
        raise AssertionError("新鲜缓存不应触发拉取")

    monkeypatch.setattr("synalysis_crew.name_service._fetch_with_timeout", should_not_fetch)
    assert get_code_name_map() == {"000630": "铜陵有色"}


def test_get_code_name_map_expired_cache_refetches_and_refreshes(
    monkeypatch, tmp_path
):
    _patch_cache(
        monkeypatch,
        tmp_path,
        {
            "updated_at": time.time() - CACHE_TTL_SECONDS - 100,
            "names": {"000630": "铜陵有色"},
        },
    )
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_with_timeout",
        lambda timeout: {"000630": "铜陵有色", "159559": "央企红利ETF"},
    )

    names = get_code_name_map()
    assert names == {"000630": "铜陵有色", "159559": "央企红利ETF"}
    # 缓存已刷新为最新时间戳
    data = json.loads(tmp_path.joinpath("code_names.json").read_text(encoding="utf-8"))
    assert time.time() - data["updated_at"] < 60
    assert data["names"] == names


def test_get_code_name_map_fetch_failure_falls_back_to_stale_cache(
    monkeypatch, tmp_path
):
    stale = {
        "updated_at": time.time() - CACHE_TTL_SECONDS - 100,
        "names": {"000630": "铜陵有色", "159559": "旧ETF名称"},
    }
    _patch_cache(monkeypatch, tmp_path, stale)
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_with_timeout", lambda timeout: {}
    )

    assert get_code_name_map() == stale["names"]


def test_get_code_name_map_fetch_failure_no_cache_returns_empty(
    monkeypatch, tmp_path
):
    _patch_cache(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_with_timeout", lambda timeout: {}
    )
    assert get_code_name_map() == {}


def test_get_code_name_map_corrupt_cache_recovers(monkeypatch, tmp_path):
    cache_path = _patch_cache(monkeypatch, tmp_path)
    cache_path.write_text("{这不是合法 JSON", encoding="utf-8")
    monkeypatch.setattr(
        "synalysis_crew.name_service._fetch_with_timeout",
        lambda timeout: {"000630": "铜陵有色"},
    )

    assert get_code_name_map() == {"000630": "铜陵有色"}
    assert json.loads(cache_path.read_text(encoding="utf-8"))["names"] == {
        "000630": "铜陵有色"
    }


# ---------------------------------------------------------------------------
# enrich_names：只填空名、不动已有名
# ---------------------------------------------------------------------------


def test_enrich_names_fills_blank_only_and_keeps_existing():
    trades = [
        TradeRecord(code="000630", name=""),  # 应填充
        TradeRecord(code="600519", name="贵州茅台"),  # 已有名称不动
        TradeRecord(code="159559", name="  "),  # 空白填充
        TradeRecord(code="999999", name=""),  # 未命中保持空白
        TradeRecord(code="", name=""),  # 无代码不动
    ]
    filled = enrich_names(
        trades,
        name_map={
            "000630": "铜陵有色",
            "600519": "茅台新名",  # 不影响已有名称
            "159559": "央企红利ETF",
        },
    )
    assert filled == 2
    assert [t.name for t in trades] == [
        "铜陵有色",
        "贵州茅台",
        "央企红利ETF",
        "",
        "",
    ]


def test_enrich_names_uses_get_code_name_map(monkeypatch):
    calls: list[float] = []

    def fake_map(timeout: float = 20.0) -> dict[str, str]:
        calls.append(timeout)
        return {"000630": "铜陵有色"}

    monkeypatch.setattr(
        "synalysis_crew.name_service.get_code_name_map", fake_map
    )
    trades = [TradeRecord(code="000630", name=""), TradeRecord(code="600519", name="")]
    assert enrich_names(trades, timeout=9.0) == 1
    assert calls == [9.0]
    assert trades[0].name == "铜陵有色"
    assert trades[1].name == ""


def test_enrich_names_after_real_zhangle_parse(tmp_path):
    """真实解析链路：涨乐 CSV -> parse_trades -> enrich_names（全离线）。"""
    csv_path = build_zhangle_csv(tmp_path / "zhangle.csv")
    trades = parse_trades(str(csv_path))
    assert len(trades) > 0
    assert all(t.name == "" for t in trades)  # 涨乐无名称列

    name_map = {t.code: f"名称{t.code}" for t in trades if t.code}
    filled = enrich_names(trades, name_map=name_map)
    coded = [t for t in trades if t.code]
    assert filled == len(coded)
    assert all(t.name == f"名称{t.code}" for t in coded)
