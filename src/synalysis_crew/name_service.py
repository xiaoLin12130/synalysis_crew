"""股票名称补充服务（涨乐财富通交割单无证券名称列，按代码自动补名）。

链路：parse_trades -> enrich_names(trades) -> compute_metrics。
覆盖 A 股 + ETF 全市场：
- ``akshare.stock_info_a_code_name()``：A 股代码 + 名称；
- ``akshare.fund_etf_spot_em()``：ETF 代码 + 名称（列名兼容
  ``代码/名称`` 与 ``基金代码/基金简称`` 两种表头）。

缓存 ``data/code_names.json``（gitignored，结构 {updated_at, names{code:name}}，
TTL 7 天）：优先读缓存；过期/缺失才拉取，拉取成功原子写缓存
（临时文件 + rename）；拉取失败/超时回退已有缓存（哪怕过期），
再无缓存返回空 dict —— 所有路径绝不抛异常，保证不阻塞分析链路。
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from pathlib import Path
from typing import Any, Optional, Sequence

__all__ = ["get_code_name_map", "enrich_names"]

ROOT = Path(__file__).resolve().parents[2]
CACHE_FILE = ROOT / "data" / "code_names.json"
CACHE_TTL_SECONDS = 7 * 24 * 3600  # 缓存有效期：7 天

_FETCH_LOCK = threading.Lock()  # 并发任务只拉取一次，避免重复请求


# ---------------------------------------------------------------------------
# 缓存读写
# ---------------------------------------------------------------------------


def _parse_updated_at(value: Any) -> Optional[float]:
    """解析缓存的 updated_at：支持 epoch 数值或 ISO 时间字符串。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            try:
                import datetime as dt

                return dt.datetime.fromisoformat(value).timestamp()
            except ValueError:
                return None
    return None


