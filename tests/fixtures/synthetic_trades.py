"""合成交割单夹具（Issue #1 验收用，全部为虚构数据，不含任何真实交割单）。

提供：
- ``make_trades()``：覆盖 10 种操作类型的 ``TradeRecord`` 列表（含「中途开始」场景：
  文件首行即卖出期初持仓，随后有银行转证券入金，模拟账户中途导出）；
- ``build_xlsx(path)``：用 openpyxl 按同花顺标准列结构写出临时 xlsx；
- ``build_csv(path)``：写出 csv（可指定分隔符/编码，默认 utf-8-sig + 逗号）；
- ``build_txt(path)``：写出纯文本交割单（可指定分隔符/编码，默认 utf-8 + 制表符；
  空格分隔时空字段以连续空格保留，解析端按 `` +`` 拆分可还原）。
- ``make_zhangle_trades()`` / ``build_zhangle_csv(path)``：涨乐财富通版式
  （12 列：日期/摘要/发生金额/委托号/过户费/其他杂费/手续费佣金/印花税/
  成交金额/股票代码/成交数量[买正卖负]/成交价格；无证券名称与资金余额列）。
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Optional

_SRC = Path(__file__).resolve().parents[2] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from synalysis_crew import OP_LABELS, OpType, TradeRecord  # noqa: E402

__all__ = [
    "make_trades",
    "build_xlsx",
    "build_csv",
    "build_txt",
    "make_zhangle_trades",
    "build_zhangle_csv",
    "STANDARD_HEADERS",
    "ZHANGLE_HEADERS",
]


STANDARD_HEADERS = [
    "证券代码",
    "证券名称",
    "操作",
    "成交数量",
    "成交均价",
    "成交金额",
    "股票余额",
    "发生金额",
    "手续费",
    "印花税",
    "其他杂费",
    "资金余额",
    "合同编号",
    "交收日期",
    "证券中文全称",
    "佣金",
    "过户费",
    "清算费(B股)",
    "币种",
]

ZHANGLE_HEADERS = [
    "日期",
    "摘要",
    "发生金额",
    "委托号",
    "过户费",
    "其他杂费",
    "手续费/佣金",
    "印花税",
    "成交金额",
    "股票代码",
    "成交数量",
    "成交价格",
]


def make_trades(include_unknown: bool = False) -> list[TradeRecord]:
    """返回覆盖 10 种真实操作的合成交割记录（含「中途开始」场景）。

    场景：文件从账户中途开始 —— 首行即卖出期初已持有的贵州茅台（期初资金≠0），
    随后银行转证券入金，再经历买卖、红股、红利、红利差异、逆回购（两腿）、
    利息、转出、指定交易；``include_unknown=True`` 时末尾追加一条 UNKNOWN。
    资金余额按「发生金额」逐笔连续累计，可复核。
    """
    trades = [
        # 中途开始：期初已持有 600519，文件首行即卖出
        TradeRecord(
            code="600519",
            name="贵州茅台",
            op_type=OpType.SELL,
            qty=100.0,
            price=1500.00,
            amount=150000.00,
            balance=149818.50,
            fee=30.00,
            stamp_tax=150.00,
            commission=30.00,
            transfer_fee=1.50,
            contract_no="AD00000001",
            trade_date=date(2025, 11, 27),
            currency="人民币",
        ),
        # 银行转证券：期初资金之外再入金 50000
        TradeRecord(
            code="",
            name="",
            op_type=OpType.BANK_TO_SEC,
            qty=0.0,
            price=0.0,
            amount=0.0,
            balance=199818.50,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="",
            trade_date=date(2025, 11, 28),
            currency="人民币",
        ),
        TradeRecord(
            code="000001",
            name="平安银行",
            op_type=OpType.BUY,
            qty=1000.0,
            price=10.50,
            amount=10500.00,
            balance=189313.50,
            fee=5.00,
            stamp_tax=0.0,
            commission=5.00,
            transfer_fee=0.0,
            contract_no="AD00000002",
            trade_date=date(2025, 11, 28),
            currency="人民币",
        ),
        TradeRecord(
            code="000001",
            name="平安银行",
            op_type=OpType.BUY,
            qty=500.0,
            price=10.80,
            amount=5400.00,
            balance=183908.50,
            fee=5.00,
            stamp_tax=0.0,
            commission=5.00,
            transfer_fee=0.0,
            contract_no="AD00000003",
            trade_date=date(2025, 12, 2),
            currency="人民币",
        ),
        # 红股入账：数量增加、资金不变
        TradeRecord(
            code="000001",
            name="平安银行",
            op_type=OpType.BONUS_SHARE,
            qty=150.0,
            price=0.0,
            amount=0.0,
            balance=183908.50,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="",
            trade_date=date(2026, 1, 5),
            currency="人民币",
        ),
        # 红利入账：现金增加
        TradeRecord(
            code="000001",
            name="平安银行",
            op_type=OpType.DIVIDEND,
            qty=1000.0,
            price=0.0,
            amount=500.00,
            balance=184408.50,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="",
            trade_date=date(2026, 1, 5),
            currency="人民币",
        ),
        # 股息红利差异（补税）：现金减少
        TradeRecord(
            code="000001",
            name="平安银行",
            op_type=OpType.DIVIDEND_DIFF,
            qty=0.0,
            price=0.0,
            amount=0.0,
            balance=184308.50,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="",
            trade_date=date(2026, 1, 6),
            currency="人民币",
        ),
        TradeRecord(
            code="000001",
            name="平安银行",
            op_type=OpType.SELL,
            qty=800.0,
            price=11.20,
            amount=8960.00,
            balance=193254.44,
            fee=5.00,
            stamp_tax=8.96,
            commission=5.00,
            transfer_fee=0.10,
            contract_no="AD00000004",
            trade_date=date(2026, 1, 7),
            currency="人民币",
        ),
        # 通用回购逆回：第一腿（融出资金）
        TradeRecord(
            code="131810",
            name="Ｒ-001",
            op_type=OpType.REPO,
            qty=10.0,
            price=100.00,
            amount=1000.00,
            balance=192254.34,
            fee=0.10,
            stamp_tax=0.0,
            commission=0.10,
            transfer_fee=0.0,
            contract_no="AD00000005",
            trade_date=date(2026, 1, 8),
            currency="人民币",
        ),
        # 通用回购逆回：第二腿（到期回款）
        TradeRecord(
            code="131810",
            name="Ｒ-001",
            op_type=OpType.REPO,
            qty=10.0,
            price=100.005,
            amount=1000.05,
            balance=193254.39,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="AD00000005",
            trade_date=date(2026, 1, 9),
            currency="人民币",
        ),
        # 利息归本
        TradeRecord(
            code="",
            name="",
            op_type=OpType.INTEREST,
            qty=0.0,
            price=0.0,
            amount=0.0,
            balance=193277.84,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="",
            trade_date=date(2026, 1, 10),
            currency="人民币",
        ),
        # 证券转银行：资金转出
        TradeRecord(
            code="",
            name="",
            op_type=OpType.SEC_TO_BANK,
            qty=0.0,
            price=0.0,
            amount=0.0,
            balance=173277.84,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="",
            trade_date=date(2026, 1, 12),
            currency="人民币",
        ),
        # 指定交易
        TradeRecord(
            code="799999",
            name="指定登记",
            op_type=OpType.DESIGNATED_TRADE,
            qty=0.0,
            price=0.0,
            amount=0.0,
            balance=173277.84,
            fee=0.0,
            stamp_tax=0.0,
            commission=0.0,
            transfer_fee=0.0,
            contract_no="0220002602",
            trade_date=date(2026, 1, 13),
            currency="人民币",
        ),
    ]
    if include_unknown:
        trades.append(
            TradeRecord(
                code="688001",
                name="科创测试",
                op_type=OpType.UNKNOWN,
                qty=0.0,
                price=0.0,
                amount=0.0,
                balance=173277.84,
                fee=0.0,
                stamp_tax=0.0,
                commission=0.0,
                transfer_fee=0.0,
                contract_no="",
                trade_date=date(2026, 1, 14),
                currency="人民币",
            )
        )
    return trades


_NUMERIC_COLUMNS = {3, 4, 5, 6, 7, 8, 9, 10, 11, 15, 16, 17}
_DATE_COLUMN = 13


def _fmt(value: float) -> str:
    """数值转字符串（用 .15g 保证 149818.5 / 100.005 这类值可精确往返）。"""
    return format(float(value), ".15g")


def _trade_rows(trades: list[TradeRecord]) -> list[list[str]]:
    """把 TradeRecord 序列化为同花顺标准 19 列字符串行（含发生金额/股票余额推算）。"""
    rows: list[list[str]] = []
    prev_balance = 0.0
    stock_balance: dict[str, float] = {}
    for trade in trades:
        code = trade.code
        if trade.op_type is OpType.BUY:
            stock_balance[code] = stock_balance.get(code, 0.0) + trade.qty
        elif trade.op_type is OpType.SELL:
            stock_balance[code] = max(0.0, stock_balance.get(code, 0.0) - trade.qty)
        elif trade.op_type is OpType.BONUS_SHARE:
            stock_balance[code] = stock_balance.get(code, 0.0) + trade.qty

        rows.append(
            [
                code,
                trade.name,
                OP_LABELS[trade.op_type],
                _fmt(trade.qty),
                _fmt(trade.price),
                _fmt(trade.amount),
                _fmt(stock_balance.get(code, 0.0)),
                _fmt(trade.balance - prev_balance),  # 发生金额 = 资金余额变动
                _fmt(trade.fee),
                _fmt(trade.stamp_tax),
                "0",  # 其他杂费（夹具不额外使用）
                _fmt(trade.balance),
                trade.contract_no,
                trade.trade_date.strftime("%Y%m%d") if trade.trade_date else "",
                trade.name,
                _fmt(trade.commission),
                _fmt(trade.transfer_fee),
                "0",  # 清算费(B股)（夹具不额外使用）
                trade.currency,
            ]
        )
        prev_balance = trade.balance
    return rows


def build_xlsx(
    path: str | Path, trades: Optional[list[TradeRecord]] = None
) -> Path:
    """用 openpyxl 按同花顺标准列结构写出临时 xlsx（供 parser 测试）。"""
    import openpyxl

    if trades is None:
        trades = make_trades()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "交割单"
    sheet.append(STANDARD_HEADERS)
    for row in _trade_rows(trades):
        cells = []
        for index, value in enumerate(row):
            if index in _NUMERIC_COLUMNS:
                cells.append(float(value) if value != "" else None)
            elif index == _DATE_COLUMN:
                cells.append(int(value) if value else None)
            else:
                cells.append(value or None)
        sheet.append(cells)

    workbook.save(target)
    return target


def build_csv(
    path: str | Path,
    trades: Optional[list[TradeRecord]] = None,
    encoding: str = "utf-8-sig",
    delimiter: str = ",",
) -> Path:
    """写出临时 csv（默认 utf-8-sig + 逗号，可指定制表符/分号与 gbk 等编码）。"""
    import csv as csv_module

    if trades is None:
        trades = make_trades()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding=encoding, newline="") as handle:
        writer = csv_module.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(STANDARD_HEADERS)
        for row in _trade_rows(trades):
            writer.writerow(row)
    return target


def build_txt(
    path: str | Path,
    trades: Optional[list[TradeRecord]] = None,
    encoding: str = "utf-8",
    delimiter: str = "\t",
) -> Path:
    """写出纯文本交割单（默认 utf-8 + 制表符，可指定空格分隔）。

    注意：空格分隔时空字段以连续空格保留（如两空格表示空字段），
    解析端对空格分隔按「恰好一个空格」拆分可无损还原。
    """
    if trades is None:
        trades = make_trades()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [delimiter.join(STANDARD_HEADERS)]
    lines.extend(delimiter.join(row) for row in _trade_rows(trades))
    target.write_bytes(("\n".join(lines) + "\n").encode(encoding))
    return target


def make_zhangle_trades(include_unknown: bool = False) -> list[TradeRecord]:
    """涨乐版式合成记录：无证券名称/资金余额/币种/佣金列。

    ``cash_amount`` 为带符号现金流（买入为负、卖出为正，含费用），
    由 ``make_trades()`` 的资金余额序列差分得到；``balance`` 置 0.0
    （涨乐文件无该列，解析后即为 0.0）。
    """
    trades: list[TradeRecord] = []
    prev_balance = 0.0
    for trade in make_trades(include_unknown=include_unknown):
        cash_amount = trade.balance - prev_balance
        trades.append(
            TradeRecord(
                code=trade.code,
                name="",  # 涨乐无证券名称列
                op_type=trade.op_type,
                qty=trade.qty,
                price=trade.price,
                amount=trade.amount,
                balance=0.0,  # 涨乐无资金余额列
                cash_amount=cash_amount,
                fee=trade.fee,
                stamp_tax=trade.stamp_tax,
                commission=0.0,  # 涨乐「手续费/佣金」合并列 -> fee
                transfer_fee=trade.transfer_fee,
                contract_no=trade.contract_no,
                trade_date=trade.trade_date,
                currency="",  # 涨乐无币种列
            )
        )
        prev_balance = trade.balance
    return trades


def build_zhangle_csv(
    path: str | Path,
    trades: Optional[list[TradeRecord]] = None,
    encoding: str = "utf-8-sig",
) -> Path:
    """按涨乐财富通导出版式写出临时 CSV（成交数量买正卖负）。"""
    import csv as csv_module

    if trades is None:
        trades = make_zhangle_trades()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding=encoding, newline="") as handle:
        writer = csv_module.writer(handle, delimiter=",", lineterminator="\n")
        writer.writerow(ZHANGLE_HEADERS)
        for trade in trades:
            signed_qty = (
                -abs(trade.qty) if trade.op_type is OpType.SELL else abs(trade.qty)
            )
            writer.writerow(
                [
                    trade.trade_date.strftime("%Y%m%d") if trade.trade_date else "",
                    OP_LABELS[trade.op_type],
                    _fmt(trade.cash_amount),  # 发生金额（带符号）
                    trade.contract_no,  # 委托号
                    _fmt(trade.transfer_fee),  # 过户费
                    "0",  # 其他杂费（夹具不额外使用）
                    _fmt(trade.fee),  # 手续费/佣金
                    _fmt(trade.stamp_tax),  # 印花税
                    _fmt(trade.amount),  # 成交金额
                    trade.code,  # 股票代码
                    _fmt(signed_qty),  # 成交数量（买正卖负）
                    _fmt(trade.price),  # 成交价格
                ]
            )
    return target
