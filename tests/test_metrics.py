"""指标计算引擎测试（Issue #2，Agent A2）。

覆盖：
- 完整历史 / 中途开始（is_partial）两种场景；
- 胜率、盈亏比、最大回撤、翻倍/腰斩次数的手算抽查；
- FIFO 配对（含费用入成本/扣净额、拆分红股按比例摊薄成本）；
- akshare 最新价成功 / 失败按成本兜底（monkeypatch，不发网络请求）；
- 特殊操作（逆回购/分红/利息/指定交易）不混入股票交易统计；
- 固定 JSON Schema（全英文 snake_case、可严格 JSON 序列化）。

TradeRecord 优先使用 parser 已落地的契约定义（try/except），失败则回退到
测试文件内部的最小 stub dataclass（字段与 docs/requirements.md 第 4 章一致）。
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# A/B/C/D 全指标手算抽查（完整历史）
# ---------------------------------------------------------------------------


def test_full_history_hand_check_account_and_trading():
    m = compute_metrics(_full_history_trades())

    # meta / 区间口径
    assert m["meta"]["is_partial"] is False
    assert m["meta"]["start_date"] == "2024-01-01"
    assert m["meta"]["end_date"] == "2024-04-25"
    assert m["meta"]["calendar_days"] == 116
    assert m["meta"]["active_trading_days"] == 12

    # A 账户总览
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

    # B 交易统计
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
    assert t["avg_holding_period_days"] == pytest.approx(13.0, abs=0.01)


def test_full_history_hand_check_pnl_and_behavior():
    m = compute_metrics(_full_history_trades())

    # C 盈亏分析（手算：A +1500，B -600，C +400，D +200，E -1000，F +100）
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
    # 翻倍：A +150%；腰斩：B -60%、E -50%
    assert p["double_count"] == 1
    assert p["halved_count"] == 2
    assert p["unmatched_sell_amount"] == 0.0
    # 月度盈亏：1 月 +1300、2 月 +200、3 月 -1000、4 月 +100
    assert p["monthly_pnl"] == [
        {"month": "2024-01", "pnl": 1300.0},
        {"month": "2024-02", "pnl": 200.0},
        {"month": "2024-03", "pnl": -1000.0},
        {"month": "2024-04", "pnl": 100.0},
    ]
    # 累计收益曲线（月末资产近似净值）与最大回撤
    equity = [pt["equity"] for pt in p["equity_curve"]]
    assert equity == pytest.approx([101300.0, 101500.0, 100500.0, 100600.0], abs=0.01)
    assert [pt["month"] for pt in p["equity_curve"]] == [
        "2024-01",
        "2024-02",
        "2024-03",
        "2024-04",
    ]
    assert p["equity_curve"][0]["net_value"] == 1.0
    # 手算最大回撤 = (101500 - 100500) / 101500 = 0.0098522
    assert p["max_drawdown"] == pytest.approx(1000 / 101500, abs=1e-4)
    # 个股盈亏榜
    top_profit = p["stock_leaderboard"]["top_profit"]
    top_loss = p["stock_leaderboard"]["top_loss"]
    assert top_profit[0]["code"] == "A"
    assert top_profit[0]["total_pnl"] == pytest.approx(1500.0, abs=0.01)
    assert top_loss[0]["code"] == "E"
    assert top_loss[0]["total_pnl"] == pytest.approx(-1000.0, abs=0.01)

    # D 行为画像（持仓周期：A 1 天 / B 2 天 / C 7 天 / D 14 天 / E 19 天 / F 35 天）
    b = m["behavior"]
    assert b["holding_period_distribution"] == {
        "le_1d": 1,
        "2_5d": 1,
        "6_20d": 3,
        "gt_20d": 1,
    }
    assert b["monthly_activity"] == [
        {"month": "2024-01", "total_count": 6, "buy_count": 3, "sell_count": 3},
        {"month": "2024-02", "total_count": 2, "buy_count": 1, "sell_count": 1},
        {"month": "2024-03", "total_count": 3, "buy_count": 2, "sell_count": 1},
        {"month": "2024-04", "total_count": 1, "buy_count": 0, "sell_count": 1},
    ]
    # 单票最大仓位：3/1 买入 E 后 2000 / (99500 + 2000) = 0.0197
    assert b["max_position"]["ratio"] == pytest.approx(2000 / 101500, abs=1e-4)
    assert b["max_position"]["code"] == "E"
    assert b["max_position"]["date"] == "2024-03-01"
    # Top5 成交额集中度 = 12500 / 13600
    assert b["top5_concentration"] == pytest.approx(12500 / 13600, abs=1e-4)
    assert b["favorite_stocks_top10"][0]["code"] == "A"
    assert b["favorite_stocks_top10"][0]["count"] == 2
    assert b["favorite_stocks_top10"][0]["amount"] == pytest.approx(3500.0, abs=0.01)
    # 风格初判：平均持仓 13 天 -> 波段；Top5 集中度 0.92 -> 集中；无激进/稳健触发 -> 均衡
    assert b["style"]["holding_style"] == "波段"
    assert b["style"]["concentration"] == "集中"
    assert b["style"]["risk_style"] == "均衡"
    assert b["style"]["label"] == "波段·集中·均衡"


# ---------------------------------------------------------------------------
# FIFO 与费用口径
# ---------------------------------------------------------------------------


def test_fifo_fees_in_cost_and_net_proceeds():
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("X", "X股", "BUY", 100, 10, 1000, 8990, date(2024, 1, 2), fee=10, commission=10),
        T("X", "X股", "BUY", 100, 12, 1200, 7780, date(2024, 1, 4), fee=10, commission=10),
        T("X", "X股", "SELL", 50, 15, 750, 8525, date(2024, 1, 5), fee=5),
        T("X", "X股", "SELL", 150, 15, 2250, 10765, date(2024, 1, 10), fee=10),
    ]
    m = compute_metrics(trades)

    # 买入费用入成本：lot1 成本 1010（1000+10），lot2 成本 1210；卖出费用扣净额
    # 卖 1：745 - 505 = +240；卖 2：2240 - (505 + 1210) = +525；合计 +765
    assert m["pnl"]["realized_pnl"] == pytest.approx(765.0, abs=0.01)
    assert m["pnl"]["win_count"] == 2
    assert m["pnl"]["loss_count"] == 0
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["pnl"]["total_profit"] == pytest.approx(765.0, abs=0.01)
    assert m["pnl"]["profit_loss_ratio"] is None
    assert m["pnl"]["max_single_profit"] == pytest.approx(525.0, abs=0.01)
    assert m["account"]["total_cost"] == pytest.approx(35.0, abs=0.01)  # 10+10+5+10
    assert m["account"]["total_return_rate"] == pytest.approx(0.0765, abs=1e-4)
    assert m["trading"]["total_amount"] == pytest.approx(5200.0, abs=0.01)

    # 平均持仓周期：(50*3 + 50*8 + 100*6) / 200 = 5.75 天
    assert m["trading"]["avg_holding_period_days"] == pytest.approx(5.75, abs=0.01)
    assert m["behavior"]["holding_period_distribution"] == {
        "le_1d": 0,
        "2_5d": 1,
        "6_20d": 1,
        "gt_20d": 0,
    }
    # X 完整周期收益率 = (2985 - 2220) / 2220 = 34.46%，不触发翻倍/腰斩
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


def test_fifo_partial_sell_and_avg_cost_allocation():
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("Y", "Y股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("Y", "Y股", "BUY", 100, 20, 2000, 7000, date(2024, 1, 4)),
        T("Y", "Y股", "SELL", 150, 15, 2250, 9250, date(2024, 1, 10)),
    ]
    m = compute_metrics(trades)
    # FIFO：先匹配 100@10（成本 1000），再匹配 50@20（成本 1000）
    # 已实现 = 2250 - 2000 = 250；剩余 50 股成本 1000
    assert m["pnl"]["realized_pnl"] == pytest.approx(250.0, abs=0.01)
    assert m["account"]["holding_cost_value"] == pytest.approx(1000.0, abs=0.01)
    assert m["trading"]["current_holding_count"] == 1
    # 平均持仓：(100*8 + 50*6) / 150 = 7.33 天
    assert m["trading"]["avg_holding_period_days"] == pytest.approx(7.3333, abs=0.01)


# ---------------------------------------------------------------------------
# 中途开始（is_partial）两种场景
# ---------------------------------------------------------------------------


def test_mid_history_with_initial_cash_is_partial():
    # 文件从中间开始：首笔是买入，期初资金 = 5000 - (-1010) = 6010 != 0
    trades = [
        T("A", "A股", "BUY", 100, 10, 1000, 5000, date(2024, 1, 2), fee=10, commission=10),
        T("", "", "BANK_TO_SEC", 0, 0, 0, 25000, date(2024, 1, 5)),
        T("A", "A股", "SELL", 100, 15, 1500, 26495, date(2024, 1, 8), fee=5),
    ]
    m = compute_metrics(trades)
    assert m["meta"]["is_partial"] is True
    assert m["account"]["initial_balance"] == pytest.approx(6010.0, abs=0.01)
    assert m["account"]["net_transfer_in"] == pytest.approx(20000.0, abs=0.01)
    assert m["account"]["ending_balance"] == pytest.approx(26495.0, abs=0.01)
    # 总收益率 = (26495 - 6010 - 20000) / 6010 = 485 / 6010
    assert m["account"]["total_return_rate"] == pytest.approx(485 / 6010, abs=1e-4)
    assert m["account"]["realized_pnl"] == pytest.approx(485.0, abs=0.01)
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["account"]["total_cost"] == pytest.approx(15.0, abs=0.01)


def test_mid_history_with_opening_position_is_partial():
    # 首笔是期初持仓的卖出（无法配对）：已实现盈亏 pnl 中性，只记 unmatched_sell_amount
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
    assert m["pnl"]["win_count"] == 1  # 只有配对的卖出计入胜率
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    # 期初资金为 0 且无净转入，无法计算收益率 -> None
    assert m["account"]["total_return_rate"] is None


def test_sell_exceeding_position_marks_partial():
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


# ---------------------------------------------------------------------------
# 拆分红股 / 多周期 / 特殊操作
# ---------------------------------------------------------------------------


def test_bonus_share_dilutes_cost_basis():
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("G", "G股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("G", "G股", "BONUS_SHARE", 50, 0, 0, 9000, date(2024, 3, 1)),
        T("G", "G股", "SELL", 120, 15, 1800, 10800, date(2024, 5, 1)),
    ]
    m = compute_metrics(trades)
    # 红股入账后 100 -> 150 股，成本仍为 1000（每股 6.6667）
    # 卖出 120 股成本 800，已实现 = 1800 - 800 = 1000；剩余 30 股成本 200
    assert m["pnl"]["realized_pnl"] == pytest.approx(1000.0, abs=0.01)
    assert m["account"]["holding_cost_value"] == pytest.approx(200.0, abs=0.01)
    assert m["trading"]["current_holding_count"] == 1
    assert m["behavior"]["special_operations"]["bonus_share"] == {"count": 1, "qty": 50.0}
    # 持仓 120 天 -> >20 天桶
    assert m["behavior"]["holding_period_distribution"]["gt_20d"] == 1
    # 未平仓周期按成本估算（成本兜底 -> 收益率 0，不触发翻倍/腰斩）
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0


def test_multi_cycle_double_count():
    trades = [
        T("", "", "BANK_TO_SEC", 0, 0, 0, 10000, date(2024, 1, 2)),
        T("M", "M股", "BUY", 100, 10, 1000, 9000, date(2024, 1, 2)),
        T("M", "M股", "SELL", 100, 25, 2500, 11500, date(2024, 1, 3)),
        T("M", "M股", "BUY", 100, 10, 1000, 10500, date(2024, 1, 4)),
        T("M", "M股", "SELL", 100, 26, 2600, 13100, date(2024, 1, 5)),
    ]
    m = compute_metrics(trades)
    # 两个完整周期：+150% 与 +160%，均翻倍
    assert m["pnl"]["double_count"] == 2
    assert m["pnl"]["halved_count"] == 0
    assert m["pnl"]["realized_pnl"] == pytest.approx(3100.0, abs=0.01)
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["behavior"]["holding_period_distribution"]["le_1d"] == 2


def test_special_operations_excluded_from_equity_stats():
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
    # 逆回购/分红/利息/指定交易不进入股票成交统计
    assert m["trading"]["total_count"] == 2
    assert m["trading"]["total_amount"] == pytest.approx(2200.0, abs=0.01)
    assert m["trading"]["distinct_stock_count"] == 1
    assert m["pnl"]["realized_pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["account"]["ending_balance"] == pytest.approx(6250.5, abs=0.01)
    assert m["account"]["total_cost"] == pytest.approx(0.1, abs=0.01)


# ---------------------------------------------------------------------------
# akshare 估值：成功 / 失败兜底 / 部分成功
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
    # 市值 = 100*25 + 100*8 = 3300；成本 3000；浮动盈亏 +300
    assert a["holding_market_value"] == pytest.approx(3300.0, abs=0.01)
    assert a["holding_cost_value"] == pytest.approx(3000.0, abs=0.01)
    assert a["unrealized_pnl"] == pytest.approx(300.0, abs=0.01)
    # 未平仓周期按最新价估算：ZZZ +150%（翻倍），WWW -60%（腰斩）
    assert m["pnl"]["double_count"] == 1
    assert m["pnl"]["halved_count"] == 1


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
    # ZZZ 用实时价 25，WWW 按成本 20 兜底
    assert a["holding_market_value"] == pytest.approx(4500.0, abs=0.01)
    assert a["unrealized_pnl"] == pytest.approx(1500.0, abs=0.01)
    assert m["pnl"]["double_count"] == 1
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
    assert m["pnl"]["double_count"] == 1
    assert m["pnl"]["halved_count"] == 1


# ---------------------------------------------------------------------------
# Schema / 序列化 / 边界
# ---------------------------------------------------------------------------


def test_json_schema_snake_case_and_serializable():
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


def test_empty_trades():
    m = compute_metrics([])
    assert m["meta"]["is_partial"] is False
    assert m["meta"]["start_date"] is None
    assert m["account"]["initial_balance"] == 0.0
    assert m["account"]["total_return_rate"] is None
    assert m["pnl"]["win_rate"] is None
    assert m["trading"]["total_count"] == 0
    assert m["pnl"]["monthly_pnl"] == []
    json.dumps(m, allow_nan=False)


def test_date_format_tolerance_and_stable_order():
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
    # 余额缺失时按成交金额 ± 费用兜底现金流
    assert m["pnl"]["realized_pnl"] == pytest.approx(200.0, abs=0.01)
    assert m["pnl"]["win_rate"] == pytest.approx(1.0, abs=1e-4)
    assert m["trading"]["total_amount"] == pytest.approx(2200.0, abs=0.01)


def test_parser_contract_records_work_with_metrics():
    """parser 已落地：用真实 TradeRecord + OpType 枚举验证集成。"""
    if not PARSER_AVAILABLE:
        pytest.skip("parser 未落地，跳过集成测试")
    m = compute_metrics(_full_history_trades())
    assert m["pnl"]["double_count"] == 1
    assert m["pnl"]["halved_count"] == 2
    assert m["account"]["total_return_rate"] == pytest.approx(0.006, abs=1e-4)
