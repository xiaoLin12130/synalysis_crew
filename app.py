# -*- coding: utf-8 -*-
"""Synalysis 前端入口（Issue #4 / A4）。

运行：streamlit run app.py
上传交割单 → 解析 → 指标 → AI 分析 → 保存历史 → 展示；
上游模块未就绪时自动降级为内置演示数据，页面不报错。
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import streamlit as st  # noqa: E402

from synalysis_crew import storage, ui  # noqa: E402

st.set_page_config(
    page_title="Synalysis 交易分析",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)
ui.apply_theme()

ss = st.session_state
ss.setdefault("current", None)
ss.setdefault("notices", [])
ss.setdefault("processed", None)


def load_demo() -> None:
    result = ui.load_demo()
    ss.current = result
    ss.processed = None
    ss.notices = result.get("notices", [])


def new_analysis() -> None:
    ss.current = None
    ss.processed = None
    ss.notices = []


def open_history(record_id: str) -> None:
    data = storage.load_analysis(record_id)
    if not data:
        ss.notices = [f"历史记录 {record_id} 读取失败或已被删除。"]
        return
    metrics = data.get("metrics") or ui.mock_metrics()
    analysis = data.get("analysis") or ui.fallback_analysis("历史记录中缺少 AI 分析结果")
    ss.current = {
        "id": data.get("id") or record_id,
        "meta": data.get("meta") or {},
        "metrics": metrics,
        "analysis": analysis,
        "notices": [],
    }
    ss.processed = None
    ss.notices = []


# ---------------------------------------------------------------------
# 侧栏：新建分析 / 上传 / 演示数据 / 历史列表
# ---------------------------------------------------------------------
with st.sidebar:
    ui.render_sidebar_brand()
    if st.button("＋ 新建分析", key="btn_new", width="stretch"):
        new_analysis()
    uploaded = st.file_uploader(
        "上传交割单",
        type=["xlsx", "xls", "csv"],
        key="uploader",
        help="同花顺导出：xlsx / xls / csv，全程仅本地处理",
    )
    if uploaded is not None:
        fp = (getattr(uploaded, "file_id", None), uploaded.name, uploaded.size)
        if fp != ss.processed:
            with st.spinner("解析 → 指标 → AI 分析 → 保存历史 …"):
                try:
                    result = ui.run_pipeline(uploaded.getvalue(), uploaded.name)
                    ss.current = result
                    ss.processed = fp
                    ss.notices = result.get("notices", [])
                except Exception as exc:  # 顶层兜底：任何异常都不能让页面崩溃
                    ss.current = None
                    ss.processed = fp
                    ss.notices = [f"分析流程出现异常：{exc}"]
    st.divider()
    if st.button("载入演示数据（离线预览）", key="btn_demo", width="stretch"):
        load_demo()
    st.markdown("##### 历史分析")
    records = storage.list_analyses()
    if records:
        current_id = (ss.current or {}).get("id")
        with st.container(height=430, border=False):
            for rec in records:
                rid = rec.get("id", "")
                label = ui.history_label(rec, highlight=(rid == current_id))
                if st.button(label, key=f"hist_{rid}", width="stretch"):
                    open_history(rid)
    else:
        st.caption("暂无记录，上传交割单后自动保存。")


# ---------------------------------------------------------------------
# 主区：欢迎页 / 五个 Tab
# ---------------------------------------------------------------------
for notice in ss.notices:
    st.info(notice)

cur = ss.current
if cur is None:
    ui.render_welcome(load_demo)
else:
    meta = cur.get("meta") or {}
    metrics = cur.get("metrics") or ui.mock_metrics()
    analysis = cur.get("analysis") or ui.fallback_analysis("当前记录缺少 AI 分析结果")
    ui.render_header(meta, metrics)
    tab_overview, tab_trades, tab_pnl, tab_behavior, tab_ai = st.tabs(
        ["账户总览", "交易明细", "盈亏分析", "行为画像", "AI 报告"]
    )
    with tab_overview:
        ui.render_account_overview(metrics)
    with tab_trades:
        ui.render_trade_detail(metrics)
    with tab_pnl:
        ui.render_pnl_analysis(metrics)
    with tab_behavior:
        ui.render_behavior_profile(metrics)
    with tab_ai:
        ui.render_ai_report(analysis)
