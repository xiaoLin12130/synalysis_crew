"""指标计算引擎 v2.1 测试（docs/requirements-v2.md 1.0–1.6 + 数据字典）。

覆盖：
- 完整历史 / 中途开始（is_partial）两种场景；
- 完整交易 trades：闭环字段齐备、FIFO 配对（费用入成本/扣净额）、红股只摊薄不记入
  买入数量、分红/利息/逆回购/指定交易/转账一律不进 trades、期初持仓卖出只记
  unmatched_sell_amount；
- 胜率/盈亏比/平均持仓周期/持仓周期分布按完整交易统计（未清仓不计）；
- 收益率（1.0 v2.1 TWR）：逐日模拟、现金以余额为权威、持仓按最近成交价估值、
  期初持仓合成 1:1 跟踪（卖出不产生虚假收益）、出入金不影响收益率本身、
  return_curve 每月末累计 R（无记录月份沿用上一值补齐）；
- 最大回撤基于逐日 (1+R) 序列；账户级翻倍（v2.1：R ≥ +100% 独立事件）/腰斩
  （v2.2 递进式：floor 初始 1.0，新高重置，v ≤ floor×0.5 逐级计数）；
- 亏损榜 top_loss 升序（亏损最多在前）、top_profit 降序；
- akshare 最新价成功 / 失败按成本兜底（monkeypatch，不发网络请求）；
- 固定 JSON Schema（全英文 snake_case、可严格 JSON 序列化），_empty_result 含
  trades/return_curve/stocks 等新字段。
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from types import SimpleNamespace

import pytest

_SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

try:  # parser 已落地时使用真实契约，否则回退本地 stub
    from synalysis_crew.parser import TradeRecord, OpType
    from synalysis_crew.metrics import MetricsResult, compute_metrics
    import synalysis_crew.metrics as metrics_module

    PARSER_AVAILABLE = True

    def _op(name: str):
        return getattr(OpType, name)

except Exception:  # pragma: no cover - 仅在 parser 未落地时触发
    PARSER_AVAILABLE = False

    @dataclass
    class TradeRecord:
        """本地最小 stub（与契约字段一致）。"""

        code: str = ""
        name: str = ""
        op_type: str = "UNKNOWN"
        qty: float = 0.0
        price: float = 0.0
        amount: float = 0.0
        balance: float = 0.0
        fee: float = 0.0
        stamp_tax: float = 0.0
        commission: float = 0.0
        transfer_fee: float = 0.0
        contract_no: str = ""
        trade_date: object = None
        currency: str = "人民币"

    from synalysis_crew.metrics import MetricsResult, compute_metrics  # type: ignore
    import synalysis_crew.metrics as metrics_module  # type: ignore

    def _op(name: str) -> str:
        return name


def T(
    code: str,
    name: str,
    op: str,
    qty: float,
    price: float,
    amount: float,
    balance: float,
    trade_date: object,
    fee: float = 0.0,
    stamp_tax: float = 0.0,
    commission: float = 0.0,
    transfer_fee: float = 0.0,
) -> TradeRecord:
    """构造一条交割记录（amount 按 parser 契约为「成交金额」，balance 为交易后资金余额）。"""
    return TradeRecord(
        code=code,
        name=name,
        op_type=_op(op),
        qty=qty,
        price=price,
        amount=amount,
        balance=balance,
        fee=fee,
        stamp_tax=stamp_tax,
        commission=commission,
        transfer_fee=transfer_fee,
        trade_date=trade_date,
    )


@pytest.fixture()
def no_price_fetch(monkeypatch):
    """封死行情拉取：任何指标计算都按成本兜底，保证确定性与离线。"""
    monkeypatch.setattr(
        metrics_module,
        "_fetch_latest_prices",
        lambda codes, timeout=15.0: None,
    )
    return None


def _full_history_trades() -> list[TradeRecord]:
    """完整历史手算场景（费用为 0，数字均为精确值）。"""
    return [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 100000, date(2024, 1, 1)),
        T("A", "A股", "BUY", 100, 10, 1000, 99000, date(2024, 1, 2)),
        T("A", "A股", "SELL", 100, 25, 2500, 101500, date(2024, 1, 3)),
        T("B", "B股", "BUY", 100, 10, 1000, 100500, date(2024, 1, 4)),
        T("C", "C股", "BUY", 100, 10, 1000, 99500, date(2024, 1, 5)),
        T("B", "B股", "SELL", 100, 4, 400, 99900, date(2024, 1, 6)),
        T("C", "C股", "SELL", 100, 14, 1400, 101300, date(2024, 1, 12)),
        T("D", "D股", "BUY", 100, 10, 1000, 100300, date(2024, 2, 1)),
        T("D", "D股", "SELL", 100, 12, 1200, 101500, date(2024, 2, 15)),
        T("E", "E股", "BUY", 100, 20, 2000, 99500, date(2024, 3, 1)),
        T("E", "E股", "SELL", 100, 10, 1000, 100500, date(2024, 3, 20)),
        T("F", "F股", "BUY", 100, 5, 500, 100000, date(2024, 3, 21)),
        T("F", "F股", "SELL", 100, 6, 600, 100600, date(2024, 4, 25)),
    ]


def _deposit_basis_double_halved_trades() -> list[TradeRecord]:
    """A0=0（累计入金基准）场景：v 序列 [1.5, 0.7333, 1.7333, 1.3333]。

    手算：入金 10000（1 月）+ 5000（2 月），累计入金 15000；
    A +5000 / B -9000 / C +15000 / D -6000，期末资产 20000。
    """
    return [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("A", "A股", "BUY", 100, 50, 5000, 5000, date(2024, 1, 3)),
        T("A", "A股", "SELL", 100, 100, 10000, 15000, date(2024, 1, 5)),
        T("", "", "BANK_TO_SEC", 0, 0, 0, 20000, date(2024, 2, 1)),
        T("B", "B股", "BUY", 100, 100, 10000, 10000, date(2024, 2, 5)),
        T("B", "B股", "SELL", 100, 10, 1000, 11000, date(2024, 2, 10)),
        T("C", "C股", "BUY", 100, 50, 5000, 6000, date(2024, 3, 2)),
        T("C", "C股", "SELL", 100, 200, 20000, 26000, date(2024, 3, 10)),
        T("D", "D股", "BUY", 100, 100, 10000, 16000, date(2024, 4, 2)),
        T("D", "D股", "SELL", 100, 40, 4000, 20000, date(2024, 4, 10)),
    ]


def _opening_asset_basis_trades() -> list[TradeRecord]:
    """A0>0（期初资产基准）场景：期初持仓变现 4000，2 月入金 10000，3 月盈利 5000。

    v 序列 [1.0, 1.0, 2.25]：3 月 v >= 2*v_min=2.0 → 翻倍 1 次。
    """
    return [
        T("OLD", "老股", "SELL", 200, 20, 4000, 4000, date(2025, 1, 5)),
        T("", "", "BANK_TO_SEC", 0, 0, 0, 14000, date(2025, 2, 3)),
        T("N", "N股", "BUY", 100, 50, 5000, 9000, date(2025, 3, 2)),
        T("N", "N股", "SELL", 100, 100, 10000, 19000, date(2025, 3, 5)),
    ]


# ---------------------------------------------------------------------------
# 完整历史手算抽查（账户 / 交易统计）
# ---------------------------------------------------------------------------


def test_full_history_hand_check_account_and_trading(no_price_fetch):
    m = compute_metrics(_full_history_trades())

    assert m["meta"]["is_partial"] is False
    assert m["meta"]["start_date"] == "2024-01-01"
    assert m["meta"]["end_date"] == "2024-04-25"
    assert m["meta"]["calendar_days"] == 116
    assert m["meta"]["active_trading_days"] == 12

    a = m["account"]
    assert a["initial_balance"] == 0.0
    assert a["ending_balance"] == pytest.approx(100600.0, abs=0.01)
    assert a["net_transfer_in"] == pytest.approx(100000.0, abs=0.01)
    assert a["total_return_rate"] == pytest.approx(0.006, abs=1e-4)
    assert a["annualized_return_rate"] == pytest.approx(
        (1.006) ** (365 / 115) - 1, abs=1e-4
    )
    assert a["realized_pnl"] == pytest.approx(600.0, abs=0.01)
    assert a["total_cost"] == 0.0
    assert a["holding_market_value"] == 0.0
    assert a["market_value_source"] == "cost"

    t = m["trading"]
    assert t["total_amount"] == pytest.approx(13600.0, abs=0.01)
    assert t["total_count"] == 12
    assert t["buy_count"] == 6
    assert t["buy_amount"] == pytest.approx(6500.0, abs=0.01)
    assert t["sell_count"] == 6
    assert t["sell_amount"] == pytest.approx(7100.0, abs=0.01)
    assert t["daily_avg_count"] == pytest.approx(1.0, abs=1e-4)
    assert t["daily_avg_amount"] == pytest.approx(13600 / 12, abs=0.01)
    assert t["distinct_stock_count"] == 6
    assert t["current_holding_count"] == 0
    assert t["avg_trade_amount"] == pytest.approx(13600 / 12, abs=0.01)
    avg_balance = sum(
        [
            100000, 99000, 101500, 100500, 99500, 99900, 101300,
            100300, 101500, 99500, 100500, 100000, 100600,
        ]
    ) / 13
    assert t["capital_turnover_rate"] == pytest.approx(13600 / avg_balance, abs=0.01)
    # 平均持仓周期按完整交易：A 2 / B 3 / C 8 / D 15 / E 20 / F 36 天 → 14 天
    assert t["avg_holding_period_days"] == pytest.approx(14.0, abs=0.01)


def test_full_history_hand_check_pnl_behavior_and_trades(no_price_fetch):
    m = compute_metrics(_full_history_trades())

    # C 盈亏分析（按完整交易：A +1500，B -600，C +400，D +200，E -1000，F +100）
    p = m["pnl"]
    assert p["realized_pnl"] == pytest.approx(600.0, abs=0.01)
    assert p["win_count"] == 4
    assert p["loss_count"] == 2
    assert p["win_rate"] == pytest.approx(4 / 6, abs=1e-4)
    assert p["total_profit"] == pytest.approx(2200.0, abs=0.01)
    assert p["total_loss"] == pytest.approx(1600.0, abs=0.01)
    assert p["profit_loss_ratio"] == pytest.approx(2200 / 1600, abs=1e-4)
    assert p["max_single_profit"] == pytest.approx(1500.0, abs=0.01)
    assert p["max_single_loss"] == pytest.approx(-1000.0, abs=0.01)
    # v2 账户级：v = [1.013, 1.015, 1.005, 1.006]，无翻倍/腰斩事件
    assert p["double_count"] == 0
    assert p["halved_count"] == 0
    assert p["unmatched_sell_amount"] == 0.0
    assert p["monthly_pnl"] == [
        {"month": "2024-01", "pnl": 1300.0},
        {"month": "2024-02", "pnl": 200.0},
        {"month": "2024-03", "pnl": -1000.0},
        {"month": "2024-04", "pnl": 100.0},
    ]
    # equity_curve 保留原始净值；收益率曲线（A0=0 → 累计入金基准）
    assert [pt["equity"] for pt in p["equity_curve"]] == pytest.approx(
        [101300.0, 101500.0, 100500.0, 100600.0], abs=0.01
    )
    assert p["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-12", "return_rate": 0.013},
        {"month": "2024-02", "date": "2024-02-15", "return_rate": 0.015},
        {"month": "2024-03", "date": "2024-03-21", "return_rate": 0.005},
        {"month": "2024-04", "date": "2024-04-25", "return_rate": 0.006},
    ]
    # 最大回撤基于 (1+R)：峰值 1.015 → (1.015-1.005)/1.015
    assert p["max_drawdown"] == pytest.approx(1000 / 101500, abs=1e-4)
    assert p["stock_leaderboard"]["top_profit"][0]["code"] == "A"
    assert p["stock_leaderboard"]["top_profit"][0]["total_pnl"] == pytest.approx(
        1500.0, abs=0.01
    )
    assert p["stock_leaderboard"]["top_loss"][0]["code"] == "E"
    assert p["stock_leaderboard"]["top_loss"][0]["total_pnl"] == pytest.approx(
        -1000.0, abs=0.01
    )

    # 完整交易：6 个闭环，字段齐备、状态 closed、红股/特殊操作不进 trades
    trades = m["trades"]
    assert len(trades) == 6
    assert trades[0] == {
        "code": "A",
        "name": "A股",
        "buy_qty": 100.0,
        "buy_amount": 1000.0,
        "sell_qty": 100.0,
        "sell_amount": 2500.0,
        "pnl": 1500.0,
        "holding_days": 2,
        "start_date": "2024-01-02",
        "end_date": "2024-01-03",
        "status": "closed",
    }
    assert [(t["code"], t["pnl"], t["holding_days"]) for t in trades] == [
        ("A", 1500.0, 2),
        ("B", -600.0, 3),
        ("C", 400.0, 8),
        ("D", 200.0, 15),
        ("E", -1000.0, 20),
        ("F", 100.0, 36),
    ]
    assert all(t["status"] == "closed" for t in trades)
    assert all(set(t) == {
        "code", "name", "buy_qty", "buy_amount", "sell_qty", "sell_amount",
        "pnl", "holding_days", "start_date", "end_date", "status",
    } for t in trades)

    # D 行为画像（持仓周期按完整交易：A 2 / B 3 / C 8 / D 15 / E 20 / F 36 天）
    b = m["behavior"]
    assert b["holding_period_distribution"] == {
        "le_1d": 0,
        "2_5d": 2,
        "6_20d": 3,
        "gt_20d": 1,
    }
    assert b["monthly_activity"] == [
        {"month": "2024-01", "total_count": 6, "buy_count": 3, "sell_count": 3},
        {"month": "2024-02", "total_count": 2, "buy_count": 1, "sell_count": 1},
        {"month": "2024-03", "total_count": 3, "buy_count": 2, "sell_count": 1},
        {"month": "2024-04", "total_count": 1, "buy_count": 0, "sell_count": 1},
    ]
    assert b["max_position"]["ratio"] == pytest.approx(2000 / 101500, abs=1e-4)
    assert b["max_position"]["code"] == "E"
    assert b["max_position"]["date"] == "2024-03-01"
    assert b["top5_concentration"] == pytest.approx(12500 / 13600, abs=1e-4)
    assert b["favorite_stocks_top10"][0]["code"] == "A"
    assert b["favorite_stocks_top10"][0]["count"] == 2
    assert b["style"]["label"] == "波段·集中·均衡"


# ---------------------------------------------------------------------------
# FIFO 与费用口径（完整交易维度）
# ---------------------------------------------------------------------------


def test_fifo_fees_in_cost_and_net_proceeds(no_price_fetch):
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("X", "X股", "BUY", 100, 10, 1000, 8990, date(2024, 1, 2), fee=10, commission=10),
        T("X", "X股", "BUY", 100, 12, 1200, 7780, date(2024, 1, 4), fee=10, commission=10),
        T("X", "X股", "SELL", 50, 15, 750, 8525, date(2024, 1, 5), fee=5),
        T("X", "X股", "SELL", 150, 15, 2250, 10765, date(2024, 1, 10), fee=10),
    ]
    m = compute_metrics(trades)

    # 买入费用入成本：lot1 1010、lot2 1210；卖出费用扣净额
    # 卖 1：745 - 505 = +240；卖 2：2240 - (505 + 1210) = +525；闭环合计 +765
    assert m["pnl"]["realized_pnl"] == pytest.approx(765.0, abs=0.01)
    # v2 按完整交易统计：X 一次闭环 → 1 胜 0 负
    assert m["pnl"]["win_count"] == 1
    assert m["pnl"]["loss_count"] == 0
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["pnl"]["total_profit"] == pytest.approx(765.0, abs=0.01)
    assert m["pnl"]["profit_loss_ratio"] is None
    assert m["pnl"]["max_single_profit"] == pytest.approx(765.0, abs=0.01)
    assert m["account"]["total_cost"] == pytest.approx(35.0, abs=0.01)  # 10+10+5+10
    # v2.1 TWR：入金与首买同日（1/2）→ 起始日资产为 0 跳过；
    # R = 10765 / 9990 − 1 ≈ 0.0776（买入费用计入首日端资产）
    assert m["account"]["total_return_rate"] == pytest.approx(10765 / 9990 - 1, abs=1e-4)
    assert m["trading"]["total_amount"] == pytest.approx(5200.0, abs=0.01)

    # 闭环交易：首买 1/2 → 清仓 1/10（含首尾 9 天）
    assert m["trades"] == [
        {
            "code": "X",
            "name": "X股",
            "buy_qty": 200.0,
            "buy_amount": 2220.0,
            "sell_qty": 200.0,
            "sell_amount": 2985.0,
            "pnl": 765.0,
            "holding_days": 9,
            "start_date": "2024-01-02",
            "end_date": "2024-01-10",
            "status": "closed",
        }
    ]
    assert m["trading"]["avg_holding_period_days"] == pytest.approx(9.0, abs=0.01)
    assert m["behavior"]["holding_period_distribution"] == {
        "le_1d": 0,
        "2_5d": 0,
        "6_20d": 1,
        "gt_20d": 0,
    }
    # 账户级 v = 1.0765，无翻倍/腰斩
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


def test_fifo_partial_sell_no_completed_trade(no_price_fetch):
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("Y", "Y股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("Y", "Y股", "BUY", 100, 20, 2000, 7000, date(2024, 1, 4)),
        T("Y", "Y股", "SELL", 150, 15, 2250, 9250, date(2024, 1, 10)),
    ]
    m = compute_metrics(trades)
    # FIFO：先匹配 100@10（成本 1000），再匹配 50@20（成本 1000）→ 已实现 250
    assert m["pnl"]["realized_pnl"] == pytest.approx(250.0, abs=0.01)
    assert m["account"]["holding_cost_value"] == pytest.approx(1000.0, abs=0.01)
    assert m["trading"]["current_holding_count"] == 1
    # 未清仓：不进完整交易，胜率/持仓周期/分布不计
    assert m["trades"] == []
    assert m["pnl"]["win_count"] == 0
    assert m["pnl"]["loss_count"] == 0
    assert m["pnl"]["win_rate"] is None
    assert m["trading"]["avg_holding_period_days"] is None
    assert m["behavior"]["holding_period_distribution"] == {
        "le_1d": 0, "2_5d": 0, "6_20d": 0, "gt_20d": 0,
    }


# ---------------------------------------------------------------------------
# 中途开始（is_partial）两种场景
# ---------------------------------------------------------------------------


def test_mid_history_with_initial_cash_is_partial(no_price_fetch):
    trades = [
        T("A", "A股", "BUY", 100, 10, 1000, 5000, date(2024, 1, 2), fee=10, commission=10),
        T("", "", "BANK_TO_SEC", 0, 0, 0, 25000, date(2024, 1, 5)),
        T("A", "A股", "SELL", 100, 15, 1500, 26495, date(2024, 1, 8), fee=5),
    ]
    m = compute_metrics(trades)
    assert m["meta"]["is_partial"] is True
    assert m["account"]["initial_balance"] == pytest.approx(6010.0, abs=0.01)
    assert m["account"]["net_transfer_in"] == pytest.approx(20000.0, abs=0.01)
    assert m["account"]["gross_deposit"] == pytest.approx(20000.0, abs=0.01)
    assert m["account"]["gross_withdraw"] == pytest.approx(0.0, abs=0.01)
    assert m["account"]["opening_asset_value"] == pytest.approx(6010.0, abs=0.01)
    assert m["account"]["ending_balance"] == pytest.approx(26495.0, abs=0.01)
    # v2.1 主口径（TWR）：(6000/6010) × (26495/26000) − 1 ≈ 0.0173
    assert m["account"]["total_return_rate"] == pytest.approx(
        (6000 / 6010) * (26495 / 26000) - 1, abs=1e-4
    )
    # 对照口径（期初资产基准简单收益率）：(26495 - 6010 - 20000) / 6010
    assert m["account"]["total_return_rate_net"] == pytest.approx(
        485 / 6010, abs=1e-4
    )
    assert m["account"]["realized_pnl"] == pytest.approx(485.0, abs=0.01)
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["account"]["total_cost"] == pytest.approx(15.0, abs=0.01)
    # 完整交易闭环：买入成本 1010（含费）、卖出净额 1495、周期盈亏 485
    assert m["trades"] == [
        {
            "code": "A",
            "name": "A股",
            "buy_qty": 100.0,
            "buy_amount": 1010.0,
            "sell_qty": 100.0,
            "sell_amount": 1495.0,
            "pnl": 485.0,
            "holding_days": 7,
            "start_date": "2024-01-02",
            "end_date": "2024-01-08",
            "status": "closed",
        }
    ]
    # 收益率曲线（v2.1 TWR）：月末累计 R = 0.0173
    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-08", "return_rate": 0.0173},
    ]
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


def test_mid_history_with_opening_position_is_partial(no_price_fetch):
    # 首笔是期初持仓的卖出（无法配对）：pnl 中性，只记 unmatched_sell_amount
    trades = [
        T("OLD", "老股", "SELL", 200, 20, 4000, 4000, date(2025, 1, 5)),
        T("OLD", "老股", "BUY", 100, 10, 1000, 3000, date(2025, 1, 6)),
        T("OLD", "老股", "SELL", 100, 12, 1200, 4200, date(2025, 1, 8)),
    ]
    m = compute_metrics(trades)
    assert m["meta"]["is_partial"] is True
    assert m["account"]["initial_balance"] == 0.0
    assert m["pnl"]["unmatched_sell_amount"] == pytest.approx(4000.0, abs=0.01)
    assert m["pnl"]["realized_pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["pnl"]["win_count"] == 1  # 只有配对的卖出计入完整交易
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    # 完整交易只含配对闭环（期初持仓卖出不进 trades）
    assert m["trades"] == [
        {
            "code": "OLD",
            "name": "老股",
            "buy_qty": 100.0,
            "buy_amount": 1000.0,
            "sell_qty": 100.0,
            "sell_amount": 1200.0,
            "pnl": 200.0,
            "holding_days": 3,
            "start_date": "2025-01-06",
            "end_date": "2025-01-08",
            "status": "closed",
        }
    ]
    # 期初资产基准（含期初持仓变现估值 4000）：(4200 - 4000) / 4000 = 5%
    assert m["account"]["opening_asset_value"] == pytest.approx(4000.0, abs=0.01)
    assert m["account"]["total_return_rate"] == pytest.approx(0.05, abs=1e-4)
    # v2.1 对照口径 = 期初资产基准简单收益率（A0 = 4000）同样为 5%
    assert m["account"]["total_return_rate_net"] == pytest.approx(0.05, abs=1e-4)
    # 首日即期初持仓卖出：合成持仓 1:1 扣减 → r = 0，不产生虚假收益
    assert m["pnl"]["return_curve"] == [
        {"month": "2025-01", "date": "2025-01-08", "return_rate": 0.05},
    ]


def test_sell_exceeding_position_marks_partial(no_price_fetch):
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("K", "K股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("K", "K股", "SELL", 150, 12, 1800, 10800, date(2024, 1, 3)),
    ]
    m = compute_metrics(trades)
    assert m["meta"]["is_partial"] is True
    # 配对 100 股：1800 * 100/150 - 1000 = 200；多余 50 股为期初持仓卖出
    assert m["pnl"]["realized_pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["pnl"]["unmatched_sell_amount"] == pytest.approx(600.0, abs=0.01)
    assert m["trading"]["current_holding_count"] == 0
    # v2.1 期初持仓合成：A0 = 期初资金 0 + 未配对卖出变现 600；
    # 首日入金 r=0、买入日 r=0，卖出日 (10800 − 10600)/10600 = 200/10600
    assert m["account"]["opening_asset_value"] == pytest.approx(600.0, abs=0.01)
    assert m["account"]["total_return_rate"] == pytest.approx(
        round(200 / 10600, 4), abs=1e-6
    )
    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-03", "return_rate": 0.0189},
    ]
    # 配对部分构成一个完整闭环（卖出数量只记配对部分）
    assert m["trades"] == [
        {
            "code": "K",
            "name": "K股",
            "buy_qty": 100.0,
            "buy_amount": 1000.0,
            "sell_qty": 100.0,
            "sell_amount": 1200.0,
            "pnl": 200.0,
            "holding_days": 2,
            "start_date": "2024-01-02",
            "end_date": "2024-01-03",
            "status": "closed",
        }
    ]


# ---------------------------------------------------------------------------
# 红股 / 多周期 / 特殊操作（完整交易剔除）
# ---------------------------------------------------------------------------


def test_bonus_share_dilutes_cost_and_trade_uses_buy_qty_only(no_price_fetch):
    # 全清仓闭环：买 100（成本 1000）+ 红股 50（零成本摊薄）+ 卖 150
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("G", "G股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("G", "G股", "BONUS_SHARE", 50, 0, 0, 9000, date(2024, 3, 1)),
        T("G", "G股", "SELL", 150, 15, 2250, 11250, date(2024, 5, 1)),
    ]
    m = compute_metrics(trades)
    assert m["pnl"]["realized_pnl"] == pytest.approx(1250.0, abs=0.01)
    assert m["account"]["holding_cost_value"] == 0.0
    assert m["trading"]["current_holding_count"] == 0
    assert m["pnl"]["win_count"] == 1
    # 红股不进 trades：buy_qty 只记实际买入 100，卖出 150（含红股）
    assert m["trades"] == [
        {
            "code": "G",
            "name": "G股",
            "buy_qty": 100.0,
            "buy_amount": 1000.0,
            "sell_qty": 150.0,
            "sell_amount": 2250.0,
            "pnl": 1250.0,
            "holding_days": 121,
            "start_date": "2024-01-02",
            "end_date": "2024-05-01",
            "status": "closed",
        }
    ]
    assert m["behavior"]["holding_period_distribution"]["gt_20d"] == 1
    assert m["behavior"]["special_operations"]["bonus_share"] == {
        "count": 1, "qty": 50.0,
    }
    assert m["trading"]["avg_holding_period_days"] == pytest.approx(121.0, abs=0.01)


def test_bonus_share_partial_sell_not_closed(no_price_fetch):
    # 买 100 + 红股 50 → 150 股；只卖 120 → 未清仓，不计胜率/持仓周期
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("G", "G股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("G", "G股", "BONUS_SHARE", 50, 0, 0, 9000, date(2024, 3, 1)),
        T("G", "G股", "SELL", 120, 15, 1800, 10800, date(2024, 5, 1)),
    ]
    m = compute_metrics(trades)
    # 已实现 = 1800 - 1000*120/150 = 1000；剩余 30 股成本 200
    assert m["pnl"]["realized_pnl"] == pytest.approx(1000.0, abs=0.01)
    assert m["account"]["holding_cost_value"] == pytest.approx(200.0, abs=0.01)
    assert m["trading"]["current_holding_count"] == 1
    assert m["trades"] == []
    assert m["pnl"]["win_count"] == 0
    assert m["trading"]["avg_holding_period_days"] is None
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


def test_multi_cycle_closed_trades(no_price_fetch):
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("M", "M股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("M", "M股", "SELL", 100, 25, 2500, 11500, date(2024, 1, 3)),
        T("M", "M股", "BUY", 100, 10, 1000, 10500, date(2024, 1, 4)),
        T("M", "M股", "SELL", 100, 26, 2600, 13100, date(2024, 1, 5)),
    ]
    m = compute_metrics(trades)
    # 两个完整周期：+150% 与 +160%（个股维度），账户级 v=1.31 无翻倍
    assert len(m["trades"]) == 2
    assert [(t["pnl"], t["holding_days"]) for t in m["trades"]] == [
        (1500.0, 2), (1600.0, 2),
    ]
    assert m["pnl"]["realized_pnl"] == pytest.approx(3100.0, abs=0.01)
    assert m["pnl"]["win_count"] == 2
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert m["behavior"]["holding_period_distribution"]["2_5d"] == 2
    assert m["trading"]["avg_holding_period_days"] == pytest.approx(2.0, abs=0.01)


def test_special_operations_excluded_from_trades_and_stats(no_price_fetch):
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("131810", "R-001", "REPO", 40, 2.525, 4000, 5999.9, date(2024, 1, 3), fee=0.1),
        T("", "", "DIVIDEND", 0, 0, 0, 6049.9, date(2024, 1, 4)),
        T("", "", "INTEREST", 0, 0, 0, 6051.1, date(2024, 1, 5)),
        T("", "", "DESIGNATED_TRADE", 0, 0, 0, 6051.1, date(2024, 1, 6)),
        T("H", "H股", "BUY", 100, 10, 1000, 5051.1, date(2024, 1, 7)),
        T("", "", "DIVIDEND_DIFF", 0, 0, 0, 5050.5, date(2024, 1, 8)),
        T("H", "H股", "SELL", 100, 12, 1200, 6250.5, date(2024, 1, 9)),
    ]
    m = compute_metrics(trades)
    sp = m["behavior"]["special_operations"]
    assert sp["reverse_repo"] == {"count": 1, "amount": pytest.approx(4000.1, abs=0.01)}
    assert sp["dividend"]["count"] == 2
    assert sp["dividend"]["amount"] == pytest.approx(49.4, abs=0.01)  # 50 - 0.6
    assert sp["interest"] == {"count": 1, "amount": pytest.approx(1.2, abs=0.01)}
    assert sp["other"]["count"] == 1
    assert sp["ipo"] == {"count": 0, "amount": 0.0}
    # 逆回购/分红/利息/指定交易/转账不进入股票成交统计
    assert m["trading"]["total_count"] == 2
    assert m["trading"]["total_amount"] == pytest.approx(2200.0, abs=0.01)
    assert m["trading"]["distinct_stock_count"] == 1
    assert m["pnl"]["realized_pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["account"]["ending_balance"] == pytest.approx(6250.5, abs=0.01)
    assert m["account"]["total_cost"] == pytest.approx(0.1, abs=0.01)
    # 完整交易只含 H 的闭环，特殊操作一行都不进 trades
    assert len(m["trades"]) == 1
    assert m["trades"][0]["code"] == "H"
    assert m["trades"][0]["pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["trades"][0]["holding_days"] == 3
    # v2.1 TWR：逆回购本金 4000 按 1:1 应收款跟踪（价值中性，仍属资产），
    # 仅费用/分红/利息/买卖盈亏计收益：R = 10250.5 / 10000 − 1 = 0.0251
    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-09", "return_rate": 0.0251},
    ]


# ---------------------------------------------------------------------------
# 收益率曲线 / 账户级翻倍腰斩（v2.1 1.0 / v2.2 1.4 TWR 逐日模拟）
# ---------------------------------------------------------------------------


def test_return_curve_twr_with_transfer_day(no_price_fetch):
    """A0=0 完整历史 + 中途转账日：v2.1 逐日 TWR 手算。

    逐日 v 序列：[1.0, 1.5, 1.5, 1.5, 0.825, 0.825, 1.95, 1.95, 1.5]；
    2/1 转账 5000（余额 15000→20000）日 r = (20000−5000−15000)/15000 = 0，
    出入金不产生收益；最终 R = 0.5；峰值 1.95 < 2 无翻倍，
    最低 0.825 > 0.75(=0.5×1.5) 无腰斩；最大回撤 (1.5−0.825)/1.5 = 0.45。
    """
    m = compute_metrics(_deposit_basis_double_halved_trades())
    assert m["meta"]["is_partial"] is False
    assert m["account"]["opening_asset_value"] == 0.0

    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-05", "return_rate": 0.5},
        {"month": "2024-02", "date": "2024-02-10", "return_rate": -0.175},
        {"month": "2024-03", "date": "2024-03-10", "return_rate": 0.95},
        {"month": "2024-04", "date": "2024-04-10", "return_rate": 0.5},
    ]
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert m["pnl"]["max_drawdown"] == pytest.approx((1.5 - 0.825) / 1.5, abs=1e-4)
    assert m["account"]["total_return_rate"] == pytest.approx(0.5, abs=1e-4)
    # 对照口径：期初资产基准简单收益率 = (20000 − 15000) / 15000
    assert m["account"]["total_return_rate_net"] == pytest.approx(1 / 3, abs=1e-4)
    # 完整交易与胜率/盈亏比
    assert [(t["code"], t["pnl"], t["holding_days"]) for t in m["trades"]] == [
        ("A", 5000.0, 3),
        ("B", -9000.0, 6),
        ("C", 15000.0, 9),
        ("D", -6000.0, 9),
    ]
    assert m["pnl"]["win_count"] == 2
    assert m["pnl"]["loss_count"] == 2
    assert m["pnl"]["win_rate"] == pytest.approx(0.5, abs=1e-4)
    assert m["pnl"]["total_profit"] == pytest.approx(20000.0, abs=0.01)
    assert m["pnl"]["total_loss"] == pytest.approx(15000.0, abs=0.01)
    assert m["pnl"]["profit_loss_ratio"] == pytest.approx(4 / 3, abs=1e-4)
    assert m["pnl"]["max_single_profit"] == pytest.approx(15000.0, abs=0.01)
    assert m["pnl"]["max_single_loss"] == pytest.approx(-9000.0, abs=0.01)
    assert m["trading"]["avg_holding_period_days"] == pytest.approx(6.75, abs=0.01)
    assert m["pnl"]["monthly_pnl"] == [
        {"month": "2024-01", "pnl": 5000.0},
        {"month": "2024-02", "pnl": -9000.0},
        {"month": "2024-03", "pnl": 15000.0},
        {"month": "2024-04", "pnl": -6000.0},
    ]


def test_return_curve_twr_opening_position_synthetic(no_price_fetch):
    """A0>0 期初持仓合成：首日卖出期初持仓 r=0，合成持仓 1:1 不产生虚假收益。

    逐日：1/5 卖期初 200 股（A0=4000 合成，r=0）→ 2/3 入金 10000（r=0）→
    3/2 买入（r=0）→ 3/5 卖出（r=5000/14000）；R = 3/7 ≈ 0.3571。
    """
    m = compute_metrics(_opening_asset_basis_trades())
    assert m["meta"]["is_partial"] is True
    assert m["account"]["opening_asset_value"] == pytest.approx(4000.0, abs=0.01)
    assert m["pnl"]["unmatched_sell_amount"] == pytest.approx(4000.0, abs=0.01)
    assert m["pnl"]["return_curve"] == [
        {"month": "2025-01", "date": "2025-01-05", "return_rate": 0.0},
        {"month": "2025-02", "date": "2025-02-03", "return_rate": 0.0},
        {"month": "2025-03", "date": "2025-03-05", "return_rate": 0.3571},
    ]
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert m["pnl"]["max_drawdown"] == 0.0
    assert m["account"]["total_return_rate"] == pytest.approx(5 / 14, abs=1e-4)
    # 对照口径（期初资产基准简单收益率）：(19000 − 4000 − 10000) / 4000 = 1.25
    assert m["account"]["total_return_rate_net"] == pytest.approx(1.25, abs=1e-4)
    assert m["trades"] == [
        {
            "code": "N",
            "name": "N股",
            "buy_qty": 100.0,
            "buy_amount": 5000.0,
            "sell_qty": 100.0,
            "sell_amount": 10000.0,
            "pnl": 5000.0,
            "holding_days": 4,
            "start_date": "2025-03-02",
            "end_date": "2025-03-05",
            "status": "closed",
        }
    ]


def test_return_curve_fills_months_without_records(no_price_fetch):
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("A", "A股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("A", "A股", "SELL", 100, 12, 1200, 10200, date(2024, 1, 3)),
        T("B", "B股", "BUY", 100, 10, 1000, 9200, date(2024, 4, 1)),
    ]
    m = compute_metrics(trades)
    # 2/3 月无记录：沿用 1 月末余额/持仓成本，快照日为月末最后一天
    assert [pt["month"] for pt in m["pnl"]["return_curve"]] == [
        "2024-01", "2024-02", "2024-03", "2024-04",
    ]
    assert m["pnl"]["return_curve"][1] == {
        "month": "2024-02", "date": "2024-02-29", "return_rate": 0.02,
    }
    assert m["pnl"]["return_curve"][2] == {
        "month": "2024-03", "date": "2024-03-31", "return_rate": 0.02,
    }
    assert m["pnl"]["return_curve"][0]["date"] == "2024-01-03"
    assert m["pnl"]["return_curve"][3]["date"] == "2024-04-01"
    assert len(m["pnl"]["equity_curve"]) == 4


def test_twr_transfers_do_not_affect_return(no_price_fetch):
    """v2.1：出入金只影响 r_d 分子（转账日收益率为 0），
    等额同日出入金对 TWR 无影响。"""
    base = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("A", "A股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 3)),
        T("A", "A股", "SELL", 100, 12, 1200, 10200, date(2024, 1, 4)),
    ]
    with_roundtrip = base + [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 110200, date(2024, 1, 5)),
        T("", "", "SEC_TO_BANK", 0, 0, 0, 10200, date(2024, 1, 5)),
    ]
    m1 = compute_metrics(base)
    m2 = compute_metrics(with_roundtrip)
    # 两个场景 TWR 完全一致：入金 10 万 + 同日出金 10 万，r_d = 0
    assert m1["account"]["total_return_rate"] == pytest.approx(0.02, abs=1e-6)
    assert m2["account"]["total_return_rate"] == pytest.approx(0.02, abs=1e-6)
    assert m2["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-05", "return_rate": 0.02},
    ]
    # 出入金字段照常累计（对照口径简单收益率会不同，但主口径 TWR 不变）
    assert m2["account"]["net_transfer_in"] == pytest.approx(10000.0, abs=0.01)
    assert m2["account"]["gross_deposit"] == pytest.approx(110000.0, abs=0.01)
    assert m2["account"]["gross_withdraw"] == pytest.approx(100000.0, abs=0.01)


def test_twr_double_and_halved_events(no_price_fetch):
    """v2.1 1.4：翻倍 = R 从 < 100% 升到 ≥ 100% 的独立事件；
    腰斩 = v2.2 递进式（floor 初始 1.0，新高重置，v ≤ floor×0.5 逐级计数）。

    手算逐日 v：1.0 → 2.0（翻倍#1）→ 1.75 → 2.55（翻倍#2，R 0.75→1.55）
    → 1.05（腰斩#1，≤ 0.5×2.55=1.275，floor 降至 1.05）→ 1.3 → 1.5
    （回升超过当前 floor，基线重置为 1.5）→ 1.1（> 0.5×1.5=0.75，不再计数）；
    最终 R = 0.1；最大回撤 = (2.55 − 1.05) / 2.55。
    """
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("A", "A股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 3)),
        T("A", "A股", "SELL", 100, 110, 11000, 20000, date(2024, 1, 4)),
        T("B", "B股", "BUY", 100, 50, 5000, 15000, date(2024, 1, 5)),
        T("B", "B股", "SELL", 100, 25, 2500, 17500, date(2024, 1, 6)),
        T("C", "C股", "BUY", 100, 80, 8000, 9500, date(2024, 1, 7)),
        T("C", "C股", "SELL", 100, 160, 16000, 25500, date(2024, 1, 8)),
        T("D", "D股", "BUY", 100, 200, 20000, 5500, date(2024, 1, 9)),
        T("D", "D股", "SELL", 100, 50, 5000, 10500, date(2024, 1, 10)),
        T("E", "E股", "BUY", 100, 30, 3000, 7500, date(2024, 1, 11)),
        T("E", "E股", "SELL", 100, 55, 5500, 13000, date(2024, 1, 12)),
        T("G", "G股", "BUY", 100, 60, 6000, 7000, date(2024, 1, 15)),
        T("G", "G股", "SELL", 100, 80, 8000, 15000, date(2024, 1, 16)),
        T("H", "H股", "BUY", 100, 80, 8000, 7000, date(2024, 1, 17)),
        T("H", "H股", "SELL", 100, 40, 4000, 11000, date(2024, 1, 18)),
    ]
    m = compute_metrics(trades)
    assert m["pnl"]["double_count"] == 2
    assert m["pnl"]["halved_count"] == 1
    assert m["account"]["total_return_rate"] == pytest.approx(0.1, abs=1e-6)
    assert m["pnl"]["max_drawdown"] == pytest.approx((2.55 - 1.05) / 2.55, abs=1e-4)
    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-18", "return_rate": 0.1},
    ]


def test_count_doublings_hand_sequences():
    """翻倍保持 v2.1：R ≥ +100% 独立事件（v = 1+R 从 < 2.0 升到 ≥ 2.0 计 1 次）。"""
    assert metrics_module._count_doublings([1.0, 1.9, 2.0, 2.1, 1.9, 2.0]) == 2
    assert metrics_module._count_doublings([1.0, 2.0, 1.5, 2.0]) == 2
    assert metrics_module._count_doublings([1.5, 1.9]) == 0
    assert metrics_module._count_doublings([]) == 0


def test_count_halvings_progressive_consecutive_decline():
    """v2.2 递进式腰斩：连续下跌 1 → 0.5 → 0.25 → 0.125 逐级计 3 次。"""
    assert metrics_module._count_halvings([1.0, 0.5, 0.25, 0.125]) == 3
    assert metrics_module._count_halvings([1.0, 0.5, 0.25, 0.125, 0.0625]) == 4


def test_count_halvings_rebound_resets_baseline():
    """回升超过当前 floor 才重置基线：0.125 后升至 2.0（新高，floor=2.0），
    再跌到 1.0（≤ 0.5×2.0）计第 4 次。"""
    assert metrics_module._count_halvings([1.0, 0.5, 0.25, 0.125, 2.0, 1.0]) == 4
    # 回升到 0.6（> 当前 floor 0.5，但低于历史高点 1.0）也重置基线，
    # 之后 0.25（≤ 0.5×0.6=0.3）继续逐级计数
    assert metrics_module._count_halvings([1.0, 0.5, 0.6, 0.25]) == 2


def test_count_halvings_mixed_series():
    """混合涨跌：新高重置 / 部分回撤不计 / 低于 floor 的回升也重置基线。"""
    # 1.6 新高 → 1.2（>0.8 不计）→ 0.7（#1，floor=0.7）→ 0.9（重置 floor=0.9）
    # → 2.0（新高 floor=2.0）→ 1.4（>1.0 不计）→ 0.68（#2，≤0.5×2.0）
    assert metrics_module._count_halvings([1.0, 1.6, 1.2, 0.7, 0.9, 2.0, 1.4, 0.68]) == 2


def test_count_halvings_flat_and_equal_boundaries():
    """等于当前 floor 不重置不计数；平盘不计数；低于 floor 但未到半腰线不计数。"""
    assert metrics_module._count_halvings([1.0, 0.5, 0.5, 0.4]) == 1
    assert metrics_module._count_halvings([1.0, 1.0, 1.0]) == 0
    assert metrics_module._count_halvings([]) == 0


def test_twr_halved_progressive_consecutive_decline_v22(no_price_fetch):
    """v2.2 1.4 端到端（真实交易序列）：连续下跌逐级计数 + 回升新高重置 + 再腰斩。

    手算逐日 v（全仓单票隔日半价换仓，买入日 r=0 平盘）：
      1.0 → 0.5（腰斩#1）→ 0.5 → 0.25（#2）→ 0.25 → 0.125（#3）→ 0.125
      → 3.0（翻倍#1，0.125→3.0 越过 2.0）→ 3.0
      → 1.5（#4，≤ 0.5×3.0）→ 1.5 → 1.2（> 0.5×1.5 不计）→ 1.2
      → 0.72（#5，≤ 0.5×1.5=0.75，floor 已重置为 1.5）；
    最终 R = −0.28；最大回撤 = (1.0 − 0.125) / 1.0 = 0.875。
    """
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("A", "A股", "BUY", 1000, 10, 10000, 0, date(2024, 1, 3)),
        T("A", "A股", "SELL", 1000, 5, 5000, 5000, date(2024, 1, 4)),
        T("A", "A股", "BUY", 1000, 5, 5000, 0, date(2024, 1, 5)),
        T("A", "A股", "SELL", 1000, 2.5, 2500, 2500, date(2024, 1, 8)),
        T("A", "A股", "BUY", 1000, 2.5, 2500, 0, date(2024, 1, 9)),
        T("A", "A股", "SELL", 1000, 1.25, 1250, 1250, date(2024, 1, 10)),
        T("A", "A股", "BUY", 1000, 1.25, 1250, 0, date(2024, 1, 11)),
        T("A", "A股", "SELL", 1000, 30, 30000, 30000, date(2024, 1, 12)),
        T("A", "A股", "BUY", 1000, 30, 30000, 0, date(2024, 1, 15)),
        T("A", "A股", "SELL", 1000, 15, 15000, 15000, date(2024, 1, 16)),
        T("A", "A股", "BUY", 1000, 15, 15000, 0, date(2024, 1, 17)),
        T("A", "A股", "SELL", 1000, 12, 12000, 12000, date(2024, 1, 18)),
        T("A", "A股", "BUY", 1000, 12, 12000, 0, date(2024, 1, 19)),
        T("A", "A股", "SELL", 1000, 7.2, 7200, 7200, date(2024, 1, 22)),
    ]
    m = compute_metrics(trades)
    assert m["pnl"]["double_count"] == 1
    assert m["pnl"]["halved_count"] == 5
    assert m["account"]["total_return_rate"] == pytest.approx(0.72 - 1, abs=1e-6)
    assert m["pnl"]["max_drawdown"] == pytest.approx((1.0 - 0.125) / 1.0, abs=1e-6)
    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-22", "return_rate": -0.28},
    ]


def test_first_row_sec_to_bank_counts_withdrawal(no_price_fetch):
    """M6：首行「证券转银行」——出金计入净转入/累计出金，期初资金 = 余额 + 出金额。

    期初资金 = 8000 + 2000 = 10000；首日 r = (8000 − (−2000) − 10000)/10000 = 0；
    后续买入日 r=0、卖出日 r = 200/8000 = 0.025。
    """
    trades = [
        T("", "", "SEC_TO_BANK", 0, 0, 2000, 8000, date(2024, 1, 2)),
        T("A", "A股", "BUY", 100, 10, 1000, 7000, date(2024, 1, 3)),
        T("A", "A股", "SELL", 100, 12, 1200, 8200, date(2024, 1, 5)),
    ]
    m = compute_metrics(trades)
    assert m["account"]["initial_balance"] == pytest.approx(10000.0, abs=0.01)
    assert m["account"]["net_transfer_in"] == pytest.approx(-2000.0, abs=0.01)
    assert m["account"]["gross_deposit"] == pytest.approx(0.0, abs=0.01)
    assert m["account"]["gross_withdraw"] == pytest.approx(2000.0, abs=0.01)
    assert m["account"]["opening_asset_value"] == pytest.approx(10000.0, abs=0.01)
    assert m["account"]["total_return_rate"] == pytest.approx(0.025, abs=1e-6)
    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-05", "return_rate": 0.025},
    ]


def test_top_loss_ascending_top_profit_descending(no_price_fetch):
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 100000, date(2024, 1, 2)),
        T("P", "P股", "BUY", 100, 10, 1000, 99000, date(2024, 1, 3)),
        T("P", "P股", "SELL", 100, 5, 500, 99500, date(2024, 1, 4)),
        T("Q", "Q股", "BUY", 100, 20, 2000, 97500, date(2024, 1, 5)),
        T("Q", "Q股", "SELL", 100, 10, 1000, 98500, date(2024, 1, 6)),
        T("R", "R股", "BUY", 100, 30, 3000, 95500, date(2024, 1, 7)),
        T("R", "R股", "SELL", 100, 28, 2800, 98300, date(2024, 1, 8)),
        T("S", "S股", "BUY", 100, 10, 1000, 97300, date(2024, 1, 9)),
        T("S", "S股", "SELL", 100, 13, 1300, 98600, date(2024, 1, 10)),
        T("T", "T股", "BUY", 100, 10, 1000, 97600, date(2024, 1, 11)),
        T("T", "T股", "SELL", 100, 11, 1100, 98700, date(2024, 1, 12)),
    ]
    m = compute_metrics(trades)
    top_loss = m["pnl"]["stock_leaderboard"]["top_loss"]
    top_profit = m["pnl"]["stock_leaderboard"]["top_profit"]
    # 亏损榜升序（亏损最多在前）：Q -1000 → P -500 → R -200
    assert [(x["code"], x["total_pnl"]) for x in top_loss] == [
        ("Q", -1000.0), ("P", -500.0), ("R", -200.0),
    ]
    # 盈利榜降序：S +300 → T +100
    assert [(x["code"], x["total_pnl"]) for x in top_profit] == [
        ("S", 300.0), ("T", 100.0),
    ]
    assert len(m["trades"]) == 5


# ---------------------------------------------------------------------------
# akshare 估值：成功 / 失败兜底 / 部分成功（账户级翻倍腰斩与个股无关）
# ---------------------------------------------------------------------------


def _open_position_trades() -> list[TradeRecord]:
    return [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("ZZZ", "ZZZ股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("WWW", "WWW股", "BUY", 100, 20, 2000, 7000, date(2024, 1, 3)),
    ]


def test_akshare_live_price_success(monkeypatch):
    monkeypatch.setattr(
        metrics_module,
        "_fetch_latest_prices",
        lambda codes, timeout=15.0: {"ZZZ": 25.0, "WWW": 8.0},
    )
    m = compute_metrics(_open_position_trades())
    a = m["account"]
    assert a["market_value_source"] == "akshare"
    assert a["valuation_date"] is not None
    assert a["holding_market_value"] == pytest.approx(3300.0, abs=0.01)
    assert a["holding_cost_value"] == pytest.approx(3000.0, abs=0.01)
    assert a["unrealized_pnl"] == pytest.approx(300.0, abs=0.01)
    # 未清仓不计胜率；账户级 v=1.0 无翻倍/腰斩（个股 ±150% 不参与）
    assert m["pnl"]["win_count"] == 0
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert m["trades"] == []


def test_akshare_failure_falls_back_to_cost(monkeypatch):
    monkeypatch.setattr(
        metrics_module, "_fetch_latest_prices", lambda codes, timeout=15.0: None
    )
    m = compute_metrics(_open_position_trades())
    a = m["account"]
    assert a["market_value_source"] == "cost"
    assert a["valuation_date"] is None
    assert a["holding_market_value"] == pytest.approx(3000.0, abs=0.01)
    assert a["unrealized_pnl"] == 0.0
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


def test_akshare_partial_price_map(monkeypatch):
    monkeypatch.setattr(
        metrics_module,
        "_fetch_latest_prices",
        lambda codes, timeout=15.0: {"ZZZ": 25.0},
    )
    m = compute_metrics(_open_position_trades())
    a = m["account"]
    assert a["market_value_source"] == "akshare"
    assert a["holding_market_value"] == pytest.approx(4500.0, abs=0.01)
    assert a["unrealized_pnl"] == pytest.approx(1500.0, abs=0.01)
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


def test_price_fetch_fallback_chain(monkeypatch):
    """akshare 全市场表失败时，逐只直连兜底仍应拿到实时价并标记 akshare。"""
    monkeypatch.setattr(
        metrics_module, "_fetch_spot_em_table", lambda ak_module: None
    )
    monkeypatch.setattr(
        metrics_module,
        "_fetch_single_em_price",
        lambda code: {"ZZZ": 25.0, "WWW": 8.0}.get(code),
    )
    m = compute_metrics(_open_position_trades(), price_timeout=5)
    a = m["account"]
    assert a["market_value_source"] == "akshare"
    assert a["holding_market_value"] == pytest.approx(3300.0, abs=0.01)
    assert a["unrealized_pnl"] == pytest.approx(300.0, abs=0.01)
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


# ---------------------------------------------------------------------------
# Schema / 序列化 / 边界
# ---------------------------------------------------------------------------


def test_json_schema_snake_case_and_serializable(no_price_fetch):
    m = compute_metrics(_full_history_trades())
    pattern = re.compile(r"^[a-z0-9_]+$")

    def check_keys(obj, path=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                assert pattern.match(key), f"非 snake_case 字段: {path}{key}"
                check_keys(value, f"{path}{key}.")
        elif isinstance(obj, list):
            for item in obj:
                check_keys(item, path)

    check_keys(m)
    payload = json.dumps(m, ensure_ascii=False, allow_nan=False)
    assert json.loads(payload) == m.to_dict()
    assert isinstance(m, MetricsResult)
    assert m["meta"]["is_partial"] is False
    # v2 新字段就位
    assert len(m["trades"]) == 6
    assert len(m["pnl"]["return_curve"]) == 4
    assert isinstance(m["stocks"], list) and len(m["stocks"]) == 6


def test_empty_result_has_v2_fields():
    m = compute_metrics([])
    assert m["meta"]["is_partial"] is False
    assert m["meta"]["start_date"] is None
    assert m["account"]["initial_balance"] == 0.0
    assert m["account"]["total_return_rate"] is None
    assert m["pnl"]["win_rate"] is None
    assert m["trading"]["total_count"] == 0
    assert m["trading"]["avg_holding_period_days"] is None
    assert m["pnl"]["monthly_pnl"] == []
    assert m["pnl"]["equity_curve"] == []
    assert m["pnl"]["return_curve"] == []
    assert m["trades"] == []
    assert m["stocks"] == []
    assert m["pnl"]["stock_leaderboard"] == {"top_profit": [], "top_loss": []}
    json.dumps(m, allow_nan=False)


def test_date_format_tolerance_and_stable_order(no_price_fetch):
    trades = [
        T("D1", "D1股", "BUY", 100, 10, 1000, 9000, "20240102"),
        T("D2", "D2股", "BUY", 100, 10, 1000, 8000, 20240102),
        T("D3", "D3股", "BUY", 100, 10, 1000, 7000, datetime(2024, 1, 2, 10, 30)),
    ]
    m = compute_metrics(trades)
    assert m["meta"]["start_date"] == "2024-01-02"
    assert m["meta"]["end_date"] == "2024-01-02"
    assert m["trading"]["total_count"] == 3
    assert m["trading"]["current_holding_count"] == 3
    assert m["trades"] == []


def test_duck_typed_records_without_balance():
    trades = [
        SimpleNamespace(
            code="Q",
            name="Q股",
            op_type="BUY",
            qty=100,
            price=10,
            amount=1000,
            trade_date="2024-02-01",
        ),
        SimpleNamespace(
            code="Q",
            name="Q股",
            op_type="SELL",
            qty=100,
            price=12,
            amount=1200,
            trade_date="2024-02-03",
        ),
    ]
    m = compute_metrics(trades)
    assert m["pnl"]["realized_pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["trading"]["total_amount"] == pytest.approx(2200.0, abs=0.01)
    assert len(m["trades"]) == 1
    assert m["trades"][0]["pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["trades"][0]["holding_days"] == 3
    # 无资金余额且无入金记录：A0=0 且 Σd=0，收益率未定义
    assert m["pnl"]["return_curve"][0]["return_rate"] is None
    assert m["account"]["total_return_rate"] is None


def test_parser_contract_records_work_with_metrics(no_price_fetch):
    """parser 已落地：用真实 TradeRecord + OpType 枚举验证集成。"""
    if not PARSER_AVAILABLE:
        pytest.skip("parser 未落地，跳过集成测试")
    m = compute_metrics(_full_history_trades())
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert len(m["trades"]) == 6
    assert len(m["pnl"]["return_curve"]) == 4
    assert m["account"]["total_return_rate"] == pytest.approx(0.006, abs=1e-4)
