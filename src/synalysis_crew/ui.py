# -*- coding: utf-8 -*-
"""Synalysis 前端 UI（Issue #4 / A4）。

Streamlit + Plotly，中文界面，Codex 桌面风格（深色侧栏 / 浅色内容区 /
细边框 / 圆角 / 单一强调色）。

开发期只依赖契约：parse_trades / compute_metrics / analyze / storage。
本模块内置完整 mock MetricsResult / AnalysisResult；上游模块未就绪时
自动降级为 mock 展示，并给出中文提示，AI 失败不阻塞指标展示。
"""

from __future__ import annotations

import html
import os
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ACCENT = "#10A37F"
POS_COLOR = "#E5484D"  # A股习惯：红涨
NEG_COLOR = "#30A46C"  # 绿跌
TEXT_MAIN = "#23262C"

DISCLAIMER = "仅供参考，不构成投资建议。市场有风险，投资需谨慎。"

_OP_LABELS = {
    "证券买入": "买入",
    "证券卖出": "卖出",
    "BUY": "买入",
    "SELL": "卖出",
    "TRANSFER_IN": "转入资金",
    "TRANSFER_OUT": "转出资金",
    "REVERSE_REPO": "逆回购",
    "DIVIDEND": "红利",
    "BONUS_SHARE": "红股",
    "INTEREST": "利息",
    "DIVIDEND_TAX": "股息补差",
    "IPO": "打新",
    "OTHER": "其他",
    "DESIGNATED": "指定交易",
    "银行转证券": "转入资金",
    "证券转银行": "转出资金",
    "通用回购逆回": "逆回购",
    "利息归本": "利息",
    "红利入账": "红利",
    "红股入账": "红股",
    "股息红利差异": "股息补差",
    "指定交易": "指定交易",
}

_CSS = """
:root { --accent: __ACCENT__; }
html, body, [data-testid="stAppViewContainer"] {
  font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
}
[data-testid="stAppViewContainer"] { background: #F7F7F5; }
#MainMenu, footer { visibility: hidden; height: 0; }
[data-testid="stHeader"] { visibility: hidden; height: 0; background: transparent; }
.block-container { padding-top: 2.1rem; padding-bottom: 3rem; max-width: 1180px; }
/* ---------- 深色侧栏（Codex 桌面风格） ---------- */
[data-testid="stSidebar"] {
  background: #17181D;
  border-right: 1px solid #26282F;
}
[data-testid="stSidebar"] .block-container { padding-top: 1.15rem; }
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] label, [data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4, [data-testid="stSidebar"] h5,
[data-testid="stSidebar"] h6, [data-testid="stSidebar"] .stMarkdown {
  color: #D9DBE0;
}
[data-testid="stSidebar"] hr { border-color: #2A2D35; }
[data-testid="stFileUploaderDropzone"] {
  background: #1F2128;
  border: 1px dashed #3A3E47;
  border-radius: 12px;
}
[data-testid="stSidebar"] .stButton > button {
  background: #1F2128;
  border: 1px solid #34373F;
  color: #D9DBE0;
  border-radius: 10px;
  text-align: left;
}
[data-testid="stSidebar"] .stButton > button:hover {
  border-color: var(--accent);
  color: #FFFFFF;
}
/* ---------- 主区按钮 / 组件 ---------- */
.stButton > button {
  border-radius: 10px;
  border: 1px solid #E2E4E8;
  background: #FFFFFF;
  color: #23262C;
  transition: border-color .15s, color .15s;
}
.stButton > button:hover { border-color: var(--accent); color: var(--accent); }
button[kind="primary"], [data-testid="stBaseButton-primary"] {
  background: var(--accent) !important;
  border-color: var(--accent) !important;
  color: #FFFFFF !important;
}
[data-testid="stTabs"] button { color: #6F747B; font-weight: 500; }
[data-testid="stTabs"] button[aria-selected="true"] { color: var(--accent); }
[data-testid="stTextInput"] input, [data-testid="stDateInput"] input,
[data-testid="stSelectbox"] > div, [data-testid="stMultiSelect"] > div {
  border-radius: 10px;
}
/* ---------- 自定义组件 ---------- */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 12px;
  margin: 6px 0 18px;
}
.kpi-card {
  background: #FFFFFF;
  border: 1px solid #E7E8EB;
  border-radius: 14px;
  padding: 13px 15px;
  box-shadow: 0 1px 2px rgba(16, 17, 20, .04);
}
.kpi-label { font-size: .78rem; color: #7A7F87; margin-bottom: 4px; }
.kpi-value { font-size: 1.28rem; font-weight: 700; line-height: 1.25; }
.kpi-sub { font-size: .74rem; color: #9AA0A8; margin-top: 3px; }
.chip-row { margin: 4px 0 10px; }
.chip {
  display: inline-block;
  padding: 3px 12px;
  margin: 3px 6px 3px 0;
  border-radius: 999px;
  background: rgba(16, 163, 127, .10);
  border: 1px solid rgba(16, 163, 127, .35);
  color: #0E7C60;
  font-size: .82rem;
  font-weight: 600;
}
.disclaimer {
  margin: 12px 0 18px;
  padding: 13px 16px;
  border: 1px solid #F2B8B8;
  background: #FFF3F3;
  color: #B42318;
  border-radius: 12px;
  font-weight: 600;
}
.big-stat {
  background: #FFFFFF;
  border: 1px solid #E7E8EB;
  border-radius: 16px;
  padding: 20px 16px;
  text-align: center;
  box-shadow: 0 1px 2px rgba(16, 17, 20, .04);
}
.big-label { font-size: .82rem; color: #7A7F87; margin-bottom: 6px; }
.big-num { font-size: 2.7rem; font-weight: 800; line-height: 1.1; }
.big-sub { font-size: .74rem; color: #9AA0A8; margin-top: 6px; }
.page-head { margin-bottom: 14px; }
.page-title { font-size: 1.5rem; font-weight: 800; color: #17181D; }
.page-sub { font-size: .82rem; color: #8A8F97; margin: 2px 0 10px; }
.brand { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.brand-icon {
  width: 30px; height: 30px; border-radius: 9px; flex: none;
  background: linear-gradient(135deg, #34C27E, #10A37F);
  display: flex; align-items: center; justify-content: center;
  color: #FFFFFF; font-weight: 800; font-size: 1rem;
}
.brand-name { font-size: 1.02rem; font-weight: 700; color: #F2F3F5; }
.brand-sub { font-size: .72rem; color: #7E828B; margin-top: -2px; }
.hero { text-align: center; padding: 54px 12px 18px; }
.hero-icon { font-size: 3rem; }
.hero-title { font-size: 2rem; font-weight: 800; color: #17181D; margin-top: 8px; }
.hero-sub { color: #7A7F87; margin-top: 8px; font-size: .95rem; }
.block-label { font-size: .9rem; font-weight: 700; color: #23262C; margin: 10px 0 4px; }
@media (max-width: 1100px) { .kpi-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 700px) { .kpi-grid { grid-template-columns: repeat(2, 1fr); } }
"""


# =====================================================================
# 格式化工具
# =====================================================================

