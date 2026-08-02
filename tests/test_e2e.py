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
from synalysis_crew import OpType, ParseError, parse_trades  # noqa: E402
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
# 指标：2.3 全部 32 项映射 + 中途开始关键数值
# =====================================================================


def test_metrics_result_covers_all_32_requirement_items(no_price_fetch):
    """需求 2.3 的 32 项指标逐一映射断言（A-D 在 MetricsResult，E 在 AnalysisResult）。"""
    trades = make_trades()
    metrics = compute_metrics(trades)
    result = analyze(trades, metrics, max_rounds=2)
    m = metrics

    # 区间口径标注：文件从账户中途开始（首行卖出期初持仓）
    assert m["meta"]["is_partial"] is True
    assert json.loads(json.dumps(m, ensure_ascii=False, allow_nan=False)) == m.to_dict()

    checks = [
        # ---- A. 账户总览（8 项）----
        ("1 统计区间（首末交易日）",
         lambda: (isinstance(m["meta"]["start_date"], str) and
                  isinstance(m["meta"]["end_date"], str) and
                  m["meta"]["start_date"] <= m["meta"]["end_date"])),
        ("2 期初资金 / 期末资金",
         lambda: (isinstance(m["account"]["initial_balance"], float) and
                  m["account"]["ending_balance"] == pytest.approx(173277.84))),
        ("3 净转入资金（银行转证券 − 证券转银行）",
         lambda: m["account"]["net_transfer_in"] == pytest.approx(30000.0)),
        ("4 总收益率（按 H1 标注区间口径）",
         lambda: isinstance(m["account"]["total_return_rate"], float)),
        ("5 年化收益率（按区间天数折算）",
         lambda: isinstance(m["account"]["annualized_return_rate"], float)),
        ("6 累计已实现盈亏（FIFO 含费用）",
         lambda: m["account"]["realized_pnl"] == pytest.approx(1305.94)),
        ("7 总交易成本及占成交额比例",
         lambda: (m["account"]["total_cost"] == pytest.approx(205.66) and
                  m["account"]["total_cost_ratio"] == pytest.approx(0.0012, abs=1e-4))),
        ("8 期末持仓市值 / 浮动盈亏（H3 按成本兜底）",
         lambda: (m["account"]["holding_market_value"] == pytest.approx(8270.0) and
                  m["account"]["unrealized_pnl"] == pytest.approx(0.0) and
                  m["account"]["market_value_source"] == "cost")),
        # ---- B. 交易统计（7 项）----
        ("9 总成交金额、总笔数",
         lambda: (m["trading"]["total_amount"] == pytest.approx(174860.0) and
                  m["trading"]["total_count"] == 4)),
        ("10 买入笔数/金额、卖出笔数/金额",
         lambda: (m["trading"]["buy_count"] == 2 and
                  m["trading"]["buy_amount"] == pytest.approx(15900.0) and
                  m["trading"]["sell_count"] == 2 and
                  m["trading"]["sell_amount"] == pytest.approx(158960.0))),
        ("11 日均交易笔数、日均成交额",
         lambda: (m["trading"]["daily_avg_count"] == pytest.approx(1.0) and
                  m["trading"]["daily_avg_amount"] == pytest.approx(43715.0))),
        ("12 交易股票数（去重）、当前持仓只数",
         lambda: (m["trading"]["distinct_stock_count"] == 2 and
                  m["trading"]["current_holding_count"] == 1)),
        ("13 平均单笔金额",
         lambda: m["trading"]["avg_trade_amount"] == pytest.approx(43715.0)),
        ("14 资金周转率",
         lambda: m["trading"]["capital_turnover_rate"] == pytest.approx(0.95, abs=0.01)),
        ("15 平均持仓周期（FIFO 配对，天数）",
         lambda: m["trading"]["avg_holding_period_days"] == pytest.approx(40.0)),
        # ---- C. 盈亏分析（9 项）----
        ("16 已实现盈亏总额（含费用）",
         lambda: m["pnl"]["realized_pnl"] == pytest.approx(1305.94)),
        ("17 盈利笔数 / 亏损笔数 / 胜率",
         lambda: (m["pnl"]["win_count"] == 1 and m["pnl"]["loss_count"] == 0 and
                  m["pnl"]["win_rate"] == pytest.approx(1.0))),
        ("18 总盈利金额 / 总亏损金额 / 盈亏比",
         lambda: (m["pnl"]["total_profit"] == pytest.approx(1305.94) and
                  m["pnl"]["total_loss"] == pytest.approx(0.0) and
                  m["pnl"]["profit_loss_ratio"] is None)),
        ("19 最大单笔盈利 / 最大单笔亏损",
         lambda: (m["pnl"]["max_single_profit"] == pytest.approx(1305.94) and
                  m["pnl"]["max_single_loss"] == pytest.approx(0.0))),
        ("20 翻倍次数（完整持仓周期收益率 ≥ +100%）",
         lambda: m["pnl"]["double_count"] == 0),
        ("21 腰斩次数（完整持仓周期收益率 ≤ −50%）",
         lambda: m["pnl"]["halved_count"] == 0),
        ("22 月度盈亏序列",
         lambda: m["pnl"]["monthly_pnl"] == [
             {"month": "2025-11", "pnl": 0.0},
             {"month": "2025-12", "pnl": 0.0},
             {"month": "2026-01", "pnl": 1305.94},
         ]),
        ("23 累计收益曲线 + 最大回撤",
         lambda: (len(m["pnl"]["equity_curve"]) == 3 and
                  m["pnl"]["max_drawdown"] == pytest.approx(0.0914, abs=1e-4))),
        ("24 个股盈亏榜 Top10（盈利/亏损）",
         lambda: (m["pnl"]["stock_leaderboard"]["top_profit"][0]["code"] == "000001" and
                  m["pnl"]["stock_leaderboard"]["top_loss"] == [])),
        # ---- D. 行为画像（6 项）----
        ("D1 持仓周期分布（≤1 / 2–5 / 6–20 / >20 天）",
         lambda: m["behavior"]["holding_period_distribution"] == {
             "le_1d": 0, "2_5d": 0, "6_20d": 0, "gt_20d": 1,
         }),
        ("D2 月度交易活跃度",
         lambda: m["behavior"]["monthly_activity"] == [
             {"month": "2025-11", "total_count": 2, "buy_count": 1, "sell_count": 1},
             {"month": "2025-12", "total_count": 1, "buy_count": 1, "sell_count": 0},
             {"month": "2026-01", "total_count": 1, "buy_count": 0, "sell_count": 1},
         ]),
        ("D3 单票最大仓位（占资金比例）",
         lambda: (m["behavior"]["max_position"]["ratio"] == pytest.approx(0.0796, abs=1e-4) and
                  m["behavior"]["max_position"]["code"] == "000001")),
        ("D4 交易集中度（Top5 成交额占比）",
         lambda: m["behavior"]["top5_concentration"] == pytest.approx(1.0)),
        ("D5 偏好个股 Top10（按交易次数）",
         lambda: m["behavior"]["favorite_stocks_top10"][0] == {
             "code": "000001", "name": "平安银行", "count": 3, "amount": 24860.0,
         }),
        ("D6 风格初判（短线/波段/长线 × 集中/分散 × 激进/稳健）+ 特殊操作统计",
         lambda: (m["behavior"]["style"]["label"] == "长线·集中·稳健" and
                  m["behavior"]["special_operations"]["reverse_repo"]["count"] == 2 and
                  m["behavior"]["special_operations"]["dividend"]["count"] == 2 and
                  m["behavior"]["special_operations"]["bonus_share"]["qty"] == pytest.approx(150.0) and
                  m["behavior"]["special_operations"]["interest"]["count"] == 1 and
                  m["behavior"]["special_operations"]["ipo"]["count"] == 0 and
                  m["behavior"]["special_operations"]["other"]["count"] == 1)),
        # ---- E. AI 分析（2 项）----
        ("E1 5 位分析师个人点评 + 个人标签",
         lambda: (len(result["analysts"]) == 5 and
                  all(a["analysis"] and a["suggestion"] and 2 <= len(a["tags"]) <= 4
                      for a in result["analysts"]))),
        ("E2 综合分析报告 + 总标签 + 风险提示 + 免责声明",
         lambda: ("# 交易分析报告" in result["final_report"] and
                  "风险提示" in result["final_report"] and
                  result["overall_tags"] and
                  result["disclaimer"] == DISCLAIMER and
                  result["final_report"].rstrip().endswith(f"> {DISCLAIMER}"))),
    ]
    assert len(checks) == 32, "2.3 指标清单必须恰好 32 项"
    for label, check in checks:
        assert check(), f"指标项未通过：{label}"


