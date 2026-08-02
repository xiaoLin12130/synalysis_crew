"""A3 AI 分析模块测试：无 Key 降级路径必须全绿。

运行方式：python -m pytest tests/test_analyst.py
"""

import json
import os
import shutil
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

# ── 必须在导入 synalysis_crew 之前置空 Key（load_dotenv 不会覆盖已存在的环境变量）──
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ.pop("OPENAI_API_KEY", None)
os.environ["STOCK_REVIEW_CREW_SKILLS_DIR"] = r"H:\stock_review_crew\skills"

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from synalysis_crew import analyst  # noqa: E402
from synalysis_crew.analyst import (  # noqa: E402
    DISCLAIMER,
    build_analyst_prompt,
    build_profile,
    build_report_prompt,
    ensure_disclaimer,
    load_skills,
    parse_analyst_output,
    parse_host_output,
    rule_tags,
)
from synalysis_crew.graph import analyze  # noqa: E402
from synalysis_crew.llm import DEEPSEEK_API_BASE, llm, llm_available, llm_strict  # noqa: E402


# ── 最小 stub 数据：故意塞入敏感字段，验证脱敏 ──
STUB_TRADES = [
    {
        "code": "000001",
        "name": "平安银行",
        "op_type": "证券买入",
        "qty": 500,
        "price": 11.5,
        "trade_date": "2026-06-01",
        "amount": -5750.0,
        "balance": 999999.99,
        "contract_no": "HT-SECRET-001",
        "fee": 5.0,
        "stamp_tax": 0.0,
        "commission": 5.0,
        "transfer_fee": 0.0,
        "currency": "人民币",
    },
    {
        "code": "600519",
        "name": "贵州茅台",
        "op_type": "证券卖出",
        "qty": 100,
        "price": 1450.0,
        "trade_date": "2026-06-15",
        "amount": 145000.0,
        "balance": 1145000.0,
        "contract_no": "HT-SECRET-002",
        "fee": 10.0,
        "stamp_tax": 145.0,
        "commission": 10.0,
        "transfer_fee": 0.0,
        "currency": "人民币",
    },
    {
        "code": "300750",
        "name": "宁德时代",
        "op_type": "证券买入",
        "qty": 200,
        "price": 180.5,
        "trade_date": "2026-07-10",
        "amount": -36100.0,
        "balance": 1108900.0,
        "contract_no": "HT-SECRET-003",
        "fee": 8.0,
        "stamp_tax": 0.0,
        "commission": 8.0,
        "transfer_fee": 0.0,
        "currency": "人民币",
    },
]

STUB_METRICS = {
    "interval_start": "2025-11-27",
    "interval_end": "2026-07-31",
    "opening_balance": 100000.0,
    "closing_balance": 118000.0,
    "net_transfer_in": 50000.0,
    "bank_transfer_detail": "招商银行→券商 50000",
    "total_return_rate": 0.18,
    "annualized_return": 0.31,
    "realized_pnl": 12345.6,
    "total_trade_amount": 500000.0,
    "total_trade_count": 120,
    "buy_count": 70,
    "sell_count": 50,
    "win_rate": 0.52,
    "profit_loss_ratio": 1.3,
    "max_drawdown": -0.21,
    "avg_holding_days": 4.5,
    "turnover_rate": 8.2,
    "trade_stock_count": 22,
    "holding_count": 5,
    "total_cost": 1234.5,
    "double_count": 1,
    "halved_count": 0,
    "style": "短线波段",
}

BANNED = ("contract_no", "资金余额", "银行转账", "HT-SECRET", "999999.99", "招商银行")


@contextmanager
def _tmp_dir():
    """沙箱环境下 tempfile.mkdtemp 创建的目录会变为只读，改用手动 mkdir。"""
    d = Path(__file__).resolve().parent / f"a3tmp_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    d.mkdir()
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ── llm.py ──

def test_llm_instances_and_no_key():
    assert llm.temperature == 0.7
    assert llm_strict.temperature == 0.1
    assert "deepseek" in llm.model_name.lower()
    assert llm.openai_api_base.rstrip("/") == DEEPSEEK_API_BASE.rstrip("/")
    assert llm_available() is False  # 测试环境无 Key