def _num(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_money(value: Any) -> str:
    n = _num(value)
    if n is None:
        return "—"
    absv = abs(n)
    if absv >= 1e8:
        s = f"{n / 1e8:.2f} 亿"
    elif absv >= 1e4:
        s = f"{n / 1e4:.2f} 万"
    else:
        s = f"{n:,.2f}"
    return ("+" if n > 0 else "") + s


def _pct_text(value: Any, digits: int = 2) -> str:
    n = _num(value)
    return "—" if n is None else f"{n:+.{digits}f}%"


def _dec(value: Any, digits: int = 1) -> str:
    n = _num(value)
    return "—" if n is None else f"{n:.{digits}f}"


def _sign_color(value: Any) -> str:
    n = _num(value)
    if n is None or n == 0:
        return TEXT_MAIN
    return POS_COLOR if n > 0 else NEG_COLOR


def _first(item: dict, *keys: str, default: str = "") -> str:
    for k in keys:
        v = item.get(k)
        if v not in (None, ""):
            return str(v)
    return default


def _scaled_pct(value: Any) -> Optional[float]:
    """小数比例（0.5773）→ 百分数（57.73）；已是百分数或空值原样返回。"""
    n = _num(value)
    if n is None:
        return None
    return n * 100


def _round_deep(obj: Any, nd: int = 4) -> Any:
    """递归把浮点数四舍五入到 nd 位（存储/展示更干净）。"""
    if isinstance(obj, dict):
        return {k: _round_deep(v, nd) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_round_deep(v, nd) for v in obj]
    if isinstance(obj, float):
        return round(obj, nd)
    return obj


# =====================================================================
# Mock 数据（结构完全符合第 4 章契约）
# =====================================================================

_PAIRS = [
    # (code, name, buy_date, buy_price, sell_date, sell_price, qty)
    ("600519", "贵州茅台", "2024-01-05", 1650.0, "2024-01-12", 1710.0, 200),
    ("300750", "宁德时代", "2024-02-01", 150.0, "2024-03-04", 176.5, 1000),
    ("300308", "中际旭创", "2024-03-08", 98.0, "2024-03-15", 121.0, 2000),
    ("688256", "寒武纪", "2024-04-02", 95.0, "2024-04-19", 140.0, 1500),
    ("601127", "赛力斯", "2024-04-25", 88.0, "2024-05-10", 72.0, 2000),
    ("603019", "中科曙光", "2024-05-15", 45.0, "2024-06-06", 38.5, 3000),
    ("603259", "药明康德", "2024-06-12", 52.0, "2024-07-08", 60.0, 1500),
    ("601012", "隆基绿能", "2024-07-15", 19.5, "2024-08-09", 14.8, 5000),
    ("000002", "万科A", "2024-08-16", 7.2, "2024-09-05", 8.1, 8000),
    ("600030", "中信证券", "2024-09-10", 20.0, "2024-10-18", 26.0, 3000),
    ("000858", "五粮液", "2024-10-22", 130.0, "2024-11-08", 118.0, 600),
    ("002371", "北方华创", "2024-11-12", 320.0, "2025-01-20", 420.0, 400),
    ("002466", "天齐锂业", "2025-01-27", 42.0, "2025-02-14", 33.0, 2000),
    ("300059", "东方财富", "2025-02-20", 18.5, "2025-03-14", 22.0, 5000),
    ("600150", "中国船舶", "2025-03-18", 28.0, "2025-04-11", 31.5, 2500),
    ("688256", "寒武纪", "2025-04-15", 210.0, "2025-06-30", 430.0, 800),
    ("300308", "中际旭创", "2025-05-20", 118.0, "2025-07-11", 96.0, 1500),
    ("600519", "贵州茅台", "2025-07-14", 1450.0, "2025-08-15", 1380.0, 200),
    ("300750", "宁德时代", "2025-08-19", 230.0, "2025-09-26", 268.0, 800),
    ("000002", "万科A", "2025-09-29", 10.5, "2025-10-17", 9.2, 6000),
    ("002466", "天齐锂业", "2025-10-21", 55.0, "2025-12-19", 25.0, 1500),
    ("300059", "东方财富", "2025-11-10", 24.0, "2025-12-05", 27.5, 3000),
    ("601012", "隆基绿能", "2026-01-06", 18.0, "2026-02-13", 13.0, 4000),
    ("601127", "赛力斯", "2026-02-17", 98.0, "2026-03-20", 115.0, 1200),
    ("603019", "中科曙光", "2026-03-24", 55.0, "2026-04-17", 62.0, 1500),
    ("002371", "北方华创", "2026-04-21", 380.0, "2026-05-15", 455.0, 300),
    ("000858", "五粮液", "2026-05-19", 128.0, "2026-06-12", 140.0, 500),
    ("600030", "中信证券", "2026-06-16", 24.5, "2026-07-24", 29.8, 2000),
]

_OPEN_POSITIONS = [
    # (code, name, buy_date, buy_price, qty, current_price)
    ("603259", "药明康德", "2026-06-02", 58.0, 800, 66.0),
    ("600150", "中国船舶", "2026-06-20", 32.0, 1500, 35.0),
    ("601012", "隆基绿能", "2026-07-10", 14.2, 3000, 13.5),
    ("688256", "寒武纪", "2026-07-15", 520.0, 100, 545.0),
]

_SPECIAL_ROWS = [
    # (date, op_type, name, amount)
    ("2024-03-20", "通用回购逆回", "GC001", 50000.0),
    ("2024-09-30", "通用回购逆回", "GC001", 80000.0),
    ("2025-01-10", "红利入账", "贵州茅台", 1200.0),
    ("2025-06-25", "红利入账", "宁德时代", 860.0),
    ("2025-11-20", "利息归本", "资金账户", 152.3),
    ("2026-06-05", "红利入账", "五粮液", 640.0),
]


def _iter_months(first: str, last: str):
    y, m = map(int, first.split("-"))
    end_y, end_m = map(int, last.split("-"))
    while (y, m) <= (end_y, end_m):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m = 1
            y += 1


def _build_mock_rows() -> list:
    rows: list = []
    for code, name, bd, bp, sd, sp, qty in _PAIRS:
        buy_amt = round(bp * qty, 2)
        sell_amt = round(sp * qty, 2)
        buy_fee = round(buy_amt * 0.0008, 2)
        sell_fee = round(sell_amt * 0.0008 + sell_amt * 0.0005, 2)
        days = (datetime.strptime(sd, "%Y-%m-%d") - datetime.strptime(bd, "%Y-%m-%d")).days
        pnl = round((sp - bp) * qty - buy_fee - sell_fee, 2)
        rows.append({"date": bd, "code": code, "name": name, "op_type": "证券买入",
                     "qty": qty, "price": bp, "amount": buy_amt, "fee": buy_fee,
                     "pnl": None, "holding_days": None})
        rows.append({"date": sd, "code": code, "name": name, "op_type": "证券卖出",
                     "qty": qty, "price": sp, "amount": sell_amt, "fee": sell_fee,
                     "pnl": pnl, "holding_days": days})
    for code, name, d, price, qty, _cur in _OPEN_POSITIONS:
        amt = round(price * qty, 2)
        fee = round(amt * 0.0008, 2)
        rows.append({"date": d, "code": code, "name": name, "op_type": "证券买入",
                     "qty": qty, "price": price, "amount": amt, "fee": fee,
                     "pnl": None, "holding_days": None, "open": True})
    for d, op, name, amount in _SPECIAL_ROWS:
        income = op in ("红利入账", "利息归本")
        rows.append({"date": d, "code": "", "name": name, "op_type": op,
                     "qty": None, "price": None, "amount": round(amount, 2), "fee": 0.0,
                     "pnl": round(amount, 2) if income else None, "holding_days": None})
    rows.sort(key=lambda r: (r["date"], r["op_type"]))
    return rows


def mock_metrics() -> dict:
    """内置完整 MetricsResult（JSON 可序列化 dict，契约结构）。"""
    rows = _build_mock_rows()
    buys = [r for r in rows if r.get("op_type") == "证券买入"]
    sells = [r for r in rows if r.get("op_type") == "证券卖出"]
    wins = [r for r in sells if (r.get("pnl") or 0) > 0]
    losses = [r for r in sells if (r.get("pnl") or 0) < 0]
    realized = round(sum(float(r.get("pnl") or 0) for r in sells), 2)
    gross_profit = round(sum(float(r["pnl"]) for r in wins), 2)
    gross_loss = round(abs(sum(float(r["pnl"]) for r in losses)), 2)
    win_rate = len(wins) / len(sells) * 100 if sells else 0.0
    pl_ratio = (gross_profit / gross_loss) if gross_loss else (999.0 if gross_profit else 0.0)
    max_single_profit = max((float(r["pnl"]) for r in wins), default=0.0)
    max_single_loss = min((float(r["pnl"]) for r in losses), default=0.0)
    total_fee = round(sum(float(r.get("fee") or 0) for r in rows), 2)
    total_amount = round(sum(float(r.get("amount") or 0) for r in rows
                            if r.get("op_type") in ("证券买入", "证券卖出")), 2)

    monthly_pnl: dict = {}
    monthly_activity: dict = {}
    stock_pnl: dict = {}
    stock_amount: dict = {}
    name_code: dict = {}
    for r in rows:
        m = r["date"][:7]
        monthly_activity[m] = monthly_activity.get(m, 0) + 1
        if r.get("pnl") is not None:
            monthly_pnl[m] = monthly_pnl.get(m, 0.0) + float(r["pnl"])
        if r.get("name"):
            name_code[r["name"]] = r.get("code") or name_code.get(r["name"], "")
        if r.get("op_type") == "证券卖出" and r.get("pnl") is not None:
            stock_pnl[r["name"]] = stock_pnl.get(r["name"], 0.0) + float(r["pnl"])
        if r.get("op_type") in ("证券买入", "证券卖出") and r.get("code"):
            stock_amount[r["code"]] = stock_amount.get(r["code"], 0.0) + float(r["amount"])

    dates = sorted({r["date"] for r in rows})
    start_date = dates[0] if dates else ""
    end_date = dates[-1] if dates else ""
    all_months = list(_iter_months(start_date[:7], end_date[:7])) if dates else []

    initial = 500000.0
    equity_series = []
    running = initial
    peak = initial
    for m in all_months:
        running += monthly_pnl.get(m, 0.0)
        peak = max(peak, running)
        dd = (running - peak) / peak * 100 if peak else 0.0
        equity_series.append({"date": f"{m}-末", "equity": round(running, 2),
                              "drawdown_pct": round(dd, 2)})
    final_cash = running

    position_value = round(sum(float(p[4]) * float(p[3]) for p in _OPEN_POSITIONS), 2)
    floating = round(sum(float(p[5]) * float(p[4]) - float(p[3]) * float(p[4])
                         for p in _OPEN_POSITIONS), 2)
    total_asset = final_cash + position_value
    total_return_pct = (total_asset - initial) / initial * 100 if initial else 0.0
    days = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(start_date, "%Y-%m-%d")).days
    if days > 0 and total_return_pct > -100:
        annual_pct = ((1 + total_return_pct / 100) ** (365 / days) - 1) * 100
    else:
        annual_pct = 0.0

    buckets = {"≤1天": 0, "2–5天": 0, "6–20天": 0, ">20天": 0}
    for r in sells:
        d = int(r.get("holding_days") or 0)
        if d <= 1:
            buckets["≤1天"] += 1
        elif d <= 5:
            buckets["2–5天"] += 1
        elif d <= 20:
            buckets["6–20天"] += 1
        else:
            buckets[">20天"] += 1
    holding_dist = [{"bucket": k, "count": v} for k, v in buckets.items()]
    avg_holding = round(sum(int(r["holding_days"]) for r in sells) / len(sells), 2) if sells else 0

    trading_days = len(dates)
    total_count = len(rows)
    name_counts = Counter(r["name"] for r in rows if r.get("name"))
    favorites = [{"code": name_code.get(n, ""), "name": n, "trades": c}
                 for n, c in name_counts.most_common(10)]

    ranked = sorted(stock_pnl.items(), key=lambda kv: kv[1])
    winners_list = [{"name": n, "code": name_code.get(n, ""), "pnl": round(v, 2)}
                    for n, v in ranked[-10:][::-1] if v > 0]
    losers_list = [{"name": n, "code": name_code.get(n, ""), "pnl": round(v, 2)}
                   for n, v in ranked[:10] if v < 0]

    double_count = halved_count = 0
    for _code, _name, _bd, bp, _sd, sp, qty in _PAIRS:
        buy_fee = round(bp * qty * 0.0008, 2)
        sell_fee = round(sp * qty * 0.0008 + sp * qty * 0.0005, 2)
        cost = bp * qty + buy_fee
        pnl_pair = (sp - bp) * qty - buy_fee - sell_fee
        ret = pnl_pair / cost if cost else 0
        if ret >= 1.0:
            double_count += 1
        if ret <= -0.5:
            halved_count += 1

    top5_amt = sum(v for _, v in sorted(stock_amount.items(), key=lambda kv: kv[1], reverse=True)[:5])
    concentration = top5_amt / total_amount * 100 if total_amount else 0
    max_pos_pct = (max((float(p[3]) * float(p[4]) for p in _OPEN_POSITIONS), default=0.0)
                   / total_asset * 100) if total_asset else 0

    if avg_holding <= 5:
        horizon = "超短线"
    elif avg_holding <= 15:
        horizon = "短线"
    elif avg_holding <= 40:
        horizon = "波段"
    else:
        horizon = "长线"
    focus = "集中" if concentration >= 60 else "分散"
    if avg_holding <= 10 or double_count >= 1:
        aggressiveness = "激进"
    elif avg_holding >= 40:
        aggressiveness = "稳健"
    else:
        aggressiveness = "均衡"

    sell_amount = round(sum(float(r["amount"]) for r in sells), 2)
    avg_balance = (initial + final_cash) / 2
    acct = {
        "period_start": start_date,
        "period_end": end_date,
        "period_days": days,
        "initial_capital": round(initial, 2),
        "final_capital": round(final_cash, 2),
        "net_transfer_in": 0.0,
        "gross_deposit": 0.0,
        "gross_withdraw": 0.0,
        "opening_asset_value": round(initial, 2),
        "total_return_pct": round(total_return_pct, 2),
        "annual_return_pct": round(annual_pct, 2),
        "realized_pnl": realized,
        "total_cost": total_fee,
        "cost_ratio_pct": round(total_fee / total_amount * 100, 2) if total_amount else 0,
        "position_value": position_value,
        "floating_pnl": floating,
        "max_drawdown_pct": round(min((c["drawdown_pct"] for c in equity_series), default=0.0), 2),
        "label": "总收益",
    }
    trades_block = {
        "total_amount": total_amount,
        "total_count": total_count,
        "buy_count": len(buys),
        "buy_amount": round(sum(float(r["amount"]) for r in buys), 2),
        "sell_count": len(sells),
        "sell_amount": sell_amount,
        "avg_daily_count": round(total_count / trading_days, 2) if trading_days else 0,
        "avg_daily_amount": round(total_amount / trading_days, 2) if trading_days else 0,
        "stock_count": len({r["code"] for r in rows if r.get("code")}),
        "position_count": len(_OPEN_POSITIONS),
        "avg_trade_amount": round(total_amount / (len(buys) + len(sells)), 2) if (buys or sells) else 0,
        "turnover_rate": round(total_amount / avg_balance, 2) if avg_balance else 0,
        "avg_holding_days": avg_holding,
    }
    pnl_block = {
        "realized_pnl": realized,
        "win_count": len(wins),
        "loss_count": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_loss_ratio": round(pl_ratio, 2),
        "max_single_profit": round(max_single_profit, 2),
        "max_single_loss": round(max_single_loss, 2),
        "double_count": double_count,
        "halved_count": halved_count,
        "monthly_pnl": [{"month": m, "pnl": round(monthly_pnl.get(m, 0.0), 2)} for m in all_months],
        "equity_curve": equity_series,
        "top_winners": winners_list,
        "top_losers": losers_list,
    }
    behavior = {
        "holding_days_dist": holding_dist,
        "monthly_activity": [{"month": m, "trades": monthly_activity.get(m, 0)} for m in all_months],
        "max_position_pct": round(max_pos_pct, 2),
        "top5_concentration_pct": round(concentration, 2),
        "favorite_stocks": favorites,
        "style": {
            "horizon": horizon,
            "focus": focus,
            "aggressiveness": aggressiveness,
            "summary": (f"平均持仓 {avg_holding} 天，换手偏"
                        f"{'高' if avg_holding <= 20 else '低'}，Top5 成交额占比 "
                        f"{concentration:.1f}%，风格偏{aggressiveness}。"),
        },
        "special_ops": {
            "reverse_repo": sum(1 for r in _SPECIAL_ROWS if r[1] == "通用回购逆回"),
            "dividends": sum(1 for r in _SPECIAL_ROWS if r[1] == "红利入账"),
            "interest": sum(1 for r in _SPECIAL_ROWS if r[1] == "利息归本"),
            "new_stock": 0,
        },
    }
    return {
        "source": "mock",
        "is_partial": False,
        "market_value_source": "cost",
        "period_start": start_date,
        "period_end": end_date,
        "account": acct,
        "trades": trades_block,
        "pnl": pnl_block,
        "behavior": behavior,
        "trade_rows": rows,
    }