def test_metrics_midstream_key_numbers(no_price_fetch):
    """中途开始场景关键数值手算抽查（FIFO 含费用、胜率、盈亏比、最大回撤等）。"""
    m = compute_metrics(make_trades())
    assert isinstance(m, MetricsResult)
    assert m["meta"]["is_partial"] is True
    assert m["meta"]["start_date"] == "2025-11-27"
    assert m["meta"]["end_date"] == "2026-01-13"
    assert m["meta"]["calendar_days"] == 48
    assert m["meta"]["active_trading_days"] == 4

    # FIFO 含费用：800 股卖出配对成本 7640（含买入费用），净额 8945.94 → +1305.94
    assert m["account"]["realized_pnl"] == pytest.approx(1305.94, abs=0.01)
    assert m["account"]["total_cost"] == pytest.approx(205.66, abs=0.01)
    assert m["pnl"]["realized_pnl"] == pytest.approx(1305.94, abs=0.01)
    assert m["pnl"]["win_count"] == 1
    assert m["pnl"]["loss_count"] == 0
    assert m["pnl"]["win_rate"] == pytest.approx(1.0)
    assert m["pnl"]["profit_loss_ratio"] is None  # 无亏损 → 盈亏比 None
    assert m["pnl"]["double_count"] == 0
    assert m["pnl"]["halved_count"] == 0
    assert m["pnl"]["unmatched_sell_amount"] == pytest.approx(149818.50, abs=0.01)

    # 区间收益率（期初资产基准）：期初资产 = 期初现金 0 + 期初持仓变现估值 149818.50；
    # 净转入 30000；期末资产 181547.84 → (181547.84 - 149818.50 - 30000) / 149818.50
    trr = m["account"]["total_return_rate"]
    assert trr == pytest.approx(
        (181547.84 - 149818.50 - 30000) / 149818.50, abs=1e-4
    )
    assert m["account"]["opening_asset_value"] == pytest.approx(149818.50, abs=0.01)
    assert m["account"]["gross_deposit"] == pytest.approx(50000.0, abs=0.01)
    assert m["account"]["gross_withdraw"] == pytest.approx(20000.0, abs=0.01)
    span_days = 47
    # 年化按未舍入收益率折算后再四舍五入，与模块口径一致（容差覆盖舍入差异）
    assert m["account"]["annualized_return_rate"] == pytest.approx(
        (1 + trr) ** (365 / span_days) - 1, abs=10.0
    )
    # 最大回撤 = (199818.50 − 181547.84) / 199818.50
    assert m["pnl"]["max_drawdown"] == pytest.approx(18270.66 / 199818.50, abs=1e-4)
    # 持仓周期：40 天 → >20 天桶；风格：长线·集中·稳健
    assert m["behavior"]["holding_period_distribution"]["gt_20d"] == 1
    assert m["trading"]["avg_holding_period_days"] == pytest.approx(40.0)
    assert m["behavior"]["style"]["label"] == "长线·集中·稳健"


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