# ── analyst.py：Skill 加载 ──

def test_load_skills_returns_five_in_order():
    skills = load_skills()
    assert len(skills) == 5
    assert [s["id"] for s in skills] == ["alang", "bingchuan", "baxiaoxian", "yangjia", "tiechui"]
    assert {s["name"] for s in skills} == {"阿狼", "爱在冰川", "拔小弦", "炒股养家", "铁锤狂砸盘"}
    for s in skills:
        assert s["prompt"] and s["name"]


def test_load_skills_builtin_fallback_when_everything_missing(monkeypatch):
    with _tmp_dir() as tmp:
        monkeypatch.setenv("STOCK_REVIEW_CREW_SKILLS_DIR", str(Path(tmp) / "missing"))
        monkeypatch.setattr(analyst, "DEFAULT_SKILLS_DIR", str(Path(tmp) / "no_source"))
        skills = load_skills()
    assert len(skills) == 5
    assert {s["name"] for s in skills} == {"阿狼", "爱在冰川", "拔小弦", "炒股养家", "铁锤狂砸盘"}


def test_ensure_skills_copy_to_assets(monkeypatch):
    """env 目录缺失时，自动从默认目录复制到项目内 assets/skills 并可加载。"""
    with _tmp_dir() as tmp:
        root = Path(tmp)
        source = root / "src_skills"
        for sid in ("alang", "bingchuan", "baxiaoxian", "yangjia", "tiechui"):
            d = source / sid
            d.mkdir(parents=True)
            (d / "skill.json").write_text(
                json.dumps({"name": sid, "prompt": f"persona-{sid}"}, ensure_ascii=False),
                encoding="utf-8",
            )
        monkeypatch.setenv("STOCK_REVIEW_CREW_SKILLS_DIR", str(root / "missing"))
        monkeypatch.setattr(analyst, "DEFAULT_SKILLS_DIR", str(source))
        target = root / "assets" / "skills"
        result = analyst._ensure_skills_dir(assets_dir=str(target))
        assert result == str(target)
        assert len(list(target.iterdir())) == 5
        skills = analyst._load_skills_from_dir(result)
        assert {s["id"] for s in skills} == {"alang", "bingchuan", "baxiaoxian", "yangjia", "tiechui"}


# ── analyst.py：脱敏画像 ──

def test_build_profile_sanitized():
    profile = build_profile(STUB_TRADES, STUB_METRICS)
    # 必需信息在
    for token in ("000001", "平安银行", "600519", "贵州茅台", "500", "11.5", "2026-06-01", "胜率", "52.0%"):
        assert token in profile
    # 敏感信息绝不在
    for banned in BANNED:
        assert banned not in profile
    # 个股统计只含允许字段
    assert "contract_no" not in profile and "balance" not in profile


def test_build_profile_accepts_objects():
    class StubTrade:
        def __init__(self, d):
            self._d = d

        def to_dict(self):
            return dict(self._d)

    trades = [StubTrade(dict(t, contract_no="OBJ-SECRET")) for t in STUB_TRADES]
    profile = build_profile(trades, STUB_METRICS)
    assert "000001" in profile
    assert "OBJ-SECRET" not in profile


def test_build_profile_empty_inputs():
    profile = build_profile([], {})
    assert "交易画像" in profile
    for banned in BANNED:
        assert banned not in profile


# ── analyst.py：提示词不含敏感字段 ──

def test_prompts_do_not_contain_sensitive_fields():
    profile = build_profile(STUB_TRADES, STUB_METRICS)
    skills = load_skills()
    analyst_prompt = build_analyst_prompt(skills[0], profile)
    report_prompt = build_report_prompt(profile, [], [], [])
    for banned in BANNED:
        assert banned not in analyst_prompt
        assert banned not in report_prompt
    assert "【操作点评】" in analyst_prompt


# ── analyst.py：输出解析与免责声明 ──