_ANALYSTS = [
    {"name": "阿狼", "role": "趋势猎手", "tags": ["追涨达人", "拐点雷达"],
     "comment": "净值曲线斜率尚可，但我闻到一股「敢重仓、敢快跑」的味道。翻倍操作值得发朋友圈，腰斩案例就别发了。"},
    {"name": "爱在冰川", "role": "情绪温度计", "tags": ["情绪大师", "手痒警告"],
     "comment": "你这不是交易，是情绪过山车：赢的时候觉得自己是股神，亏的时候假装自己是价值投资。"},
    {"name": "拔小弦", "role": "细节控", "tags": ["费用审计员", "鸡腿守护者"],
     "comment": "手续费缴得很积极，堪称券商年度最佳客户。建议把「手痒」频率调低一点，省下的费用够加不少鸡腿。"},
    {"name": "炒股养家", "role": "大局观", "tags": ["配置大师", "集中度警察"],
     "comment": "仓位集中度像浓缩咖啡——够劲但容易失眠。适当分散，睡眠质量和净值曲线都会变好。"},
    {"name": "铁锤狂砸盘", "role": "风险官", "tags": ["止损教官", "回撤克星"],
     "comment": "最大回撤和那几笔腰斩，我隔着屏幕都替你捏把汗。仓位管理不是选修课，是保命必修课。"},
]

