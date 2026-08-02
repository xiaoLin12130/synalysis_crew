# -*- coding: utf-8 -*-
"""Wave 2 端到端 / 集成测试（Issue #5，Agent A5）。

覆盖需求文档（docs/requirements.md）第 4 章接口契约全链路：

    xlsx → parse_trades → compute_metrics → analyze（无 Key 规则引擎降级）→ storage 存取

以及：
- 解析器：10 种操作类型、脏数据/空行、日期格式（int/datetime/str）、
  缺列报错、文件不存在中文异常、xlsx 往返、未知操作归 UNKNOWN、中途开始场景；
- 指标：2.3 节全部 32 项映射断言（重点：翻倍/腰斩次数、胜率、盈亏比、最大回撤、
  总收益率、年化、月度盈亏、持仓周期分布、风格初判、is_partial、FIFO 含费用、区间口径）；
- AI 模块：无 Key 降级路径（degraded=True、5 位分析师、仅一份报告、标签 2-4 个、
  免责声明程序级追加）、画像脱敏（不含合同编号/资金余额/银行转账）、坏输入不抛异常；
- storage：save/list/load、损坏文件/非法 id 返回空、字段拆分（meta/metrics/analysis）；
- 前端冒烟：Streamlit AppTest（演示数据 5 Tab 渲染、上传全流程、历史回看）。

沙箱注意事项（与本机 Windows 文件过滤器对齐）：
- 过滤器按 POSIX mode 生成 ACL：mode=0o700 的目录会锁死当前用户（WinError 5）。
  本模块在导入 streamlit.testing 之前把 os.mkdir 的 0o700 修正为 0o777
  （streamlit.testing 模块导入时会用 tempfile.mkdtemp 建临时目录，
  pytest 的 cacheprovider 也会用同样机制原子写 .pytest_cache），
  避免产生 tmp*/pytest-cache-files-* 残留；
- 所有测试临时目录用 0o777 显式创建（同 tests/test_parser.py 的 tmp_path 方案）；
- 会话结束时自动清扫工作区 tmp*/pytest-cache-files-* 残留。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"

# ── 沙箱兼容：0o700 -> 0o777（必须在导入 streamlit.testing / 任何创建 0o700 目录的库之前） ──
_orig_mkdir = os.mkdir


def _mkdir_mode_safe(path, mode=0o777, *args, **kwargs):
    if mode == 0o700:
        mode = 0o777
    return _orig_mkdir(path, mode, *args, **kwargs)


os.mkdir = _mkdir_mode_safe

# ── 无 Key 降级路径：load_dotenv 不会覆盖已存在的环境变量，必须先置空再导入模块 ──
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ.pop("OPENAI_API_KEY", None)

for _path in (_SRC, _FIXTURES):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import pytest  # noqa: E402

from synthetic_trades import STANDARD_HEADERS, build_xlsx, make_trades  # noqa: E402
from synalysis_crew import OpType, ParseError, TradeRecord, parse_trades  # noqa: E402
from synalysis_crew import storage  # noqa: E402
from synalysis_crew.analyst import DISCLAIMER, build_profile  # noqa: E402
from synalysis_crew.graph import analyze  # noqa: E402
from synalysis_crew.metrics import MetricsResult, compute_metrics  # noqa: E402
import synalysis_crew.metrics as metrics_module  # noqa: E402

try:
    from streamlit.testing.v1 import AppTest

    _APPTEST_AVAILABLE = True
except Exception:  # pragma: no cover - 环境无 streamlit 时前端冒烟自动跳过
    AppTest = None
    _APPTEST_AVAILABLE = False

# AppTest 运行时“缺少 ScriptRunContext”的告警对断言无意义，压掉保持输出干净
logging.getLogger(
    "streamlit.runtime.scriptrunner_utils.script_run_context"
).setLevel(logging.ERROR)

_NEEDS_APPTEST = pytest.mark.skipif(
    not _APPTEST_AVAILABLE, reason="streamlit.testing.v1.AppTest 不可用，跳过前端冒烟"
)

_REAL_TEN_OPS = {
    OpType.BUY,
    OpType.SELL,
    OpType.BANK_TO_SEC,
    OpType.SEC_TO_BANK,
    OpType.REPO,
    OpType.INTEREST,
    OpType.DIVIDEND,
    OpType.BONUS_SHARE,
    OpType.DIVIDEND_DIFF,
    OpType.DESIGNATED_TRADE,
}


@pytest.fixture()
def tmp_path():
    """自建临时目录（替代 pytest 内置 tmp_path，同 test_parser 方案）。"""
    base = Path(tempfile.gettempdir())
    path = base / f"synalysis_e2e_{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o777)
    yield path
    shutil.rmtree(path, ignore_errors=True)


@pytest.fixture()
def no_price_fetch(monkeypatch):
    """封死行情拉取：任何指标计算都按成本兜底，保证确定性与离线。"""
    monkeypatch.setattr(
        metrics_module,
        "_fetch_latest_prices",
        lambda codes, timeout=15.0: None,
    )
    return None


@pytest.fixture(scope="session", autouse=True)
def _cleanup_workspace_temp():
    """会话结束后清扫工作区残留（tmp* / pytest-cache-files-* / 空的 .tmp）。"""
    yield
    for child in sorted(_PROJECT_ROOT.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("tmp") or child.name.startswith("pytest-cache-files-"):
            shutil.rmtree(child, ignore_errors=True)
    tmp_dir = _PROJECT_ROOT / ".tmp"
    if tmp_dir.is_dir():
        for leftover in tmp_dir.glob("upload_*"):
            try:
                leftover.unlink()
            except OSError:
                pass
        try:
            tmp_dir.rmdir()
        except OSError:
            pass


# =====================================================================
# 解析器（真实模块，端到端视角补强）
# =====================================================================


def test_parser_xlsx_roundtrip_covers_ten_ops_and_midstream(tmp_path):
    path = build_xlsx(tmp_path / "synthetic.xlsx")
    trades = parse_trades(path)
    expected = make_trades()
    assert len(trades) == len(expected)
    assert {t.op_type for t in trades} == _REAL_TEN_OPS
    for got, exp in zip(trades, expected):
        assert got.op_type is exp.op_type
        assert got.trade_date == exp.trade_date
        assert got.code == exp.code
        assert got.name == exp.name
        assert got.contract_no == exp.contract_no
    # 中途开始：文件首行即卖出期初持仓，随后银行转证券入金
    assert trades[0].op_type is OpType.SELL
    assert trades[0].code == "600519"
    assert trades[1].op_type is OpType.BANK_TO_SEC


def test_parser_unknown_op_dirty_rows_and_date_formats(tmp_path):
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(STANDARD_HEADERS)
    # 未知操作（应归 UNKNOWN 不报错）+ 空行（应跳过）
    sheet.append(
        ["688001", "科创测试", "新股申购", 100.0, 20.0, 2000.0, 100.0, -2005.0,
         5.0, 0.0, 0.0, 5000.0, "AD00000088", 20251128, "科创测试",
         5.0, 0.0, 0.0, "人民币"]
    )
    sheet.append([None] * 19)
    # 日期格式：int / str / datetime / Excel 序列号
    sheet.append(
        ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
         -1005.0, 5.0, 0.0, 0.0, 3995.0, "AD00000089", "2025-11-29",
         "平安银行", 5.0, 0.0, 0.0, "人民币"]
    )
    sheet.append(
        ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
         -1005.0, 5.0, 0.0, 0.0, 2990.0, "AD00000090",
         datetime(2025, 11, 30, 9, 30), "平安银行", 5.0, 0.0, 0.0, "人民币"]
    )
    sheet.append(
        ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
         -1005.0, 5.0, 0.0, 0.0, 1985.0, "AD00000091", 46024,
         "平安银行", 5.0, 0.0, 0.0, "人民币"]  # Excel 序列号 = 2026-01-02
    )
    path = tmp_path / "dirty.xlsx"
    workbook.save(path)

    trades = parse_trades(path)
    assert [t.op_type for t in trades] == [
        OpType.UNKNOWN,
        OpType.BUY,
        OpType.BUY,
        OpType.BUY,
    ]
    assert [t.trade_date for t in trades] == [
        date(2025, 11, 28),
        date(2025, 11, 29),
        date(2025, 11, 30),
        date(2026, 1, 2),
    ]


def test_parser_chinese_errors_missing_file_and_column(tmp_path):
    with pytest.raises(ParseError) as excinfo:
        parse_trades(tmp_path / "不存在的文件.xlsx")
    assert "文件不存在" in str(excinfo.value)

    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["证券代码", "证券名称", "成交数量", "成交均价"])
    sheet.append(["000001", "平安银行", 100.0, 10.0])
    path = tmp_path / "no_op.xlsx"
    workbook.save(path)
    with pytest.raises(ParseError) as excinfo:
        parse_trades(path)
    assert "操作" in str(excinfo.value)
    assert "交收日期" in str(excinfo.value)


# =====================================================================
# 指标：v2 全部 32 项映射 + 中途开始关键数值
# =====================================================================


def _v2_checklist_trades() -> list[TradeRecord]:
    """v2.1 32 项清单场景：完整历史 + 4 个完整交易闭环（A +5000 / B -9000 /
    C +15000 / D -6000），累计入金 15000，期末资产 20000。

    v2.1 TWR 逐日 v 序列：[1.0, 1.5, 1.5, 1.5, 0.825, 0.825, 1.95, 1.95, 1.5]
    （2/1 转账 5000 日 r=0，出入金不产生收益）→ 月末 R = [0.5, -0.175, 0.95, 0.5]；
    峰值 1.95 < 2.0 无翻倍、最低 0.825 > 0.75(=0.5×1.5) 无腰斩；
    最大回撤 = (1.5 - 0.825) / 1.5 = 0.45；主口径 R = 0.5。
    """
    return [
        TradeRecord(code="", name="", op_type=OpType.BANK_TO_SEC, qty=0.0, price=0.0,
                    amount=0.0, balance=10000.0, trade_date=date(2024, 1, 2),
                    currency="人民币"),
        TradeRecord(code="A", name="A股", op_type=OpType.BUY, qty=100.0, price=50.0,
                    amount=5000.0, balance=5000.0, trade_date=date(2024, 1, 3),
                    currency="人民币"),
        TradeRecord(code="A", name="A股", op_type=OpType.SELL, qty=100.0, price=100.0,
                    amount=10000.0, balance=15000.0, trade_date=date(2024, 1, 5),
                    currency="人民币"),
        TradeRecord(code="", name="", op_type=OpType.BANK_TO_SEC, qty=0.0, price=0.0,
                    amount=0.0, balance=20000.0, trade_date=date(2024, 2, 1),
                    currency="人民币"),
        TradeRecord(code="B", name="B股", op_type=OpType.BUY, qty=100.0, price=100.0,
                    amount=10000.0, balance=10000.0, trade_date=date(2024, 2, 5),
                    currency="人民币"),
        TradeRecord(code="B", name="B股", op_type=OpType.SELL, qty=100.0, price=10.0,
                    amount=1000.0, balance=11000.0, trade_date=date(2024, 2, 10),
                    currency="人民币"),
        TradeRecord(code="C", name="C股", op_type=OpType.BUY, qty=100.0, price=50.0,
                    amount=5000.0, balance=6000.0, trade_date=date(2024, 3, 2),
                    currency="人民币"),
        TradeRecord(code="C", name="C股", op_type=OpType.SELL, qty=100.0, price=200.0,
                    amount=20000.0, balance=26000.0, trade_date=date(2024, 3, 10),
                    currency="人民币"),
        TradeRecord(code="D", name="D股", op_type=OpType.BUY, qty=100.0, price=100.0,
                    amount=10000.0, balance=16000.0, trade_date=date(2024, 4, 2),
                    currency="人民币"),
        TradeRecord(code="D", name="D股", op_type=OpType.SELL, qty=100.0, price=40.0,
                    amount=4000.0, balance=20000.0, trade_date=date(2024, 4, 10),
                    currency="人民币"),
    ]


def test_metrics_result_covers_all_32_requirement_items(no_price_fetch):
    """v2 规格（requirements-v2.md 1.1–1.6 + API 契约）的 32 项指标逐一映射断言。"""
    trades = _v2_checklist_trades()
    metrics = compute_metrics(trades)
    result = analyze(trades, metrics, max_rounds=2)
    m = metrics

    assert m["meta"]["is_partial"] is False
    assert json.loads(json.dumps(m, ensure_ascii=False, allow_nan=False)) == m.to_dict()

    checks = [
        # ---- A. 账户总览（8 项）----
        ("1 统计区间（首末交易日）",
         lambda: (m["meta"]["start_date"] == "2024-01-02" and
                  m["meta"]["end_date"] == "2024-04-10" and
                  m["meta"]["calendar_days"] == 100 and
                  m["meta"]["active_trading_days"] == 8)),
        ("2 期初资金 / 期末资金",
         lambda: (m["account"]["initial_balance"] == pytest.approx(0.0) and
                  m["account"]["ending_balance"] == pytest.approx(20000.0))),
        ("3 净转入资金 / 累计入金 / 累计出金",
         lambda: (m["account"]["net_transfer_in"] == pytest.approx(15000.0) and
                  m["account"]["gross_deposit"] == pytest.approx(15000.0) and
                  m["account"]["gross_withdraw"] == pytest.approx(0.0))),
        ("4 总收益率主口径（v2.1 TWR：R = Π(1+r_d) − 1 = 0.5）",
         lambda: m["account"]["total_return_rate"] == pytest.approx(0.5, abs=1e-4)),
        ("5 年化收益率（按区间自然日折算：1.5^(365/99) − 1 ≈ 3.4589）",
         lambda: m["account"]["annualized_return_rate"] == pytest.approx(
             3.4589, abs=1e-4)),
        ("6 累计已实现盈亏（完整交易闭环）",
         lambda: m["account"]["realized_pnl"] == pytest.approx(5000.0)),
        ("7 总交易成本及占成交额比例",
         lambda: (m["account"]["total_cost"] == pytest.approx(0.0) and
                  m["account"]["total_cost_ratio"] == pytest.approx(0.0))),
        ("8 期末持仓市值 / 浮动盈亏（按成本兜底）",
         lambda: (m["account"]["holding_market_value"] == pytest.approx(0.0) and
                  m["account"]["unrealized_pnl"] == pytest.approx(0.0) and
                  m["account"]["market_value_source"] == "cost")),
        # ---- B. 交易统计（7 项）----
        ("9 总成交金额、总笔数",
         lambda: (m["trading"]["total_amount"] == pytest.approx(65000.0) and
                  m["trading"]["total_count"] == 8)),
        ("10 买入笔数/金额、卖出笔数/金额",
         lambda: (m["trading"]["buy_count"] == 4 and
                  m["trading"]["buy_amount"] == pytest.approx(30000.0) and
                  m["trading"]["sell_count"] == 4 and
                  m["trading"]["sell_amount"] == pytest.approx(35000.0))),
        ("11 日均交易笔数、日均成交额",
         lambda: (m["trading"]["daily_avg_count"] == pytest.approx(1.0) and
                  m["trading"]["daily_avg_amount"] == pytest.approx(8125.0))),
        ("12 交易股票数（去重）、当前持仓只数",
         lambda: (m["trading"]["distinct_stock_count"] == 4 and
                  m["trading"]["current_holding_count"] == 0)),
        ("13 平均单笔金额",
         lambda: m["trading"]["avg_trade_amount"] == pytest.approx(8125.0)),
        ("14 资金周转率",
         lambda: m["trading"]["capital_turnover_rate"] == pytest.approx(
             4.68, abs=0.01)),
        ("15 平均持仓周期（完整交易：3+6+9+9 → 6.75 天）",
         lambda: m["trading"]["avg_holding_period_days"] == pytest.approx(6.75)),
        # ---- C. 盈亏分析（11 项）----
        ("16 已实现盈亏总额（完整交易口径）",
         lambda: m["pnl"]["realized_pnl"] == pytest.approx(5000.0)),
        ("17 盈利/亏损完整交易数、胜率",
         lambda: (m["pnl"]["win_count"] == 2 and m["pnl"]["loss_count"] == 2 and
                  m["pnl"]["win_rate"] == pytest.approx(0.5))),
        ("18 总盈利金额 / 总亏损金额 / 盈亏比",
         lambda: (m["pnl"]["total_profit"] == pytest.approx(20000.0) and
                  m["pnl"]["total_loss"] == pytest.approx(15000.0) and
                  m["pnl"]["profit_loss_ratio"] == pytest.approx(4 / 3, abs=1e-4))),
        ("19 最大单笔盈利 / 最大单笔亏损",
         lambda: (m["pnl"]["max_single_profit"] == pytest.approx(15000.0) and
                  m["pnl"]["max_single_loss"] == pytest.approx(-9000.0))),
        ("20 账户翻倍次数（v2.1：R ≥ +100% 独立事件，峰值 1.95 < 2 → 0）",
         lambda: m["pnl"]["double_count"] == 0),
        ("21 账户腰斩次数（v2.1：v ≤ 0.5×v_peak 独立事件，最低 0.825 > 0.75 → 0）",
         lambda: m["pnl"]["halved_count"] == 0),
        ("22 月度盈亏序列",
         lambda: m["pnl"]["monthly_pnl"] == [
             {"month": "2024-01", "pnl": 5000.0},
             {"month": "2024-02", "pnl": -9000.0},
             {"month": "2024-03", "pnl": 15000.0},
             {"month": "2024-04", "pnl": -6000.0},
         ]),
        ("23 收益率曲线 return_curve（v2.1 TWR 月末累计 R）",
         lambda: m["pnl"]["return_curve"] == [
             {"month": "2024-01", "date": "2024-01-05", "return_rate": 0.5},
             {"month": "2024-02", "date": "2024-02-10", "return_rate": -0.175},
             {"month": "2024-03", "date": "2024-03-10", "return_rate": 0.95},
             {"month": "2024-04", "date": "2024-04-10", "return_rate": 0.5},
         ]),
        ("24 最大回撤（基于逐日 1+R 序列）",
         lambda: m["pnl"]["max_drawdown"] == pytest.approx(0.45, abs=1e-4)),
        ("25 完整交易 trades（闭环字段齐备、status=closed）",
         lambda: (len(m["trades"]) == 4 and
                  m["trades"][0] == {
                      "code": "A", "name": "A股", "buy_qty": 100.0,
                      "buy_amount": 5000.0, "sell_qty": 100.0,
                      "sell_amount": 10000.0, "pnl": 5000.0,
                      "holding_days": 3, "start_date": "2024-01-03",
                      "end_date": "2024-01-05", "status": "closed",
                  } and
                  all(t["status"] == "closed" for t in m["trades"]))),
        ("26 unmatched_sell_amount（期初持仓卖出单列）",
         lambda: m["pnl"]["unmatched_sell_amount"] == pytest.approx(0.0)),
        ("27 个股盈亏榜（top_loss 升序、top_profit 降序）",
         lambda: ([x["code"] for x in m["pnl"]["stock_leaderboard"]["top_loss"]] ==
                  ["B", "D"] and
                  [x["code"] for x in m["pnl"]["stock_leaderboard"]["top_profit"]] ==
                  ["C", "A"])),
        # ---- D. 行为画像（4 项）----
        ("28 持仓周期分布（按完整交易）",
         lambda: m["behavior"]["holding_period_distribution"] == {
             "le_1d": 0, "2_5d": 1, "6_20d": 3, "gt_20d": 0,
         }),
        ("29 月度交易活跃度",
         lambda: m["behavior"]["monthly_activity"] == [
             {"month": "2024-01", "total_count": 2, "buy_count": 1, "sell_count": 1},
             {"month": "2024-02", "total_count": 2, "buy_count": 1, "sell_count": 1},
             {"month": "2024-03", "total_count": 2, "buy_count": 1, "sell_count": 1},
             {"month": "2024-04", "total_count": 2, "buy_count": 1, "sell_count": 1},
         ]),
        ("30 单票最大仓位 + Top5 集中度",
         lambda: (m["behavior"]["max_position"]["ratio"] == pytest.approx(0.5, abs=1e-4) and
                  m["behavior"]["max_position"]["code"] == "A" and
                  m["behavior"]["top5_concentration"] == pytest.approx(1.0))),
        ("31 偏好个股 Top10 + 风格初判 + 特殊操作统计",
         lambda: (m["behavior"]["favorite_stocks_top10"][0]["code"] == "C" and
                  m["behavior"]["style"]["label"] == "短线·集中·激进" and
                  m["behavior"]["special_operations"]["reverse_repo"]["count"] == 0 and
                  m["behavior"]["special_operations"]["dividend"]["count"] == 0)),
        # ---- E. AI 分析（1 项）----
        ("32 AI 分析（5 位分析师 + 综合报告 + 免责声明）",
         lambda: (len(result["analysts"]) == 5 and
                  all(a["analysis"] and a["suggestion"] and 2 <= len(a["tags"]) <= 4
                      for a in result["analysts"]) and
                  "# 交易分析报告" in result["final_report"] and
                  "风险提示" in result["final_report"] and
                  result["overall_tags"] and
                  result["disclaimer"] == DISCLAIMER and
                  result["final_report"].rstrip().endswith(f"> {DISCLAIMER}"))),
    ]
    assert len(checks) == 32, "v2 指标清单必须恰好 32 项"
    for label, check in checks:
        assert check(), f"指标项未通过：{label}"


def test_metrics_midstream_key_numbers(no_price_fetch):
    """中途开始场景（合成交割单）关键数值手算抽查：FIFO 含费、未清仓不计胜率、
    v2.1 TWR 收益率曲线、期初持仓合成、账户级翻倍/腰斩、最大回撤。"""
    m = compute_metrics(make_trades())
    assert isinstance(m, MetricsResult)
    assert m["meta"]["is_partial"] is True
    assert m["meta"]["start_date"] == "2025-11-27"
    assert m["meta"]["end_date"] == "2026-01-13"
    assert m["meta"]["calendar_days"] == 48
    assert m["meta"]["active_trading_days"] == 4

    # FIFO 含费用 + 红股摊薄：800 股卖出配对成本 7640，净额 8945.94 → +1305.94
    assert m["account"]["realized_pnl"] == pytest.approx(1305.94, abs=0.01)
    assert m["account"]["total_cost"] == pytest.approx(205.66, abs=0.01)
    assert m["pnl"]["realized_pnl"] == pytest.approx(1305.94, abs=0.01)
    # 000001 买 1500 + 红股 150 → 1650，仅卖 800：未清仓 → 不计完整交易/胜率
    assert m["trades"] == []
    assert m["pnl"]["win_count"] == 0
    assert m["pnl"]["loss_count"] == 0
    assert m["pnl"]["win_rate"] is None
    assert m["pnl"]["profit_loss_ratio"] is None
    assert m["pnl"]["max_single_profit"] == 0.0
    assert m["pnl"]["max_single_loss"] == 0.0
    assert m["trading"]["avg_holding_period_days"] is None
    assert m["behavior"]["holding_period_distribution"] == {
        "le_1d": 0, "2_5d": 0, "6_20d": 0, "gt_20d": 0,
    }
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert m["pnl"]["unmatched_sell_amount"] == pytest.approx(149818.50, abs=0.01)

    # v2.1 主口径 = 逐日 TWR 最终 R（精确链 1.0149017553 − 1 → 4 位舍入 0.0149）
    trr = m["account"]["total_return_rate"]
    assert trr == pytest.approx(0.0149, abs=1e-4)
    # 对照口径（期初资产基准简单收益率）：
    # (181547.84 − 149818.50 − 30000) / 149818.50 ≈ 0.0115
    assert m["account"]["total_return_rate_net"] == pytest.approx(
        (181547.84 - 149818.50 - 30000) / 149818.50, abs=1e-4
    )
    assert m["account"]["opening_asset_value"] == pytest.approx(149818.50, abs=0.01)
    assert m["account"]["gross_deposit"] == pytest.approx(50000.0, abs=0.01)
    assert m["account"]["gross_withdraw"] == pytest.approx(20000.0, abs=0.01)
    span_days = 47
    # M11：年化按模块舍入逻辑精确断言（未舍入 R ≈ 0.0149017553，span = 47）
    assert m["account"]["annualized_return_rate"] == pytest.approx(0.1217, abs=1e-4)
    # 收益率曲线（v2.1 TWR 月末累计 R）：
    # 2025-11 = −5/149818.50 ≈ −0.0000334（买入费）→ 0.0；
    # 2025-12 = 295/199813.50 ≈ 0.0014；2026-01 = 0.0149
    assert m["pnl"]["return_curve"] == [
        {"month": "2025-11", "date": "2025-11-28", "return_rate": 0.0},
        {"month": "2025-12", "date": "2025-12-02", "return_rate": 0.0014},
        {"month": "2026-01", "date": "2026-01-13", "return_rate": 0.0149},
    ]
    # 最大回撤基于逐日 (1+R)：逆回购本金价值中性（应收款 1:1），
    # 最大回撤来自 1/6 红利税 −100 元：(1.0120525 − 1.0115520)/1.0120525 ≈ 0.0005
    assert m["pnl"]["max_drawdown"] == pytest.approx(0.0005, abs=1e-4)
    # 月度盈亏：1 月卖出 800 股 +1305.94
    assert m["pnl"]["monthly_pnl"] == [
        {"month": "2025-11", "pnl": 0.0},
        {"month": "2025-12", "pnl": 0.0},
        {"month": "2026-01", "pnl": 1305.94},
    ]
    # 无完整交易 → 平均持仓 None；风格：波段·集中·稳健
    assert m["behavior"]["monthly_activity"] == [
        {"month": "2025-11", "total_count": 2, "buy_count": 1, "sell_count": 1},
        {"month": "2025-12", "total_count": 1, "buy_count": 1, "sell_count": 0},
        {"month": "2026-01", "total_count": 1, "buy_count": 0, "sell_count": 1},
    ]
    assert m["behavior"]["style"]["label"] == "波段·集中·稳健"


def test_metrics_midstream_completed_trade_and_special_ops(no_price_fetch):
    """中途开始 + 完整交易闭环 + 特殊操作剔除 + A0>0 收益率曲线（v2 1.1/1.3）。"""
    trades = [
        TradeRecord(code="OLD", name="老股", op_type=OpType.SELL, qty=200.0,
                    price=20.0, amount=4000.0, balance=4000.0,
                    trade_date=date(2025, 11, 27), currency="人民币"),
        TradeRecord(code="", name="", op_type=OpType.BANK_TO_SEC, qty=0.0,
                    price=0.0, amount=0.0, balance=14000.0,
                    trade_date=date(2025, 12, 3), currency="人民币"),
        TradeRecord(code="", name="", op_type=OpType.DIVIDEND, qty=0.0,
                    price=0.0, amount=50.0, balance=14050.0,
                    trade_date=date(2025, 12, 5), currency="人民币"),
        TradeRecord(code="N", name="N股", op_type=OpType.BUY, qty=100.0,
                    price=50.0, amount=5000.0, balance=9050.0,
                    trade_date=date(2026, 1, 6), currency="人民币"),
        TradeRecord(code="131810", name="R-001", op_type=OpType.REPO, qty=10.0,
                    price=100.0, amount=1000.0, balance=8049.9,
                    trade_date=date(2026, 1, 8), fee=0.1, commission=0.1,
                    currency="人民币"),
        TradeRecord(code="N", name="N股", op_type=OpType.SELL, qty=100.0,
                    price=120.0, amount=12000.0, balance=20049.9,
                    trade_date=date(2026, 1, 9), currency="人民币"),
        TradeRecord(code="", name="", op_type=OpType.INTEREST, qty=0.0,
                    price=0.0, amount=0.0, balance=20051.1,
                    trade_date=date(2026, 1, 10), currency="人民币"),
        TradeRecord(code="", name="", op_type=OpType.DESIGNATED_TRADE, qty=0.0,
                    price=0.0, amount=0.0, balance=20051.1,
                    trade_date=date(2026, 1, 12), currency="人民币"),
    ]
    m = compute_metrics(trades)
    assert m["meta"]["is_partial"] is True
    # 期初持仓卖出只记 unmatched_sell_amount，不进 trades
    assert m["pnl"]["unmatched_sell_amount"] == pytest.approx(4000.0, abs=0.01)
    # 完整交易只有 N 的闭环（分红/逆回购/利息/指定交易/转账一律剔除）
    assert m["trades"] == [
        {
            "code": "N", "name": "N股", "buy_qty": 100.0, "buy_amount": 5000.0,
            "sell_qty": 100.0, "sell_amount": 12000.0, "pnl": 7000.0,
            "holding_days": 4, "start_date": "2026-01-06",
            "end_date": "2026-01-09", "status": "closed",
        }
    ]
    assert m["pnl"]["win_count"] == 1
    assert m["pnl"]["win_rate"] == pytest.approx(1.0)
    assert m["pnl"]["realized_pnl"] == pytest.approx(7000.0, abs=0.01)
    sp = m["behavior"]["special_operations"]
    assert sp["dividend"] == {"count": 1, "amount": pytest.approx(50.0)}
    assert sp["reverse_repo"]["count"] == 1
    assert sp["interest"]["count"] == 1
    assert sp["other"]["count"] == 1
    # A0 = 4000（期初持仓合成）：首日卖出期初持仓 r = 0，入金日 r = 0
    assert m["account"]["opening_asset_value"] == pytest.approx(4000.0, abs=0.01)
    # v2.1 TWR 月末累计 R：2025-11 = 0（合成持仓 1:1）；
    # 2025-12 = 50/14000 ≈ 0.0036（红利计为盈亏）；2026-01 = 0.5036
    #（逆回购本金 1000 以应收款留存在资产中，R = 21051.1/14000 − 1）
    assert m["pnl"]["return_curve"] == [
        {"month": "2025-11", "date": "2025-11-27", "return_rate": 0.0},
        {"month": "2025-12", "date": "2025-12-05", "return_rate": 0.0036},
        {"month": "2026-01", "date": "2026-01-12", "return_rate": 0.5036},
    ]
    # v 峰值 ≈ 1.5036 < 2.0：无翻倍/腰斩；逆回购本金价值中性 → 无显著回撤
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert m["pnl"]["max_drawdown"] == 0.0
    assert m["account"]["total_return_rate"] == pytest.approx(0.5036, abs=1e-4)


def _tr(code, name, op, qty, price, amount, balance, d) -> TradeRecord:
    return TradeRecord(
        code=code, name=name, op_type=op, qty=qty, price=price, amount=amount,
        balance=balance, trade_date=d, currency="人民币",
    )


def test_twr_double_halved_events_hand_check(no_price_fetch):
    """v2.1 1.4 翻倍/腰斩（真实 TradeRecord 集成手算）。

    逐日 v：1.0 → 2.0（翻倍#1）→ 1.75 → 2.55（翻倍#2）→ 1.05（腰斩#1）
    → 1.3 → 1.5 → 1.1（腰斩#2）；最终 R = 0.1；回撤 = (2.55−1.05)/2.55。
    """
    trades = [
        _tr("", "", OpType.BANK_TO_SEC, 0, 0, 0, 10000, date(2024, 1, 2)),
        _tr("A", "A股", OpType.BUY, 100, 10, 1000, 9000, date(2024, 1, 3)),
        _tr("A", "A股", OpType.SELL, 100, 110, 11000, 20000, date(2024, 1, 4)),
        _tr("B", "B股", OpType.BUY, 100, 50, 5000, 15000, date(2024, 1, 5)),
        _tr("B", "B股", OpType.SELL, 100, 25, 2500, 17500, date(2024, 1, 6)),
        _tr("C", "C股", OpType.BUY, 100, 80, 8000, 9500, date(2024, 1, 7)),
        _tr("C", "C股", OpType.SELL, 100, 160, 16000, 25500, date(2024, 1, 8)),
        _tr("D", "D股", OpType.BUY, 100, 200, 20000, 5500, date(2024, 1, 9)),
        _tr("D", "D股", OpType.SELL, 100, 50, 5000, 10500, date(2024, 1, 10)),
        _tr("E", "E股", OpType.BUY, 100, 30, 3000, 7500, date(2024, 1, 11)),
        _tr("E", "E股", OpType.SELL, 100, 55, 5500, 13000, date(2024, 1, 12)),
        _tr("G", "G股", OpType.BUY, 100, 60, 6000, 7000, date(2024, 1, 15)),
        _tr("G", "G股", OpType.SELL, 100, 80, 8000, 15000, date(2024, 1, 16)),
        _tr("H", "H股", OpType.BUY, 100, 80, 8000, 7000, date(2024, 1, 17)),
        _tr("H", "H股", OpType.SELL, 100, 40, 4000, 11000, date(2024, 1, 18)),
    ]
    m = compute_metrics(trades)
    assert m["account"]["total_return_rate"] == pytest.approx(0.1, abs=1e-4)
    assert m["pnl"]["double_count"] == 2
    assert m["pnl"]["halved_count"] == 2
    assert m["pnl"]["max_drawdown"] == pytest.approx((2.55 - 1.05) / 2.55, abs=1e-4)
    assert m["pnl"]["return_curve"] == [
        {"month": "2024-01", "date": "2024-01-18", "return_rate": 0.1},
    ]


# =====================================================================
# AI 模块（真实指标 + 无 Key 降级）
# =====================================================================


def test_ai_degraded_no_key_with_real_pipeline(no_price_fetch):
    trades = make_trades()
    metrics = compute_metrics(trades)
    result = analyze(trades, metrics, max_rounds=2)

    assert result["degraded"] is True
    assert result["disclaimer"] == DISCLAIMER
    assert 0 <= result["round_count"] <= 2
    assert len(result["analysts"]) == 5
    assert {a["skill_name"] for a in result["analysts"]} == {
        "阿狼", "爱在冰川", "拔小弦", "炒股养家", "铁锤狂砸盘",
    }
    for entry in result["analysts"]:
        assert entry["analysis"] and entry["suggestion"]
        assert 2 <= len(entry["tags"]) <= 4
        assert entry["skill_id"]

    report = result["final_report"]
    assert report.count("# 交易分析报告") == 1  # 仅一份报告
    for section in ("账户概况", "核心观点", "分歧与讨论", "操作意见", "幽默标签", "风险提示"):
        assert section in report
    assert report.rstrip().endswith(f"> {DISCLAIMER}")  # 免责声明程序级追加
    assert result["overall_tags"]


def test_ai_profile_sanitized_no_sensitive_fields(no_price_fetch):
    trades = make_trades()
    metrics = compute_metrics(trades)

    profile = build_profile(trades, metrics)
    # 必要信息保留：代码/名称/数量/价格/日期（个股级统计）
    for token in ("600519", "贵州茅台", "000001", "平安银行", "2025-11-27"):
        assert token in profile
    # 敏感信息绝不出现：合同编号 / 资金余额 / 银行转账 / 脱敏前的合同号原文
    for banned in ("AD00000001", "149818.50", "资金余额", "银行转证券", "合同"):
        assert banned not in profile

    result = analyze(trades, metrics)
    for banned in ("AD00000001", "149818.50", "资金余额", "银行转证券", "合同编号"):
        assert banned not in result["final_report"]


def test_ai_bad_inputs_never_raise():
    result = analyze(None, None)
    assert result["degraded"] is True
    assert result["final_report"]
    assert result["final_report"].rstrip().endswith(f"> {DISCLAIMER}")
    result2 = analyze([{"garbage": 1}], {"weird": object(), "win_rate": "abc"})
    assert result2["final_report"]
    assert result2["disclaimer"] == DISCLAIMER


# =====================================================================
# storage（隔离目录：绝不写 data/analyses）
# =====================================================================


def test_storage_save_list_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNALYSIS_DATA_DIR", str(tmp_path / "analyses"))
    meta = {
        "file_name": "合成交割单.xlsx",
        "total_return_pct": 12.34,
        "overall_tags": ["测试标签"],
        "is_partial": True,
        "metrics": {"meta": {"is_partial": True}, "account": {"ending_balance": 100.0}},
        "analysis": {"final_report": "# 报告", "degraded": True, "overall_tags": ["测试标签"]},
    }
    record_id = storage.save_analysis(meta, timestamp="20260101-000000")
    assert record_id == "20260101-000000"

    records = storage.list_analyses()
    assert any(r["id"] == record_id and r["file_name"] == "合成交割单.xlsx" for r in records)

    loaded = storage.load_analysis(record_id)
    assert loaded["id"] == record_id
    assert loaded["meta"]["file_name"] == "合成交割单.xlsx"
    assert loaded["metrics"]["account"]["ending_balance"] == 100.0
    assert loaded["analysis"]["final_report"] == "# 报告"
    json.dumps(loaded, ensure_ascii=False)


def test_storage_field_split_meta_metrics_analysis(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNALYSIS_DATA_DIR", str(tmp_path / "analyses"))
    record_id = storage.save_analysis(
        {
            "file_name": "x.xlsx",
            "metrics": {"trading": {"total_count": 7}},
            "analysis": {"round_count": 1},
        },
        timestamp="20260102-000000",
    )
    entry = tmp_path / "analyses" / record_id
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    assert "metrics" not in meta and "analysis" not in meta
    assert json.loads((entry / "metrics.json").read_text(encoding="utf-8")) == {
        "trading": {"total_count": 7}
    }
    assert json.loads((entry / "analysis.json").read_text(encoding="utf-8")) == {
        "round_count": 1
    }


def test_storage_corrupted_files_and_illegal_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("SYNALYSIS_DATA_DIR", str(tmp_path / "analyses"))
    root = tmp_path / "analyses"
    broken = root / "broken1"
    broken.mkdir(parents=True)
    (broken / "meta.json").write_text("{not-valid-json", encoding="utf-8")
    (broken / "metrics.json").write_text("garbage", encoding="utf-8")

    # 损坏文件：list/load 均不抛异常，返回空结构
    assert any(r["id"] == "broken1" for r in storage.list_analyses())
    loaded = storage.load_analysis("broken1")
    assert loaded["id"] == "broken1"
    assert loaded["meta"] == {} and loaded["metrics"] == {} and loaded["analysis"] == {}

    # 非法 id / 不存在 id：返回空 dict
    for bad_id in ("", None, "..", "..\\evil", "a/b", "a*b", "no-such-record"):
        assert storage.load_analysis(bad_id) == {}


# =====================================================================
# 端到端全链路
# =====================================================================


def test_full_pipeline_xlsx_to_storage(tmp_path, monkeypatch, no_price_fetch):
    monkeypatch.setenv("SYNALYSIS_DATA_DIR", str(tmp_path / "analyses"))
    xlsx = build_xlsx(tmp_path / "pipeline.xlsx")

    trades = parse_trades(xlsx)
    assert len(trades) == len(make_trades())
    metrics = compute_metrics(trades)
    assert isinstance(metrics, MetricsResult)
    assert metrics["meta"]["is_partial"] is True
    assert metrics["account"]["market_value_source"] == "cost"

    result = analyze(trades, metrics, max_rounds=2)
    assert result["degraded"] is True
    assert result["final_report"].rstrip().endswith(f"> {DISCLAIMER}")

    record_id = storage.save_analysis(
        {
            "file_name": "pipeline.xlsx",
            "is_partial": metrics["meta"]["is_partial"],
            "total_return_pct": metrics["account"]["total_return_rate"],
            "overall_tags": result["overall_tags"],
            "degraded": result["degraded"],
            "metrics": metrics,
            "analysis": result,
        }
    )
    loaded = storage.load_analysis(record_id)
    assert loaded["meta"]["file_name"] == "pipeline.xlsx"
    assert loaded["metrics"]["account"]["ending_balance"] == metrics["account"]["ending_balance"]
    assert loaded["metrics"]["meta"]["is_partial"] is True
    assert loaded["analysis"]["final_report"] == result["final_report"]
    assert loaded["analysis"]["disclaimer"] == DISCLAIMER
    assert loaded["analysis"]["degraded"] is True
    entry = tmp_path / "analyses" / record_id
    assert (entry / "meta.json").exists()
    assert (entry / "metrics.json").exists()
    assert (entry / "analysis.json").exists()
    json.dumps(loaded, ensure_ascii=False, allow_nan=False)


# =====================================================================
# 前端冒烟（Streamlit AppTest）
# =====================================================================


def _make_app(tmp_path, monkeypatch, timeout=60):
    monkeypatch.setenv("SYNALYSIS_DATA_DIR", str(tmp_path / "analyses"))
    at = AppTest.from_file(str(_PROJECT_ROOT / "app.py"), default_timeout=timeout)
    at.run()
    return at


@_NEEDS_APPTEST
def test_frontend_demo_renders_five_tabs(tmp_path, monkeypatch):
    at = _make_app(tmp_path, monkeypatch)
    assert at.session_state["current"] is None  # 初始为欢迎页

    at.button(key="btn_demo").click().run()
    cur = at.session_state["current"]
    assert cur is not None and cur["id"]
    assert [tab.label for tab in at.tabs] == [
        "账户总览", "交易明细", "盈亏分析", "行为画像", "AI 报告",
    ]
    all_markdown = " ".join(md.value for md in at.markdown)
    assert "仅供参考" in all_markdown
    # 演示数据已保存为历史记录
    assert any(r["id"] == cur["id"] for r in storage.list_analyses())


@_NEEDS_APPTEST
def test_frontend_upload_runs_full_pipeline(tmp_path, monkeypatch, no_price_fetch):
    xlsx = build_xlsx(tmp_path / "upload.xlsx")
    at = _make_app(tmp_path, monkeypatch)

    at.file_uploader(key="uploader").set_value(
        [
            (
                "upload.xlsx",
                xlsx.read_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        ]
    )
    at.run()

    assert at.session_state["notices"] == []  # 真实模块全流程，无降级提示
    cur = at.session_state["current"]
    assert cur is not None and cur["id"]
    assert [tab.label for tab in at.tabs] == [
        "账户总览", "交易明细", "盈亏分析", "行为画像", "AI 报告",
    ]
    loaded = storage.load_analysis(cur["id"])
    assert loaded["metrics"]["meta"]["is_partial"] is True
    assert loaded["analysis"]["degraded"] is True
    assert loaded["analysis"]["final_report"].rstrip().endswith(f"> {DISCLAIMER}")
    # 上传临时文件已自清理
    assert list((_PROJECT_ROOT / ".tmp").glob("upload_*")) == []


@_NEEDS_APPTEST
def test_frontend_history_lookback(tmp_path, monkeypatch):
    at = _make_app(tmp_path, monkeypatch)
    at.button(key="btn_demo").click().run()
    demo_id = at.session_state["current"]["id"]

    hist_buttons = [b for b in at.button if b.key.startswith("hist_")]
    assert hist_buttons
    target = next(b for b in hist_buttons if b.key == f"hist_{demo_id}")
    target.click().run()
    assert at.session_state["current"]["id"] == demo_id

    # 顶部「新建分析」回到欢迎页
    at.button(key="btn_new").click().run()
    assert at.session_state["current"] is None