def test_parse_analyst_output_structured():
    content = (
        "【操作点评】操作风格偏短线，胜率尚可。\n"
        "【操作建议】控制仓位，破位即走。\n"
        "【幽默标签】#短线快枪手 #回撤拉满 #韭菜自救"
    )
    parsed = parse_analyst_output(content, load_skills()[0])
    assert "短线" in parsed["analysis"]
    assert "控制仓位" in parsed["suggestion"]
    assert parsed["tags"] == ["短线快枪手", "回撤拉满", "韭菜自救"]


def test_parse_analyst_output_fallback():
    content = "没有任何格式的原始输出"
    parsed = parse_analyst_output(content, load_skills()[0])
    assert parsed["analysis"] == content
    assert parsed["tags"]  # 回落 personas 标签


def test_parse_host_output():
    assert parse_host_output("分歧判断：有\n讨论议题：该加仓还是减仓？") == (True, "该加仓还是减仓？")
    assert parse_host_output("分歧判断：无\n讨论议题：无") == (False, "")
    assert parse_host_output("分歧判断:有\n讨论话题: 多空之争") == (True, "多空之争")


def test_ensure_disclaimer():
    report = ensure_disclaimer("正文内容")
    assert report.count(DISCLAIMER) == 1
    assert report.rstrip().endswith(f"> {DISCLAIMER}")
    # 已含免责声明时去重并放到末尾
    report2 = ensure_disclaimer(f"正文{DISCLAIMER}结尾")
    assert report2.count(DISCLAIMER) == 1
    assert report2.rstrip().endswith(f"> {DISCLAIMER}")
    assert ensure_disclaimer("") == f"> {DISCLAIMER}"


def test_rule_tags_generated():
    tags = rule_tags(STUB_METRICS)
    assert tags
    assert "短线波段" in tags  # style


# ── graph.py：analyze() 无 Key 降级全流程 ──

def test_analyze_no_key_full_flow():
    result = analyze(STUB_TRADES, STUB_METRICS, max_rounds=2)
    assert isinstance(result, dict)
    assert set(result) >= {"final_report", "analysts", "debate_history", "overall_tags", "disclaimer", "degraded", "round_count"}
    assert result["degraded"] is True
    assert result["disclaimer"] == DISCLAIMER
    assert 0 <= result["round_count"] <= 2
    assert isinstance(result["debate_history"], list)

    assert len(result["analysts"]) == 5
    assert {a["skill_name"] for a in result["analysts"]} == {"阿狼", "爱在冰川", "拔小弦", "炒股养家", "铁锤狂砸盘"}
    for a in result["analysts"]:
        assert a["analysis"] and a["suggestion"]
        assert 2 <= len(a["tags"]) <= 3
        assert a["skill_id"]

    report = result["final_report"]
    assert isinstance(report, str)
    assert report.count("# 交易分析报告") == 1  # 只输出一份报告
    for section in ("账户概况", "核心观点", "分歧与讨论", "操作意见", "幽默标签", "风险提示"):
        assert section in report
    assert report.rstrip().endswith(f"> {DISCLAIMER}")
    for banned in BANNED:
        assert banned not in report


def test_analyze_max_rounds_zero():
    result = analyze(STUB_TRADES, STUB_METRICS, max_rounds=0)
    assert result["round_count"] == 0
    assert result["debate_history"] == []
    assert "# 交易分析报告" in result["final_report"]
    assert result["final_report"].rstrip().endswith(f"> {DISCLAIMER}")


def test_analyze_never_raises_on_bad_inputs():
    result = analyze(None, None)
    assert result["degraded"] is True
    assert result["final_report"]
    result2 = analyze([{"garbage": 1}], {"weird": object(), "win_rate": "abc"})
    assert result2["final_report"]
    assert result2["disclaimer"] == DISCLAIMER


def test_analyze_accepts_namespace_metrics():
    ns = SimpleNamespace(**STUB_METRICS)
    result = analyze(STUB_TRADES, ns, max_rounds=1)
    assert result["final_report"]
    assert result["round_count"] <= 1