_MOCK_REPORT = """# 综合分析报告（演示数据）

## 一、账户概况
- 统计区间：2024-01-05 ~ 2026-07-24，约 931 天
- 总收益率约 +64%，年化约 +21%；已实现盈亏约 +32 万元，胜率约 64%
- 期末持仓 4 只（按成本估算），另有逆回购、分红等特殊操作记录

## 二、分析师核心观点
- **阿狼（趋势猎手）**：主升段拿得住，翻倍操作是全场最佳镜头。
- **爱在冰川（情绪温度计）**：情绪波动大，追涨杀跌痕迹明显，建议「冷启动」几天再下单。
- **拔小弦（细节控）**：交易频率偏高，手续费与印花税是隐形成本，长期会吃掉利润。
- **炒股养家（大局观）**：集中度偏高，单票行情好的时候爽，行情反转时也疼。
- **铁锤狂砸盘（风险官）**：腰斩记录说明止损纪律需要加强，别让亏损单「陪跑」。

## 三、分歧与讨论
主持人与 5 位分析师辩论两轮：核心分歧是「重仓追强势股」还是「先管住回撤」。
最终共识：保留进攻仓位，单票上限 30%；亏损单设置硬止损；降低交易频率。

## 四、操作意见
1. 单票仓位建议不超过总资产 30%，避免单一标的大幅波动影响全局。
2. 为每笔交易预设止损位（建议 −8% 以内），腰斩类亏损尽量不再发生。
3. 降低无效交易频率，把手续费预算花在更确定的信号上。

## 五、幽默标签
短线波段混合 · 翻倍选手 · 重仓警告 · 手续费贡献者

## 六、风险提示
历史业绩不代表未来收益；集中持仓放大波动；频繁交易推高成本。

---

> 仅供参考，不构成投资建议。市场有风险，投资需谨慎。
"""


def mock_analysis() -> dict:
    """内置完整 AnalysisResult（契约结构：final_report/analysts/debate_history/
    overall_tags/disclaimer/degraded/round_count）。"""
    return {
        "final_report": _MOCK_REPORT,
        "analysts": [dict(a) for a in _ANALYSTS],
        "debate_history": [
            {"round": 1, "speaker": "主持人", "content": "议题：仓位集中还是分散？"},
            {"round": 1, "speaker": "阿狼", "content": "翻倍票就该重仓拿住，怕高都是苦命人。"},
            {"round": 1, "speaker": "铁锤狂砸盘", "content": "腰斩那几笔还在流血，先管住回撤再说。"},
            {"round": 2, "speaker": "爱在冰川", "content": "情绪面看，最近明显追涨杀跌，建议冷启动三天再出手。"},
            {"round": 2, "speaker": "主持人", "content": "结论：保留进攻仓位，单票上限 30%，亏损单坚决止损。"},
        ],
        "overall_tags": ["短线波段混合", "翻倍选手", "重仓警告", "手续费贡献者"],
        "disclaimer": DISCLAIMER,
        "degraded": False,
        "round_count": 2,
    }


def fallback_analysis(reason: str = "", metrics: Optional[dict] = None) -> dict:
    """AI 不可用时的规则引擎兜底结果（degraded=True），指标区不受影响。"""
    metrics = metrics or {}
    acct = metrics.get("account") or {}
    pnl = metrics.get("pnl") or {}
    trd = metrics.get("trades") or {}
    reason_txt = reason or "AI 服务暂不可用"
    report = f"""# 综合分析报告（降级 · 规则引擎兜底）

> {reason_txt}。以下为规则引擎基于指标生成的保守点评，指标区不受影响。

## 一、账户概况（客观指标）
- 总收益率：{_pct_text(acct.get('total_return_pct'))}；年化：{_pct_text(acct.get('annual_return_pct'))}
- 已实现盈亏：{_fmt_money(pnl.get('realized_pnl'))}；胜率：{_dec(pnl.get('win_rate_pct'), 1)}%
- 交易笔数：{trd.get('total_count', 0)}；翻倍次数：{pnl.get('double_count', 0)}；腰斩次数：{pnl.get('halved_count', 0)}；最大回撤：{_dec(acct.get('max_drawdown_pct'), 2)}%

## 二、规则兜底意见
- 胜率不足 50% 时，优先降低交易频率，等待更明确的信号再出手。
- 单票仓位与集中度过高时，注意用止损控制单笔风险敞口。
- 翻倍与腰斩记录是最好的仓位管理教材：赚钱靠拿得住，亏钱常因不止损。

---

> 仅供参考，不构成投资建议。市场有风险，投资需谨慎。
"""
    return {
        "final_report": report,
        "analysts": [],
        "debate_history": [],
        "overall_tags": ["AI 离线", "规则兜底", "仅供参考"],
        "disclaimer": DISCLAIMER,
        "degraded": True,
        "round_count": 0,
        "degraded_reason": reason_txt,
    }


# =====================================================================
# 主题
# =====================================================================

def apply_theme() -> None:
    st.markdown(f"<style>{_CSS.replace('__ACCENT__', ACCENT)}</style>", unsafe_allow_html=True)


def render_sidebar_brand() -> None:
    st.markdown(
        '<div class="brand"><div class="brand-icon">✦</div>'
        '<div><div class="brand-name">Synalysis</div>'
        '<div class="brand-sub">交割单 · 指标 · AI 点评</div></div></div>',
        unsafe_allow_html=True,
    )


def _chips(tags: Any) -> str:
    if not tags:
        return ""
    return '<div class="chip-row">' + "".join(
        f'<span class="chip">{html.escape(str(t))}</span>' for t in tags
    ) + "</div>"


def _kpi_grid(cards: list) -> None:
    parts = ['<div class="kpi-grid">']
    for c in cards:
        color = c.get("color") or TEXT_MAIN
        parts.append(
            f'<div class="kpi-card"><div class="kpi-label">{html.escape(str(c.get("label", "")))}</div>'
            f'<div class="kpi-value" style="color:{color}">{html.escape(str(c.get("value", "—")))}</div>'
            f'<div class="kpi-sub">{html.escape(str(c.get("sub", "")))}</div></div>'
        )
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def _big_stat(label: str, value: Any, color: str, sub: str) -> None:
    st.markdown(
        f'<div class="big-stat"><div class="big-label">{html.escape(label)}</div>'
        f'<div class="big-num" style="color:{color}">{html.escape(str(value))}</div>'
        f'<div class="big-sub">{html.escape(sub)}</div></div>',
        unsafe_allow_html=True,
    )


def _disclaimer_box(text: str) -> None:
    st.markdown(f'<div class="disclaimer">⚠️ {html.escape(str(text))}</div>', unsafe_allow_html=True)


def _base_layout(fig: go.Figure, title: str = "", height: int = 360) -> None:
    layout = dict(
        height=height,
        margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#FFFFFF",
        font=dict(family='"Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif',
                  size=12, color="#3D4149"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
        hoverlabel=dict(font=dict(family='"Microsoft YaHei", sans-serif', size=12)),
    )
    if title:
        layout["title"] = dict(text=title, font=dict(size=15, color="#23262C"))
    fig.update_layout(**layout)


def _plot(fig: Optional[go.Figure]) -> None:
    if fig is not None:
        st.plotly_chart(fig, theme=None, config={"displayModeBar": False})


# =====================================================================
# 图表
# =====================================================================

def _equity_series(metrics: dict) -> list:
    pnl_block = metrics.get("pnl") or {}
    curve = pnl_block.get("equity_curve")
    if curve:
        return list(curve)
    monthly = pnl_block.get("monthly_pnl") or []
    acct = metrics.get("account") or {}
    initial = float(acct.get("initial_capital") or 0)
    out = []
    running = initial
    peak = initial
    for row in monthly:
        running += float(row.get("pnl") or 0)
        peak = max(peak, running)
        dd = (running - peak) / peak * 100 if peak else 0.0
        out.append({"date": str(row.get("month", "")) + "-末",
                    "equity": round(running, 2), "drawdown_pct": round(dd, 2)})
    return out


def _equity_figure(metrics: dict) -> Optional[go.Figure]:
    series = _equity_series(metrics)
    if not series:
        return None
    dates = [str(s.get("date", "")) for s in series]
    eq = [s.get("equity") for s in series]
    dd = [s.get("drawdown_pct", 0) for s in series]
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=dates, y=eq, mode="lines+markers",
                             name="累计资产（近似净值）",
                             line=dict(color=ACCENT, width=2.5),
                             marker=dict(size=5, color=ACCENT),
                             fill="tozeroy", fillcolor="rgba(232,121,31,0.08)"),
                  secondary_y=False)
    fig.add_trace(go.Scatter(x=dates, y=dd, mode="lines", name="回撤 %",
                             line=dict(color="#E5484D", width=1.3, dash="dot")),
                  secondary_y=True)
    _base_layout(fig, "累计收益曲线（月末近似净值）", 380)
    fig.update_yaxes(title_text="资产（元）", secondary_y=False,
                     gridcolor="#EFF0F2", tickformat=",.0f")
    fig.update_yaxes(title_text="回撤 %", secondary_y=True,
                     gridcolor="#F6F6F7", zeroline=False)
    return fig