def _read_cache(path: Path) -> Optional[dict[str, Any]]:
    """读取缓存；文件缺失/损坏/结构非法/名称全空 -> None（视为无缓存）。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(data, dict):
        return None
    raw_names = data.get("names")
    if not isinstance(raw_names, dict):
        return None
    names = {
        str(code).strip(): str(name).strip()
        for code, name in raw_names.items()
        if str(name).strip()
    }
    if not names:
        return None
    return {"updated_at": _parse_updated_at(data.get("updated_at")), "names": names}


def _is_expired(cache: Optional[dict[str, Any]], now: Optional[float] = None) -> bool:
    """缓存过期判定：无 updated_at / 超 TTL 均视为过期。"""
    if cache is None:
        return True
    updated_at = cache.get("updated_at")
    if updated_at is None:
        return True
    if now is None:
        now = time.time()
    return now - updated_at > CACHE_TTL_SECONDS


def _write_cache(path: Path, names: dict[str, str]) -> bool:
    """原子写缓存：先写同目录临时文件再 rename，失败静默（不影响返回结果）。"""
    payload = {"updated_at": time.time(), "names": names}
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, path)
        return True
    except Exception:  # noqa: BLE001
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        return False


# ---------------------------------------------------------------------------
# akshare 拉取
# ---------------------------------------------------------------------------


def _import_akshare() -> Any:
    """延迟导入 akshare（import 较慢，仅拉取时执行；测试可替换）。"""
    import akshare as ak  # type: ignore

    return ak


def _normalize_code(value: Any) -> str:
    """代码归一化：去空白/后缀（如 600519.SH），数字补足 6 位（000630）。"""
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        text = str(int(value))
    else:
        text = str(value).strip()
    if "." in text:
        text = text.split(".", 1)[0].strip()
    if text.isdigit():
        return text.zfill(6)
    return text


def _normalize_name(value: Any) -> str:
    """名称归一化：去空白；NaN/None 等占位 -> 空串。"""
    if value is None:
        return ""
    if isinstance(value, float):
        import math

        if math.isnan(value):
            return ""
    text = str(value).strip()
    if text.lower() in ("", "nan", "none", "null", "-"):
        return ""
    return text


def _extract_names(
    frame: Any,
    code_candidates: tuple[str, ...],
    name_candidates: tuple[str, ...],
) -> dict[str, str]:
    """从 akshare 返回的 DataFrame 中提取 {code: name}；缺列/空表 -> {}。"""
    if frame is None or getattr(frame, "empty", True):
        return {}
    columns = [str(column).strip() for column in frame.columns]
    code_idx = next(
        (i for i, column in enumerate(columns) if column in code_candidates), None
    )
    name_idx = next(
        (i for i, column in enumerate(columns) if column in name_candidates), None
    )
    if code_idx is None or name_idx is None:
        return {}
    names: dict[str, str] = {}
    for _, row in frame.iterrows():
        code = _normalize_code(row.iloc[code_idx])
        name = _normalize_name(row.iloc[name_idx])
        if code and name:
            names[code] = name
    return names


def _fetch_stock_names(ak_module: Any) -> dict[str, str]:
    """A 股全市场代码 + 名称（akshare.stock_info_a_code_name）。"""
    try:
        return _extract_names(
            ak_module.stock_info_a_code_name(),
            code_candidates=("code", "代码", "证券代码", "股票代码"),
            name_candidates=("name", "名称", "证券简称", "股票名称"),
        )
    except Exception:  # noqa: BLE001
        return {}


def _fetch_etf_names(ak_module: Any) -> dict[str, str]:
    """ETF 全市场代码 + 名称（akshare.fund_etf_spot_em）。

    列名兼容两种表头：``代码/名称`` 或 ``基金代码/基金简称``。
    """
    try:
        return _extract_names(
            ak_module.fund_etf_spot_em(),
            code_candidates=("代码", "基金代码"),
            name_candidates=("名称", "基金简称", "简称"),
        )
    except Exception:  # noqa: BLE001
        return {}


def _fetch_with_timeout(timeout: float) -> dict[str, str]:
    """守护线程拉取 A 股 + ETF 名称并合并（同名代码 ETF 优先）。

    超时/异常 -> {}（与"拉取失败"同语义，由调用方回退缓存）。
    参考 metrics.py ``_fetch_latest_prices`` 的超时模式。
    """
    result_queue: "queue.Queue[dict[str, str]]" = queue.Queue(maxsize=1)

    def _worker() -> None:
        try:
            ak_module = _import_akshare()
            merged: dict[str, str] = {}
            merged.update(_fetch_stock_names(ak_module))
            merged.update(_fetch_etf_names(ak_module))
            result_queue.put(merged)
        except Exception:  # noqa: BLE001
            result_queue.put({})

    thread = threading.Thread(
        target=_worker, daemon=True, name="synalysis-name-fetch"
    )
    thread.start()
    try:
        return result_queue.get(timeout=timeout)
    except queue.Empty:
        return {}


# ---------------------------------------------------------------------------
# 对外接口
# ---------------------------------------------------------------------------


def get_code_name_map(timeout: float = 20.0) -> dict[str, str]:
    """返回 {代码: 名称} 映射；任何失败/超时都回退缓存或返回空 dict，绝不抛异常。

    优先读缓存（TTL 7 天）；过期/缺失才拉取 akshare；拉取成功原子写缓存，
    失败回退已有缓存（哪怕过期），再无缓存返回空 dict。
    """
    cached = _read_cache(CACHE_FILE)
    if cached is not None and not _is_expired(cached):
        return dict(cached["names"])
    with _FETCH_LOCK:
        # 锁内复查：并发任务等待期间缓存可能已被其他任务刷新
        cached = _read_cache(CACHE_FILE)
        if cached is not None and not _is_expired(cached):
            return dict(cached["names"])
        names = _fetch_with_timeout(timeout)
        if names:
            _write_cache(CACHE_FILE, names)  # 写失败不影响返回
            return names
        stale = _read_cache(CACHE_FILE)
        if stale is not None:
            return dict(stale["names"])
        return {}


def enrich_names(
    trades: Sequence[Any],
    *,
    name_map: Optional[dict[str, str]] = None,
    timeout: float = 20.0,
) -> int:
    """就地补充 name 为空的 TradeRecord（仅映射命中时填充），返回补充条数。

    - 已有名称的记录一律不动；
    - 未命中映射 / 无代码的记录保持空白；
    - 未显式传入 ``name_map`` 时调用 ``get_code_name_map`` 获取
      （失败返回空映射，本函数不抛异常）。
    """
    if name_map is None:
        name_map = get_code_name_map(timeout=timeout)
    filled = 0
    for trade in trades:
        if trade is None:
            continue
        name = getattr(trade, "name", None)
        code = getattr(trade, "code", None)
        if name and str(name).strip():
            continue  # 已有名称不动
        code = str(code or "").strip()
        if not code:
            continue
        mapped = name_map.get(code)
        if mapped:
            trade.name = mapped
            filled += 1
    return filled
