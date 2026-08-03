"""交割单解析器单元测试（Issue #1）。

覆盖：10 种操作类型、中途开始场景、列序/表头空格/标题行容忍、
费用聚合、UNKNOWN 兜底、空行跳过、0 金额保留、日期多格式、
CSV/TXT 分隔符探测（逗号/制表符/分号/空格）与编码链（utf-8-sig/gb18030/gbk）、
涨乐财富通版式（摘要映射/数量符号/费用映射/cash_amount/无名称列）、
xls 尽力而为、中文错误信息、合同号脱敏。
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import uuid
from datetime import date, datetime
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SRC = _PROJECT_ROOT / "src"
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
for _path in (_SRC, _FIXTURES):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from synthetic_trades import (  # noqa: E402
    STANDARD_HEADERS,
    build_csv,
    build_txt,
    build_xlsx,
    build_zhangle_csv,
    make_trades,
    make_zhangle_trades,
)
from synalysis_crew import OP_LABELS, OpType, ParseError, TradeRecord, parse_trades  # noqa: E402


REAL_TEN_OPS = {
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
    """自建临时目录（替代 pytest 内置 tmp_path）。

    本机沙箱文件过滤器在 Windows 上会遵守 POSIX 目录 mode：pytest 内置
    tmp_path 用 mode=0o700 建目录，创建出的目录 ACL 会拒绝当前用户枚举
    （WinError 5）；这里改用 0o777 显式创建，保证 ``python -m pytest``
    在沙箱内外都能直接跑通。
    """
    base = Path(tempfile.gettempdir())
    path = base / f"synalysis_parser_{uuid.uuid4().hex[:12]}"
    path.mkdir(mode=0o777)
    yield path
    shutil.rmtree(path, ignore_errors=True)


def _write_workbook(
    path: Path, headers: list[str], rows: list[list], title: str | None = None
) -> Path:
    """用 openpyxl 写一个自定义工作簿（测试脏数据/列序等场景用）。"""
    import openpyxl

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    if title is not None:
        sheet.append([title])
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    workbook.save(path)
    return path


def _assert_trades_equal(got: list[TradeRecord], expected: list[TradeRecord]) -> None:
    assert len(got) == len(expected)
    for actual, exp in zip(got, expected):
        assert actual.code == exp.code
        assert actual.name == exp.name
        assert actual.op_type is exp.op_type
        assert actual.trade_date == exp.trade_date
        assert actual.currency == exp.currency
        assert actual.contract_no == exp.contract_no
        assert actual.qty == pytest.approx(exp.qty)
        assert actual.price == pytest.approx(exp.price)
        assert actual.amount == pytest.approx(exp.amount)
        assert actual.balance == pytest.approx(exp.balance)
        assert actual.cash_amount == pytest.approx(exp.cash_amount)
        assert actual.fee == pytest.approx(exp.fee)
        assert actual.stamp_tax == pytest.approx(exp.stamp_tax)
        assert actual.commission == pytest.approx(exp.commission)
        assert actual.transfer_fee == pytest.approx(exp.transfer_fee)


# ---------------------------------------------------------------------------
# 合成夹具
# ---------------------------------------------------------------------------


def test_make_trades_covers_ten_op_types():
    trades = make_trades()
    assert {t.op_type for t in trades} == REAL_TEN_OPS
    assert len(trades) >= 10  # 13 条记录覆盖 10 种操作类型（含逆回购两腿等场景）
    for trade in trades:
        assert isinstance(trade, TradeRecord)
        assert isinstance(trade.to_dict(), dict)


def test_make_trades_midstream_start_scenario():
    trades = make_trades()
    # 中途开始：首行即卖出期初持仓（期初资金≠0），随后银转证入金
    assert trades[0].op_type is OpType.SELL
    assert trades[0].code == "600519"
    assert trades[0].name == "贵州茅台"
    assert trades[1].op_type is OpType.BANK_TO_SEC
    # 资金余额逐笔连续累计
    for prev, current in zip(trades, trades[1:]):
        assert current.balance >= 0.0
        assert prev.balance != current.balance or current.op_type in (
            OpType.BONUS_SHARE,
            OpType.DESIGNATED_TRADE,
        )


def test_make_trades_unknown_optional():
    trades = make_trades(include_unknown=True)
    assert len(trades) == len(make_trades()) + 1
    assert trades[-1].op_type is OpType.UNKNOWN


# ---------------------------------------------------------------------------
# 合成 xlsx 往返
# ---------------------------------------------------------------------------


def test_parse_synthetic_xlsx_roundtrip(tmp_path):
    path = build_xlsx(tmp_path / "synthetic.xlsx")
    trades = parse_trades(path)
    _assert_trades_equal(trades, make_trades())
    assert {t.op_type for t in trades} == REAL_TEN_OPS


def test_parse_shuffled_columns_with_spaces_and_title(tmp_path):
    """列序打乱、表头带前导空格、首行是标题行、缺可选列（默认 0/空）。"""
    path = _write_workbook(
        tmp_path / "shuffled.xlsx",
        headers=[
            "资金余额",
            " 币种",
            "证券代码",
            "成交数量",
            "操作",
            "交收日期",
            "成交金额",
            "成交均价",
            "手续费",
            "印花税",
            "合同编号",
            "佣金",
            "证券中文全称",
        ],
        rows=[
            [
                100.0,
                "人民币",
                7.0,  # 浮点代码（真实文件同款），应为 "7"
                100.0,
                "证券买入",
                20260105,
                1000.0,
                10.0,
                5.0,
                0.0,
                "AD12345678",
                5.0,
                "测试股份",
            ]
        ],
        title="XX证券 客户交割单 2026",
    )
    trades = parse_trades(path)
    assert len(trades) == 1
    trade = trades[0]
    assert trade.code == "7"
    assert trade.name == "测试股份"  # 证券名称缺失时回退到证券中文全称
    assert trade.op_type is OpType.BUY
    assert trade.trade_date == date(2026, 1, 5)
    assert trade.currency == "人民币"
    assert trade.balance == pytest.approx(100.0)
    assert trade.fee == pytest.approx(5.0)
    assert trade.commission == pytest.approx(5.0)
    assert trade.stamp_tax == pytest.approx(0.0)
    assert trade.transfer_fee == pytest.approx(0.0)  # 缺列默认 0
    assert trade.contract_no == "AD12345678"


def test_fee_and_transfer_fee_aggregation(tmp_path):
    """手续费+其他杂费 -> fee；过户费+清算费(B股) -> transfer_fee。"""
    path = _write_workbook(
        tmp_path / "fees.xlsx",
        headers=STANDARD_HEADERS,
        rows=[
            [
                "000002",
                "万科A",
                "证券买入",
                100.0,
                10.0,
                1000.0,
                100.0,
                -1005.5,
                5.0,
                0.0,
                0.5,
                8994.5,
                "AD00000099",
                20260106,
                "万科A",
                5.0,
                1.0,
                0.2,
                "人民币",
            ]
        ],
    )
    (trade,) = parse_trades(path)
    assert trade.fee == pytest.approx(5.5)
    assert trade.transfer_fee == pytest.approx(1.2)
    assert trade.commission == pytest.approx(5.0)


def test_unknown_op_does_not_raise(tmp_path):
    path = _write_workbook(
        tmp_path / "unknown.xlsx",
        headers=STANDARD_HEADERS,
        rows=[
            [
                "688001",
                "科创测试",
                "新股申购",
                100.0,
                20.0,
                2000.0,
                100.0,
                -2005.0,
                5.0,
                0.0,
                0.0,
                5000.0,
                "AD00000088",
                20251128,
                "科创测试",
                5.0,
                0.0,
                0.0,
                "人民币",
            ]
        ],
    )
    trades = parse_trades(path)
    assert len(trades) == 1
    assert trades[0].op_type is OpType.UNKNOWN


def test_blank_and_no_op_rows_skipped(tmp_path):
    path = _write_workbook(
        tmp_path / "blank.xlsx",
        headers=STANDARD_HEADERS,
        rows=[
            [
                "000001",
                "平安银行",
                "证券买入",
                100.0,
                10.0,
                1000.0,
                100.0,
                -1005.0,
                5.0,
                0.0,
                0.0,
                5000.0,
                "AD00000001",
                20251127,
                "平安银行",
                5.0,
                0.0,
                0.0,
                "人民币",
            ],
            [None] * 19,  # 全空行
            ["000002", "万科A", None, 200.0, 8.0, 1600.0, 200.0, -1605.0,
             5.0, 0.0, 0.0, 3395.0, "AD00000002", 20251128, "万科A",
             5.0, 0.0, 0.0, "人民币"],  # 操作列为空 -> 跳过
        ],
    )
    trades = parse_trades(path)
    assert len(trades) == 1
    assert trades[0].code == "000001"


def test_zero_amount_rows_preserved(tmp_path):
    path = build_xlsx(tmp_path / "zero.xlsx")
    trades = parse_trades(path)
    bank = next(t for t in trades if t.op_type is OpType.BANK_TO_SEC)
    assert bank.amount == 0.0  # 金额为 0 的记录保留，不丢弃
    assert bank.qty == 0.0
    assert bank.balance == pytest.approx(199818.50)


# ---------------------------------------------------------------------------
# 日期兼容
# ---------------------------------------------------------------------------


def test_date_formats_int_str_datetime_excel_serial(tmp_path):
    path = _write_workbook(
        tmp_path / "dates.xlsx",
        headers=STANDARD_HEADERS,
        rows=[
            ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
             -1005.0, 5.0, 0.0, 0.0, 5000.0, "AD00000001", 20251127,
             "平安银行", 5.0, 0.0, 0.0, "人民币"],
            ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
             -1005.0, 5.0, 0.0, 0.0, 5000.0, "AD00000001", "2025-11-28",
             "平安银行", 5.0, 0.0, 0.0, "人民币"],
            ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
             -1005.0, 5.0, 0.0, 0.0, 5000.0, "AD00000001",
             datetime(2025, 11, 29, 10, 30, 0), "平安银行", 5.0, 0.0, 0.0,
             "人民币"],
            ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
             -1005.0, 5.0, 0.0, 0.0, 5000.0, "AD00000001", "2025/11/30",
             "平安银行", 5.0, 0.0, 0.0, "人民币"],
            ["000001", "平安银行", "证券买入", 100.0, 10.0, 1000.0, 100.0,
             -1005.0, 5.0, 0.0, 0.0, 5000.0, "AD00000001", 46023,
             "平安银行", 5.0, 0.0, 0.0, "人民币"],  # Excel 序列号 = 2026-01-01
        ],
    )
    trades = parse_trades(path)
    assert [t.trade_date for t in trades] == [
        date(2025, 11, 27),
        date(2025, 11, 28),
        date(2025, 11, 29),
        date(2025, 11, 30),
        date(2026, 1, 1),
    ]


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


_CSV_HEADERS = ",".join(STANDARD_HEADERS)
_CSV_ROW = (
    "000001,平安银行,证券买入,100,10.5,\"1,050.00\",100,-1055,5,0,0,"
    "4945,AD12345678,2025-11-27,平安银行,5,0,0,人民币"
)


def test_parse_csv_utf8_sig_and_gbk(tmp_path):
    for index, encoding in enumerate(("utf-8-sig", "gbk")):
        path = tmp_path / f"sample_{index}.csv"
        path.write_bytes((_CSV_HEADERS + "\n" + _CSV_ROW + "\n").encode(encoding))
        trades = parse_trades(path)
        assert len(trades) == 1
        trade = trades[0]
        assert trade.code == "000001"  # dtype=object，前导零不丢失
        assert trade.name == "平安银行"
        assert trade.op_type is OpType.BUY
        assert trade.trade_date == date(2025, 11, 27)
        assert trade.amount == pytest.approx(1050.0)  # "1,050.00" 千分位
        assert trade.balance == pytest.approx(4945.0)


def test_parse_csv_tab_delimited(tmp_path):
    path = build_csv(tmp_path / "tab_delimited.csv", delimiter="\t")
    trades = parse_trades(path)
    _assert_trades_equal(trades, make_trades())


def test_parse_csv_semicolon_delimited(tmp_path):
    path = build_csv(tmp_path / "semicolon.csv", delimiter=";")
    trades = parse_trades(path)
    assert len(trades) == len(make_trades())
    assert trades[0].op_type is OpType.SELL
    assert trades[0].code == "600519"
    assert trades[0].balance == pytest.approx(149818.50)


def test_parse_csv_gbk_tab_delimited(tmp_path):
    """GBK 编码 + 制表符分隔：编码链与分隔符探测同时覆盖。"""
    path = build_csv(tmp_path / "gbk_tab.csv", encoding="gbk", delimiter="\t")
    trades = parse_trades(path)
    assert len(trades) == len(make_trades())
    assert trades[0].name == "贵州茅台"
    assert trades[0].trade_date == date(2025, 11, 27)


def test_parse_txt_tab_delimited(tmp_path):
    path = build_txt(tmp_path / "tab.txt", delimiter="\t")
    trades = parse_trades(path)
    _assert_trades_equal(trades, make_trades())


def test_parse_txt_space_delimited(tmp_path):
    """空格分隔：含空字段行（银行转证券等）也能无损还原。"""
    path = build_txt(tmp_path / "space.txt", delimiter=" ")
    trades = parse_trades(path)
    _assert_trades_equal(trades, make_trades())


def test_parse_txt_gbk_space_delimited(tmp_path):
    path = build_txt(tmp_path / "gbk_space.txt", encoding="gbk", delimiter=" ")
    trades = parse_trades(path)
    assert len(trades) == len(make_trades())
    assert trades[1].op_type is OpType.BANK_TO_SEC  # 空代码/空名称行
    assert trades[1].balance == pytest.approx(199818.50)


def test_parse_txt_unknown_delimiter_raises(tmp_path):
    path = tmp_path / "unknown.txt"
    path.write_text("这是一行没有分隔符的内容\n第二行也没有分隔符\n", encoding="utf-8")
    with pytest.raises(ParseError) as excinfo:
        parse_trades(path)
    assert "分隔符" in str(excinfo.value)


def test_parse_text_undecodable_raises(tmp_path):
    path = tmp_path / "bad.txt"
    path.write_bytes(b"\xff\xff\xff\xff")  # utf-8 与 gb18030 均无法解码
    with pytest.raises(ParseError) as excinfo:
        parse_trades(path)
    assert "编码" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 涨乐财富通版式
# ---------------------------------------------------------------------------


def test_make_zhangle_trades_layout():
    trades = make_zhangle_trades()
    assert {t.op_type for t in trades} == REAL_TEN_OPS
    # 涨乐无证券名称/资金余额/币种/佣金列
    assert all(t.name == "" for t in trades)
    assert all(t.balance == 0.0 for t in trades)
    assert all(t.currency == "" for t in trades)
    assert all(t.commission == 0.0 for t in trades)
    # cash_amount 带符号：买入为负、卖出为正
    buy = next(t for t in trades if t.op_type is OpType.BUY)
    sell = next(t for t in trades if t.op_type is OpType.SELL)
    assert buy.cash_amount < 0
    assert sell.cash_amount > 0


def test_parse_zhangle_csv_roundtrip(tmp_path):
    path = build_zhangle_csv(tmp_path / "zhangle.csv")
    trades = parse_trades(path)
    _assert_trades_equal(trades, make_zhangle_trades())
    assert {t.op_type for t in trades} == REAL_TEN_OPS
    assert all(t.name == "" and t.balance == 0.0 and t.currency == "" for t in trades)


def test_parse_zhangle_qty_sign_trusts_summary(tmp_path):
    """数量符号与摘要不一致时以摘要为准，数量取绝对值；费用/现金流水映射。"""
    path = tmp_path / "zhangle_raw.csv"
    path.write_bytes(
        (
            "日期,摘要,发生金额,委托号,过户费,其他杂费,手续费/佣金,印花税,"
            "成交金额,股票代码,成交数量,成交价格\n"
            # 摘要=证券买入 但数量为负（不一致）-> 仍按 BUY，数量取 abs
            "20260630,证券买入,-2541.53,144152,0.03,0.50,5.00,0.00,"
            "2536.00,000630,-400.00,6.340\n"
            # 摘要=证券卖出 但数量为正（不一致）-> 仍按 SELL，数量取 abs
            "20260630,证券卖出,2569.63,115458,0.00,0.00,0.77,0.00,"
            "2570.40,159559,1800.00,1.428\n"
        ).encode("utf-8")
    )
    trades = parse_trades(path)
    assert len(trades) == 2
    buy, sell = trades
    assert buy.op_type is OpType.BUY
    assert buy.qty == pytest.approx(400.0)
    assert sell.op_type is OpType.SELL
    assert sell.qty == pytest.approx(1800.0)
    # 涨乐列 -> 标准字段映射
    assert buy.code == "000630"
    assert buy.name == ""
    assert buy.trade_date == date(2026, 6, 30)
    assert buy.amount == pytest.approx(2536.0)
    assert buy.price == pytest.approx(6.34)
    assert buy.fee == pytest.approx(5.5)  # 手续费/佣金 5.00 + 其他杂费 0.50
    assert buy.stamp_tax == pytest.approx(0.0)
    assert buy.transfer_fee == pytest.approx(0.03)  # 过户费
    assert buy.cash_amount == pytest.approx(-2541.53)  # 发生金额（带符号）
    assert buy.balance == 0.0  # 无资金余额列
    assert buy.contract_no == "144152"  # 委托号
    assert buy.to_dict()["contract_no"] == "**4152"  # 序列化脱敏
    assert sell.cash_amount == pytest.approx(2569.63)
    assert sell.fee == pytest.approx(0.77)


def test_parse_zhangle_gbk_encoding(tmp_path):
    path = build_zhangle_csv(tmp_path / "zhangle_gbk.csv", encoding="gbk")
    trades = parse_trades(path)
    assert len(trades) == len(make_zhangle_trades())
    assert trades[0].code == "600519"
    assert trades[0].op_type is OpType.SELL
    assert trades[0].cash_amount == pytest.approx(149818.50)


# ---------------------------------------------------------------------------
# 错误处理（中文信息）
# ---------------------------------------------------------------------------


def test_missing_file_raises_chinese_error(tmp_path):
    with pytest.raises(ParseError) as excinfo:
        parse_trades(tmp_path / "不存在.xlsx")
    assert "文件不存在" in str(excinfo.value)


def test_directory_raises_chinese_error(tmp_path):
    with pytest.raises(ParseError) as excinfo:
        parse_trades(tmp_path)
    assert "目录" in str(excinfo.value)


def test_unparseable_file_raises_chinese_error(tmp_path):
    path = tmp_path / "bad.xlsx"
    path.write_bytes(b"this is not a real xlsx file")
    with pytest.raises(ParseError) as excinfo:
        parse_trades(path)
    assert "无法解析" in str(excinfo.value)


def test_missing_required_column_raises_chinese_error(tmp_path):
    path = _write_workbook(
        tmp_path / "no_op.xlsx",
        headers=["证券代码", "证券名称", "成交数量", "成交均价"],
        rows=[["000001", "平安银行", 100.0, 10.0]],
    )
    with pytest.raises(ParseError) as excinfo:
        parse_trades(path)
    assert "操作" in str(excinfo.value)
    assert "交收日期" in str(excinfo.value)


def test_empty_workbook_raises_chinese_error(tmp_path):
    path = _write_workbook(tmp_path / "empty.xlsx", headers=["随便"], rows=[])
    with pytest.raises(ParseError) as excinfo:
        parse_trades(path)
    assert "表头" in str(excinfo.value)


# ---------------------------------------------------------------------------
# 序列化与脱敏
# ---------------------------------------------------------------------------


def test_to_dict_masks_contract_no_and_is_json_serializable():
    trade = make_trades()[0]
    assert trade.contract_no == "AD00000001"  # 属性保留原始值（仅本地）
    payload = trade.to_dict()
    assert payload["contract_no"] == "******0001"  # 序列化边界脱敏（保留末 4 位）
    assert payload["op_type"] == "SELL"
    assert payload["trade_date"] == "2025-11-27"
    json.dumps(payload, ensure_ascii=False)
    # 空合同号不脱敏成星号
    assert make_trades()[1].to_dict()["contract_no"] == ""


def test_op_labels_cover_all_enum_members():
    assert len(OP_LABELS) == len(OpType)
    for op in OpType:
        assert op in OP_LABELS


# ---------------------------------------------------------------------------
# 操作别名与 .xls 尽力而为
# ---------------------------------------------------------------------------


def test_op_contains_matching_variants(tmp_path):
    path = _write_workbook(
        tmp_path / "variants.xlsx",
        headers=STANDARD_HEADERS,
        rows=[
            ["131810", "Ｒ-001", "逆回购到期", 10.0, 100.0, 1000.0, 0.0,
             1000.0, 0.0, 0.0, 0.0, 6000.0, "AD00000011", 20260108,
             "Ｒ-001", 0.0, 0.0, 0.0, "人民币"],
            ["000001", "平安银行", "证券买入(信用)", 100.0, 10.0, 1000.0,
             100.0, -1005.0, 5.0, 0.0, 0.0, 4995.0, "AD00000012",
             20260109, "平安银行", 5.0, 0.0, 0.0, "人民币"],
        ],
    )
    trades = parse_trades(path)
    assert [t.op_type for t in trades] == [OpType.REPO, OpType.BUY]


def test_parse_xls_best_effort(tmp_path):
    """.xls 尽力而为：xlwt/xlrd 均可用时写盘并解析，否则跳过。"""
    xlwt = pytest.importorskip("xlwt")
    pytest.importorskip("xlrd")

    path = tmp_path / "sample.xls"
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("交割单")
    for col, header in enumerate(STANDARD_HEADERS):
        sheet.write(0, col, header)
    row = [
        "000001", "平安银行", "证券买入", 100.0, 10.5, 1050.0, 100.0,
        -1055.0, 5.0, 0.0, 0.0, 4945.0, "AD12345678", 20251127,
        "平安银行", 5.0, 0.0, 0.0, "人民币",
    ]
    for col, value in enumerate(row):
        sheet.write(1, col, value)
    workbook.save(str(path))

    trades = parse_trades(path)
    assert len(trades) == 1
    assert trades[0].op_type is OpType.BUY
    assert trades[0].trade_date == date(2025, 11, 27)


def test_header_only_workbook_returns_empty_list(tmp_path):
    path = _write_workbook(
        tmp_path / "headers_only.xlsx", headers=STANDARD_HEADERS, rows=[]
    )
    assert parse_trades(path) == []