def _monthly_pnl_figure(metrics: dict) -> Optional[go.Figure]:
    rows = (metrics.get("pnl") or {}).get("monthly_pnl") or []
    if not rows:
        return None
    months = [str(r.get("month", "")) for r in rows]
    vals = [float(r.get("pnl") or 0) for r in rows]
    colors = [POS_COLOR if v >= 0 else NEG_COLOR for v in vals]
    fig = go.Figure(go.Bar(x=months, y=vals, marker_color=colors, name="月度盈亏",
                           hovertemplate="%{x}<br>%{y:,.2f} 元<extra></extra>"))
    fig.add_hline(y=0, line_color="#C9CDD3", line_width=1)
    _base_layout(fig, "月度盈亏（已实现，含费用）", 320)
    fig.update_yaxes(gridcolor="#EFF0F2", tickformat=",.0f")
    return fig


def _pnl_distribution_figure(metrics: dict) -> Optional[go.Figure]:
    rows = metrics.get("trade_rows") or []
    sells = [float(r["pnl"]) for r in rows if r.get("pnl") is not None]
    if not sells:
        # 真实指标未提供单笔盈亏：用个股榜 Top20 画分布
        winners, losers = _stock_rankings(metrics)
        lb = [float(x.get("pnl") or 0) for x in winners + losers]
        if not lb:
            return None
        fig = go.Figure(go.Histogram(x=lb, marker_color="#8A93A3", opacity=0.9, nbinsx=12,
                                     hovertemplate="%{x:,.2f} 元<extra></extra>"))
        _base_layout(fig, "个股盈亏分布（榜单 Top20）", 340)
        fig.update_xaxes(title_text="个股累计已实现盈亏（元）", gridcolor="#F0F1F3", tickformat=",.0f")
        fig.update_yaxes(title_text="个股数", gridcolor="#F0F1F3")
        return fig
    pos = [v for v in sells if v >= 0]
    neg = [v for v in sells if v < 0]
    fig = go.Figure()
    if pos:
        fig.add_trace(go.Histogram(x=pos, name="盈利笔数", marker_color=POS_COLOR,
                                   opacity=0.88, nbinsx=12))
    if neg:
        fig.add_trace(go.Histogram(x=neg, name="亏损笔数", marker_color=NEG_COLOR,
                                   opacity=0.88, nbinsx=12))
    fig.update_layout(barmode="overlay", bargap=0.05)
    _base_layout(fig, "已实现盈亏分布（按卖出配对笔）", 340)
    fig.update_xaxes(title_text="单笔已实现盈亏（元）", gridcolor="#F0F1F3", tickformat=",.0f")
    fig.update_yaxes(title_text="笔数", gridcolor="#F0F1F3")
    return fig


def _ranking_figure(items: list, title: str, color: str) -> Optional[go.Figure]:
    if not items:
        return None
    names, vals = [], []
    for it in items:
        nm = str(it.get("name") or "")
        code = str(it.get("code") or "")
        names.append(f"{nm} · {code}" if code else nm)
        vals.append(float(it.get("pnl") or it.get("realized_pnl") or 0))
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    names = [names[i] for i in order]
    vals = [vals[i] for i in order]
    fig = go.Figure(go.Bar(x=vals, y=names, orientation="h", marker_color=color,
                           hovertemplate="%{y}<br>%{x:,.2f} 元<extra></extra>"))
    _base_layout(fig, title, max(280, 60 + len(items) * 30))
    fig.update_xaxes(gridcolor="#EFF0F2", tickformat=",.0f")
    fig.update_yaxes(gridcolor="#F6F6F7")
    return fig


def _holding_figure(metrics: dict) -> Optional[go.Figure]:
    dist = (metrics.get("behavior") or {}).get("holding_days_dist") or []
    if not dist:
        return None
    data = {str(d.get("bucket")): int(d.get("count") or 0) for d in dist}
    order = ["≤1天", "2–5天", "6–20天", ">20天"]
    buckets = [b for b in order if b in data] or list(data.keys())
    counts = [data[b] for b in buckets]
    fig = go.Figure(go.Bar(x=buckets, y=counts, marker_color=ACCENT,
                           hovertemplate="%{x}<br>%{y} 笔<extra></extra>"))
    _base_layout(fig, "持仓周期分布（卖出配对笔）", 320)
    fig.update_yaxes(gridcolor="#EFF0F2")
    return fig


def _activity_figure(metrics: dict) -> Optional[go.Figure]:
    rows = (metrics.get("behavior") or {}).get("monthly_activity") or []
    if not rows:
        return None
    months = [str(r.get("month", "")) for r in rows]
    counts = [int(r.get("trades") or 0) for r in rows]
    fig = go.Figure(go.Bar(x=months, y=counts, marker_color="#8A93A3",
                           hovertemplate="%{x}<br>%{y} 笔<extra></extra>"))
    _base_layout(fig, "月度交易活跃度（笔数）", 320)
    fig.update_yaxes(gridcolor="#EFF0F2")
    return fig


def _stock_rankings(metrics: dict) -> tuple:
    pnl = metrics.get("pnl") or {}
    winners = pnl.get("top_winners") or []
    losers = pnl.get("top_losers") or []
    if winners or losers:
        return winners, losers
    rows = metrics.get("trade_rows") or []
    agg: dict = {}
    code_map: dict = {}
    for r in rows:
        if r.get("pnl") is None or not r.get("name"):
            continue
        nm = str(r["name"])
        agg[nm] = agg.get(nm, 0.0) + float(r["pnl"])
        if r.get("code"):
            code_map[nm] = str(r["code"])
    ranked = sorted(agg.items(), key=lambda kv: kv[1], reverse=True)
    winners = [{"name": n, "code": code_map.get(n, ""), "pnl": round(v, 2)}
               for n, v in ranked[:10] if v > 0]
    losers = [{"name": n, "code": code_map.get(n, ""), "pnl": round(v, 2)}
              for n, v in ranked[::-1][:10] if v < 0]
    return winners, losers


# =====================================================================
# 页面组件
# =====================================================================

def render_header(meta: dict, metrics: dict) -> None:
    fname = str(meta.get("file_name") or "未命名分析")
    ts = str(meta.get("timestamp") or meta.get("created_at") or "")
    chips = []
    if metrics.get("is_partial"):
        chips.append(("区间收益", "rgba(232,121,31,.12)", "rgba(232,121,31,.45)", "#B45309"))
    if str(metrics.get("market_value_source") or "").lower() == "cost":
        chips.append(("按成本估算", "rgba(109,40,217,.10)", "rgba(109,40,217,.35)", "#6D28D9"))
    if meta.get("demo"):
        chips.append(("演示数据", "rgba(107,114,128,.12)", "rgba(107,114,128,.35)", "#6B7280"))
    chip_html = "".join(
        f'<span class="chip" style="background:{bg};border-color:{bd};color:{fg}">'
        f'{html.escape(t)}</span>'
        for t, bg, bd, fg in chips
    )
    st.markdown(
        f'<div class="page-head"><div class="page-title">{html.escape(fname)}</div>'
        f'<div class="page-sub">{html.escape(ts)}</div>{chip_html}</div>',
        unsafe_allow_html=True,
    )


def render_welcome(on_demo: Any = None) -> None:
    st.markdown(
        '<div class="hero"><div class="hero-icon">📈</div>'
        '<div class="hero-title">Synalysis 交易分析台</div>'
        '<div class="hero-sub">上传同花顺交割单，自动生成账户指标、盈亏画像与 5 位分析师幽默点评</div></div>',
        unsafe_allow_html=True,
    )
    steps = [
        ("① 上传交割单", "在左侧侧栏点击「新建分析」，上传同花顺导出的交割单（xlsx / xls / csv），全程仅本地处理"),
        ("② 自动生成指标", "解析 → FIFO 盈亏配对 → 账户 / 交易 / 盈亏 / 行为指标与图表"),
        ("③ AI 分析师点评", "5 位分析师辩论后产出综合报告、幽默标签与风险提示（含免责声明）"),
    ]
    cols = st.columns(3)
    for col, (t, d) in zip(cols, steps):
        with col:
            st.markdown(
                f'<div class="kpi-card"><div class="kpi-label">{html.escape(t)}</div>'
                f'<div class="kpi-sub" style="color:#5A5F66;line-height:1.6">{html.escape(d)}</div></div>',
                unsafe_allow_html=True,
            )
    st.markdown('<div style="height:16px"></div>', unsafe_allow_html=True)
    col_a, col_b, col_c = st.columns([1, 1.5, 1])
    with col_b:
        if on_demo is not None:
            if st.button("🚀 先看内置演示数据", key="btn_demo_main", type="primary", width="stretch"):
                on_demo()
        st.caption("开发期上游模块未就绪时，演示数据可预览全部页面；真实数据仅存本地。")


def render_account_overview(metrics: dict) -> None:
    acct = metrics.get("account") or {}
    pnl = metrics.get("pnl") or {}
    trd = metrics.get("trades") or {}
    is_partial = bool(metrics.get("is_partial"))
    source = str(metrics.get("market_value_source") or "cost").lower()
    st.caption(
        f"统计区间：{acct.get('period_start', '—')} ~ {acct.get('period_end', '—')}"
        + (" ｜ 文件从中途开始，以下为「区间收益」口径" if is_partial else " ｜ 完整历史，「总收益」口径")
    )
    cards = [
        {"label": "总收益率", "value": _pct_text(acct.get("total_return_pct")),
         "sub": (acct.get("label") or ("区间收益" if is_partial else "总收益"))
                + " · "
                + ("期初资产基准" if _num(acct.get("opening_asset_value")) > 0 else "累计入金基准"),
         "color": _sign_color(acct.get("total_return_pct"))},
        {"label": "年化收益率", "value": _pct_text(acct.get("annual_return_pct")),
         "sub": f"{int(acct.get('period_days') or 0)} 天折算",
         "color": _sign_color(acct.get("annual_return_pct"))},
        {"label": "已实现盈亏", "value": _fmt_money(pnl.get("realized_pnl")),
         "sub": "FIFO 配对（含费用）", "color": _sign_color(pnl.get("realized_pnl"))},
        {"label": "胜率", "value": f"{_dec(pnl.get('win_rate_pct'), 1)}%",
         "sub": f"{pnl.get('win_count', 0)} 盈 / {pnl.get('loss_count', 0)} 亏"},
        {"label": "最大回撤", "value": f"{_dec(acct.get('max_drawdown_pct'), 2)}%",
         "sub": "基于月末资产近似净值", "color": NEG_COLOR},
        {"label": "总交易成本", "value": _fmt_money(acct.get("total_cost")),
         "sub": f"占成交额 {_dec(acct.get('cost_ratio_pct'), 2)}%"},
    ]
    _kpi_grid(cards)
    cards2 = [
        {"label": "期末持仓市值", "value": _fmt_money(acct.get("position_value")),
         "sub": "按成本估算" if source == "cost" else "按最新行情"},
        {"label": "浮动盈亏", "value": _fmt_money(acct.get("floating_pnl")),
         "color": _sign_color(acct.get("floating_pnl"))},
        {"label": "总成交额", "value": _fmt_money(trd.get("total_amount"))},
        {"label": "交易笔数", "value": f"{int(trd.get('total_count') or 0):,}",
         "sub": f"买 {trd.get('buy_count', 0)} / 卖 {trd.get('sell_count', 0)}"},
        {"label": "交易股票数", "value": f"{int(trd.get('stock_count') or 0)} 只",
         "sub": f"当前持仓 {trd.get('position_count', 0)} 只"},
        {"label": "平均持仓周期", "value": f"{_dec(trd.get('avg_holding_days'), 1)} 天"},
    ]
    _kpi_grid(cards2)
    cards3 = [
        {"label": "累计入金", "value": _fmt_money(acct.get("gross_deposit")),
         "sub": "银行转证券合计"},
        {"label": "累计出金", "value": _fmt_money(acct.get("gross_withdraw")),
         "sub": "证券转银行合计"},
        {"label": "净转入", "value": _fmt_money(acct.get("net_transfer_in")),
         "sub": "入金 − 出金", "color": _sign_color(acct.get("net_transfer_in"))},
    ]
    _kpi_grid(cards3)
    st.subheader("累计收益曲线")
    fig = _equity_figure(metrics)
    if fig:
        _plot(fig)
    else:
        st.info("暂无累计收益曲线数据。")
    st.subheader("月度盈亏")
    fig2 = _monthly_pnl_figure(metrics)
    if fig2:
        _plot(fig2)
    else:
        st.info("暂无月度盈亏数据。")


def render_trade_detail(metrics: dict) -> None:
    rows = metrics.get("trade_rows") or []
    if not rows:
        st.info("暂无交易明细数据。")
        return
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).copy()
    if df.empty:
        st.info("交易明细日期无法解析。")
        return
    df["op_type_str"] = df["op_type"].astype(str)
    df["op_label"] = df["op_type_str"].map(_OP_LABELS).fillna(df["op_type_str"])
    df["date_str"] = df["date"].dt.strftime("%Y-%m-%d")
    base = df.sort_values("date", ascending=False)

    f1, f2, f3 = st.columns([1.6, 1, 1.2])
    stock_opts = (base["name"].astype(str) + " " + base["code"].astype(str)).drop_duplicates().tolist()
    with f1:
        sel_stocks = st.multiselect("股票", stock_opts, placeholder="全部股票")
    with f2:
        sel_ops = st.multiselect("操作类型", sorted(base["op_label"].dropna().unique().tolist()),
                                 placeholder="全部操作")
    with f3:
        q = st.text_input("搜索代码 / 名称", placeholder="如 600519 或 茅台")
    dmin, dmax = base["date"].min().date(), base["date"].max().date()
    rng = st.date_input("时间范围", value=(dmin, dmax), min_value=dmin, max_value=dmax)
    if isinstance(rng, (tuple, list)) and len(rng) == 2:
        d0, d1 = rng[0], rng[1]
    else:
        d0 = d1 = rng

    mask = pd.Series(True, index=base.index)
    if sel_stocks:
        mask &= (base["name"].astype(str) + " " + base["code"].astype(str)).isin(sel_stocks)
    if sel_ops:
        mask &= base["op_label"].isin(sel_ops)
    if q:
        mask &= (base["name"].astype(str).str.contains(q, case=False, na=False)
                 | base["code"].astype(str).str.contains(q, case=False, na=False))
    mask &= (base["date"].dt.date >= d0) & (base["date"].dt.date <= d1)
    view = base[mask].copy()
    view["盈亏"] = view["pnl"].apply(lambda v: f"{v:+,.2f}" if pd.notna(v) else "—")
    view["持仓天数"] = view["holding_days"].apply(lambda v: f"{int(v)} 天" if pd.notna(v) else "—")
    show = pd.DataFrame({
        "日期": view["date_str"],
        "代码": view["code"],
        "名称": view["name"],
        "操作": view["op_label"],
        "数量": view["qty"].where(pd.notna(view["qty"]), None),
        "成交均价": view["price"].where(pd.notna(view["price"]), None),
        "成交金额": view["amount"].where(pd.notna(view["amount"]), None),
        "费用": view["fee"].where(pd.notna(view["fee"]), None),
        "盈亏": view["盈亏"],
        "持仓天数": view["持仓天数"],
    })
    st.dataframe(
        show,
        column_config={
            "成交均价": st.column_config.NumberColumn(format="%.3f"),
            "成交金额": st.column_config.NumberColumn(format="%.2f"),
            "费用": st.column_config.NumberColumn(format="%.2f"),
            "数量": st.column_config.NumberColumn(format="%d"),
        },
        hide_index=True,
        height=460,
    )
    st.caption(f"共 {len(view):,} 笔（筛选后）／全部 {len(base):,} 笔")


def render_pnl_analysis(metrics: dict) -> None:
    pnl = metrics.get("pnl") or {}
    c1, c2 = st.columns(2)
    with c1:
        _big_stat("翻倍次数", pnl.get("double_count", 0), POS_COLOR,
                  "个股完整持仓周期收益率 ≥ +100%")
    with c2:
        _big_stat("腰斩次数", pnl.get("halved_count", 0), NEG_COLOR,
                  "个股完整持仓周期收益率 ≤ −50%")
    cards = [
        {"label": "胜率", "value": f"{_dec(pnl.get('win_rate_pct'), 1)}%",
         "sub": f"{pnl.get('win_count', 0)} 盈 / {pnl.get('loss_count', 0)} 亏"},
        {"label": "盈亏比", "value": _dec(pnl.get("profit_loss_ratio"), 2),
         "sub": "总盈利 / 总亏损"},
        {"label": "总盈利金额", "value": _fmt_money(pnl.get("gross_profit")),
         "color": POS_COLOR},
        {"label": "总亏损金额", "value": _fmt_money(pnl.get("gross_loss")),
         "color": NEG_COLOR},
        {"label": "最大单笔盈利", "value": _fmt_money(pnl.get("max_single_profit")),
         "color": POS_COLOR},
        {"label": "最大单笔亏损", "value": _fmt_money(pnl.get("max_single_loss")),
         "color": NEG_COLOR},
    ]
    _kpi_grid(cards)
    st.subheader("盈亏分布")
    fig = _pnl_distribution_figure(metrics)
    if fig:
        _plot(fig)
    else:
        st.info("暂无盈亏分布数据。")
    st.subheader("个股盈亏榜 Top10")
    winners, losers = _stock_rankings(metrics)
    left, right = st.columns(2)
    with left:
        fig_w = _ranking_figure(winners, "盈利榜 Top10", POS_COLOR)
        if fig_w:
            _plot(fig_w)
        else:
            st.caption("暂无盈利榜数据")
    with right:
        fig_l = _ranking_figure(losers, "亏损榜 Top10", NEG_COLOR)
        if fig_l:
            _plot(fig_l)
        else:
            st.caption("暂无亏损榜数据")


def render_behavior_profile(metrics: dict) -> None:
    beh = metrics.get("behavior") or {}
    style = beh.get("style") or {}
    tags = [t for t in (style.get("horizon"), style.get("focus"), style.get("aggressiveness")) if t]
    st.markdown('<div class="block-label">风格标签</div>', unsafe_allow_html=True)
    if tags:
        st.markdown(_chips(tags), unsafe_allow_html=True)
    else:
        st.caption("暂无风格标签")
    if style.get("summary"):
        st.caption(style["summary"])
    st.subheader("持仓周期分布")
    fig = _holding_figure(metrics)
    if fig:
        _plot(fig)
    else:
        st.info("暂无持仓周期数据。")
    st.subheader("月度交易活跃度")
    fig2 = _activity_figure(metrics)
    if fig2:
        _plot(fig2)
    else:
        st.info("暂无活跃度数据。")
    special = beh.get("special_ops") or {}
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("逆回购次数", special.get("reverse_repo", 0))
    with c2:
        st.metric("分红 / 利息入账次数", int(special.get("dividends", 0) or 0) + int(special.get("interest", 0) or 0))
    with c3:
        st.metric("打新记录", special.get("new_stock", 0))
    conc = _num(beh.get("top5_concentration_pct")) or 0
    maxpos = _num(beh.get("max_position_pct")) or 0
    st.markdown('<div class="block-label">仓位特征</div>', unsafe_allow_html=True)
    st.progress(min(conc / 100, 1.0), text=f"Top5 股票成交额占比：{conc:.1f}%")
    st.progress(min(maxpos / 100, 1.0), text=f"单票最大仓位：{maxpos:.1f}%")
    fav = beh.get("favorite_stocks") or []
    if fav:
        st.markdown('<div class="block-label">偏爱个股 Top10（按交易次数）</div>', unsafe_allow_html=True)
        fav_df = pd.DataFrame([{
            "名称": f.get("name", ""),
            "代码": f.get("code", ""),
            "交易次数": int(f.get("trades") or 0),
        } for f in fav])
        st.dataframe(fav_df, hide_index=True, height=min(360, 40 + 33 * len(fav_df)))


def _extract_report(analysis: dict) -> str:
    report = analysis.get("final_report")
    if isinstance(report, str):
        return report
    if isinstance(report, dict):
        for k in ("final_report", "report", "markdown", "content"):
            if isinstance(report.get(k), str):
                return report[k]
    if isinstance(analysis.get("report"), str):
        return analysis["report"]
    return ""


def render_ai_report(analysis: dict) -> None:
    analysis = analysis or {}
    degraded = bool(analysis.get("degraded"))
    if degraded:
        st.warning(
            "⚠️ AI 分析已降级："
            + str(analysis.get("degraded_reason") or "上游分析模块暂不可用")
            + "。以下为规则引擎兜底结果，指标区不受影响。"
        )
    tags = analysis.get("overall_tags") or []
    if tags:
        st.markdown('<div class="block-label">幽默标签</div>', unsafe_allow_html=True)
        st.markdown(_chips(tags), unsafe_allow_html=True)
    _disclaimer_box(analysis.get("disclaimer") or DISCLAIMER)
    report = _extract_report(analysis)
    if report:
        st.markdown(report)
    else:
        st.info("暂无综合报告内容。")
    analysts = analysis.get("analysts") or []
    if analysts:
        st.subheader("分析师点评")
        for a in analysts:
            if not isinstance(a, dict):
                continue
            name = _first(a, "name", "nickname", "analyst") or "分析师"
            role = _first(a, "role", "position", "title")
            title = f"{name} · {role}" if role else name
            with st.expander(title, expanded=False):
                tags_a = a.get("tags") or a.get("labels") or []
                if tags_a:
                    st.markdown(_chips(tags_a), unsafe_allow_html=True)
                comment = _first(a, "comment", "commentary", "opinion", "summary", "content")
                st.markdown(comment or "（暂无点评）")
    debate = analysis.get("debate_history") or []
    rounds = analysis.get("round_count") or 0
    if debate:
        with st.expander(f"辩论过程（{rounds} 轮）", expanded=False):
            for item in debate:
                if not isinstance(item, dict):
                    continue
                r = item.get("round", "—")
                sp = item.get("speaker", "")
                content = item.get("content", "")
                st.markdown(f"**第 {r} 轮 · {sp}**  \n{content}")


def history_label(rec: dict, highlight: bool = False) -> str:
    ts = str(rec.get("timestamp") or rec.get("id") or "")
    fname = str(rec.get("file_name") or "未知文件")
    if len(fname) > 42:
        fname = fname[:39] + "…"
    rpct_n = _num(rec.get("total_return_pct"))
    rpct_txt = f"{rpct_n:+.2f}%" if rpct_n is not None else "—"
    if rec.get("is_partial"):
        rpct_txt = "区间 " + rpct_txt
    tags = rec.get("overall_tags") or []
    tags_txt = " · ".join(str(t) for t in tags[:3]) or "无标签"
    label = f"{ts}\n{fname}\n{rpct_txt} ｜ {tags_txt}"
    return ("▸ " + label) if highlight else label


# =====================================================================
# 分析流水线（上传 → 解析 → 指标 → AI → 保存）
# =====================================================================

def _trades_to_rows(trades: list) -> list:
    """把契约 TradeRecord 列表转成展示用明细行（不包含合同编号等敏感字段）。"""
    rows = []
    for t in trades:
        if not isinstance(t, dict):
            try:
                t = vars(t)
            except TypeError:
                continue
        op = t.get("op_type")
        op_str = getattr(op, "value", None) or str(op)
        td = t.get("trade_date")
        if hasattr(td, "isoformat"):
            td = td.isoformat()
        rows.append({
            "date": str(td or ""),
            "code": str(t.get("code") or ""),
            "name": str(t.get("name") or ""),
            "op_type": op_str,
            "qty": t.get("qty"),
            "price": t.get("price"),
            "amount": t.get("amount"),
            "fee": t.get("fee"),
            "pnl": None,
            "holding_days": None,
        })
    return rows


def _normalize_metrics(metrics: dict) -> dict:
    """把指标引擎真实输出（A2 命名）适配为 UI 视图结构；mock/未知结构原样返回。"""
    if not isinstance(metrics, dict) or ("meta" not in metrics and "trading" not in metrics):
        return metrics
    out = dict(metrics)
    meta = dict(metrics.get("meta") or {})
    acct = dict(metrics.get("account") or {})
    trading = dict(metrics.get("trading") or {})
    pnl = dict(metrics.get("pnl") or {})
    beh = dict(metrics.get("behavior") or {})
    is_partial = bool(meta.get("is_partial"))
    source = str(acct.get("market_value_source") or "cost").lower()

    start = str(meta.get("start_date") or "")
    end = str(meta.get("end_date") or "")
    days = meta.get("calendar_days")
    if days is None and start and end:
        try:
            days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(start, "%Y-%m-%d")).days
        except ValueError:
            days = 0

    curve = []
    for c in pnl.get("equity_curve") or []:
        if not isinstance(c, dict):
            continue
        curve.append({
            "date": str(c.get("date") or str(c.get("month", "")) + "-末"),
            "equity": c.get("equity"),
            "drawdown_pct": _scaled_pct(c.get("drawdown")),
        })
    lb = pnl.get("stock_leaderboard") or {}

    def _rank(items: Any, key: str) -> list:
        out = []
        for it in items or []:
            if not isinstance(it, dict):
                continue
            out.append({"name": str(it.get("name") or ""), "code": str(it.get("code") or ""),
                        "pnl": it.get(key, it.get("total_pnl", it.get("realized_pnl", 0)))})
        return out

    dist_raw = beh.get("holding_period_distribution") or {}
    style_raw = beh.get("style") or {}
    maxpos = beh.get("max_position") or {}
    special = beh.get("special_operations") or {}

    def _cnt(x: Any) -> int:
        return int(x.get("count", 0)) if isinstance(x, dict) else 0

    out["is_partial"] = is_partial
    out["market_value_source"] = source
    out["period_start"] = start
    out["period_end"] = end
    out["account"] = _round_deep({
        "period_start": start,
        "period_end": end,
        "period_days": days or 0,
        "initial_capital": acct.get("initial_balance"),
        "final_capital": acct.get("ending_balance"),
        "net_transfer_in": acct.get("net_transfer_in"),
        "gross_deposit": acct.get("gross_deposit"),
        "gross_withdraw": acct.get("gross_withdraw"),
        "opening_asset_value": acct.get("opening_asset_value"),
        "total_return_pct": _num(acct.get("total_return_rate")),
        "annual_return_pct": _num(acct.get("annualized_return_rate")),
        "realized_pnl": acct.get("realized_pnl"),
        "total_cost": acct.get("total_cost"),
        "cost_ratio_pct": _scaled_pct(acct.get("total_cost_ratio")),
        "position_value": acct.get("holding_market_value")
        if acct.get("holding_market_value") is not None else acct.get("holding_cost_value"),
        "floating_pnl": acct.get("unrealized_pnl"),
        "max_drawdown_pct": _scaled_pct(pnl.get("max_drawdown")),
        "label": "区间收益" if is_partial else "总收益",
    })
    out["trades"] = _round_deep({
        "total_amount": trading.get("total_amount"),
        "total_count": trading.get("total_count"),
        "buy_count": trading.get("buy_count"),
        "buy_amount": trading.get("buy_amount"),
        "sell_count": trading.get("sell_count"),
        "sell_amount": trading.get("sell_amount"),
        "avg_daily_count": trading.get("daily_avg_count"),
        "avg_daily_amount": trading.get("daily_avg_amount"),
        "stock_count": trading.get("distinct_stock_count"),
        "position_count": trading.get("current_holding_count"),
        "avg_trade_amount": trading.get("avg_trade_amount"),
        "turnover_rate": trading.get("capital_turnover_rate"),
        "avg_holding_days": trading.get("avg_holding_period_days"),
    })
    out["pnl"] = _round_deep({
        "realized_pnl": pnl.get("realized_pnl"),
        "win_count": pnl.get("win_count"),
        "loss_count": pnl.get("loss_count"),
        "win_rate_pct": _scaled_pct(pnl.get("win_rate")),
        "gross_profit": pnl.get("total_profit"),
        "gross_loss": pnl.get("total_loss"),
        "profit_loss_ratio": pnl.get("profit_loss_ratio"),
        "max_single_profit": pnl.get("max_single_profit"),
        "max_single_loss": pnl.get("max_single_loss"),
        "double_count": pnl.get("double_count", 0),
        "halved_count": pnl.get("halved_count", 0),
        "monthly_pnl": [dict(x) for x in (pnl.get("monthly_pnl") or []) if isinstance(x, dict)],
        "equity_curve": curve,
        "top_winners": _rank(lb.get("top_profit"), "total_pnl"),
        "top_losers": _rank(lb.get("top_loss"), "total_pnl"),
    })
    out["behavior"] = _round_deep({
        "holding_days_dist": [
            {"bucket": "≤1天", "count": dist_raw.get("le_1d", 0)},
            {"bucket": "2–5天", "count": dist_raw.get("2_5d", 0)},
            {"bucket": "6–20天", "count": dist_raw.get("6_20d", 0)},
            {"bucket": ">20天", "count": dist_raw.get("gt_20d", 0)},
        ],
        "monthly_activity": [{"month": str(x.get("month", "")), "trades": int(x.get("total_count", 0))}
                             for x in (beh.get("monthly_activity") or []) if isinstance(x, dict)],
        "max_position_pct": _scaled_pct(maxpos.get("ratio")),
        "top5_concentration_pct": _scaled_pct(beh.get("top5_concentration")),
        "favorite_stocks": [{"code": str(x.get("code") or ""), "name": str(x.get("name") or ""),
                             "trades": int(x.get("count", 0))}
                            for x in (beh.get("favorite_stocks_top10") or []) if isinstance(x, dict)],
        "style": {
            "horizon": style_raw.get("holding_style"),
            "focus": style_raw.get("concentration"),
            "aggressiveness": style_raw.get("risk_style"),
            "summary": str(style_raw.get("label") or ""),
        },
        "special_ops": {
            "reverse_repo": _cnt(special.get("reverse_repo")),
            "dividends": _cnt(special.get("dividend")),
            "interest": _cnt(special.get("interest")),
            "new_stock": _cnt(special.get("ipo")),
        },
    })
    out.setdefault("trade_rows", [])
    return out


def _build_meta(file_name: str, metrics: dict, analysis: dict, demo: bool = False) -> dict:
    acct = metrics.get("account") or {}
    trd = metrics.get("trades") or {}
    return {
        "timestamp": datetime.now().strftime("%Y%m%d-%H%M%S"),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "file_name": file_name or "未命名文件",
        "is_partial": bool(metrics.get("is_partial")),
        "market_value_source": str(metrics.get("market_value_source") or "cost"),
        "return_label": acct.get("label") or ("区间收益" if metrics.get("is_partial") else "总收益"),
        "total_return_pct": acct.get("total_return_pct"),
        "overall_tags": [str(t) for t in (analysis.get("overall_tags") or [])],
        "degraded": bool(analysis.get("degraded")),
        "demo": demo,
        "stock_count": trd.get("stock_count"),
        "trade_count": trd.get("total_count"),
        "metrics": metrics,
        "analysis": analysis,
    }


def _slim_meta(meta: dict) -> dict:
    return {k: v for k, v in meta.items() if k not in ("metrics", "analysis")}


def run_pipeline(uploaded_bytes: bytes, file_name: str) -> dict:
    """上传 → 解析 → 指标 → AI 分析 → 保存历史 → 返回展示数据。

    任何上游模块缺失 / 失败都不阻塞：指标失败用 mock 展示，
    AI 失败仅降级 AI 区（degraded=True），并附中文提示。
    """
    notices: list = []
    suffix = Path(file_name).suffix.lower() or ".xlsx"
    tmp_path: Optional[str] = None
    try:
        tmp_dir = Path(__file__).resolve().parents[2] / ".tmp"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = str(tmp_dir / f"upload_{int(time.time() * 1000)}{suffix}")
        with open(tmp_path, "wb") as tf:
            tf.write(uploaded_bytes or b"")
        trades = None
        parse_missing = False
        try:
            from synalysis_crew.parser import parse_trades
            trades = parse_trades(tmp_path)
            if not isinstance(trades, list):
                raise TypeError("parse_trades 返回类型不符合契约（需 list[TradeRecord]）")
            trades = [t for t in trades if t is not None]
        except ModuleNotFoundError:
            parse_missing = True
            notices.append("解析模块未就绪，已改用内置演示数据。")
        except Exception as exc:
            notices.append(f"解析失败（{type(exc).__name__}: {exc}），已改用内置演示数据。")
        metrics = None
        if trades:
            try:
                from synalysis_crew.metrics import compute_metrics
                metrics = compute_metrics(trades)
                if not isinstance(metrics, dict):
                    raise TypeError("compute_metrics 返回类型不符合契约（需 dict）")
                metrics = _normalize_metrics(metrics)
                metrics["trade_rows"] = _trades_to_rows(trades)
            except Exception as exc:
                notices.append(f"指标模块未就绪或计算失败（{type(exc).__name__}: {exc}），已改用内置演示数据。")
        elif trades is not None:
            notices.append("未解析到有效交易记录（文件可能为空或格式不符），已改用内置演示数据。")
        if metrics is None:
            metrics = mock_metrics()

        if not trades:
            # 没有可分析的真实交易：解析模块缺失 → 完整演示；文件无效 → 降级兜底
            analysis = mock_analysis() if parse_missing else fallback_analysis("未能解析出有效交易记录", metrics)
        else:
            analyze_fn = None
            for mod in ("graph", "analyst", "llm"):
                try:
                    module = __import__(f"synalysis_crew.{mod}", fromlist=["analyze"])
                    analyze_fn = getattr(module, "analyze", None)
                    if analyze_fn is not None:
                        break
                except Exception:
                    analyze_fn = None
            if analyze_fn is None:
                notices.append("分析模块未就绪，AI 报告暂用降级演示内容（指标区不受影响）。")
                analysis = fallback_analysis("分析模块未就绪", metrics)
            else:
                try:
                    analysis = analyze_fn(trades, metrics, max_rounds=2)
                    if not isinstance(analysis, dict):
                        raise TypeError("analyze 返回类型不符合契约（需 dict）")
                except Exception as exc:
                    notices.append(f"AI 分析执行失败（{type(exc).__name__}: {exc}），已展示降级结果（指标区不受影响）。")
                    analysis = fallback_analysis(str(exc), metrics)

        meta = _build_meta(file_name, metrics, analysis)
        from synalysis_crew import storage
        analysis_id = storage.save_analysis(meta)
        return {
            "id": analysis_id,
            "meta": _slim_meta(meta),
            "metrics": metrics,
            "analysis": analysis,
            "notices": notices,
        }
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def load_demo() -> dict:
    """载入内置演示数据并保存为一条历史记录（用于离线预览全部页面）。"""
    metrics = mock_metrics()
    analysis = mock_analysis()
    meta = _build_meta("演示数据（内置 mock）", metrics, analysis, demo=True)
    from synalysis_crew import storage
    analysis_id = storage.save_analysis(meta)
    return {
        "id": analysis_id,
        "meta": _slim_meta(meta),
        "metrics": metrics,
        "analysis": analysis,
        "notices": ["当前展示的是内置演示数据：上游解析 / 指标 / AI 模块就绪后，上传真实交割单即可自动分析。"],
    }
