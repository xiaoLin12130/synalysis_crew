"""同花顺交割单解析器（Issue #1）。

职责：
- 读取同花顺导出的交割单（.xlsx 为主，.xls/.csv 尽力而为）；
- 自动识别表头（容忍列序变化、表头前后空格、全角括号、标题行）；
- 操作类型归一化为 ``OpType`` 枚举，未知操作归 ``UNKNOWN`` 不报错；
- 脏数据容错：空行/无操作行跳过，金额为 0 保留，日期兼容 int/datetime/str；
- 文件不存在或不可解析时抛出带中文信息的 ``ParseError``。

字段口径（契约见 docs/requirements.md 第 4 章）：
- ``fee``          = 同花顺「手续费」+「其他杂费」（TradeRecord 无独立杂费字段，
  合并进 fee，保证下游「总交易成本 = 手续费+印花税+佣金+过户费+杂费」口径成立）；
- ``transfer_fee`` = 「过户费」+「清算费(B股)」；
- ``contract_no``  在 ``to_dict()`` 中脱敏（保留末 4 位），dataclass 属性保留原始值
  仅供本地处理，任何输出/序列化一律走 ``to_dict()``。
"""

from __future__ import annotations

import datetime as dt
import math
import os
from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real
from pathlib import Path
from typing import Any, Optional

import pandas as pd

__all__ = [
    "OpType",
    "TradeRecord",
    "ParseError",
    "parse_trades",
    "OP_LABELS",
]


class OpType(str, Enum):
    """交割单操作类型（归一化枚举）。"""

    BUY = "BUY"
    SELL = "SELL"
    BANK_TO_SEC = "BANK_TO_SEC"
    SEC_TO_BANK = "SEC_TO_BANK"
    REPO = "REPO"
    INTEREST = "INTEREST"
    DIVIDEND = "DIVIDEND"
    BONUS_SHARE = "BONUS_SHARE"
    DIVIDEND_DIFF = "DIVIDEND_DIFF"
    DESIGNATED_TRADE = "DESIGNATED_TRADE"
    UNKNOWN = "UNKNOWN"


class ParseError(Exception):
    """交割单解析失败（文件不存在 / 不可解析 / 缺必需列 / 日期无法解析）。"""


@dataclass
class TradeRecord:
    """单条交割记录（跨模块契约字段，见 docs/requirements.md 第 4 章）。"""

    code: str = ""
    name: str = ""
    op_type: OpType = OpType.UNKNOWN
    qty: float = 0.0
    price: float = 0.0
    amount: float = 0.0
    balance: float = 0.0
    fee: float = 0.0
    stamp_tax: float = 0.0
    commission: float = 0.0
    transfer_fee: float = 0.0
    contract_no: str = ""
    trade_date: Optional[dt.date] = None
    currency: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为 JSON 友好 dict（op_type 转字符串、日期转 ISO、合同号脱敏）。"""
        return {
            "code": self.code,
            "name": self.name,
            "op_type": self.op_type.value,
            "qty": self.qty,
            "price": self.price,
            "amount": self.amount,
            "balance": self.balance,
            "fee": self.fee,
            "stamp_tax": self.stamp_tax,
            "commission": self.commission,
            "transfer_fee": self.transfer_fee,
            "contract_no": _mask_contract_no(self.contract_no),
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "currency": self.currency,
        }


# ---------------------------------------------------------------------------
# 表头识别
# ---------------------------------------------------------------------------

_COLUMN_ALIASES: dict[str, list[str]] = {
    "code": ["证券代码", "股票代码", "代码"],
    "name": ["证券名称", "证券简称", "股票名称", "名称"],
    "op": ["操作", "交易操作", "业务类型"],
    "qty": ["成交数量", "成交量", "成交股数"],
    "price": ["成交均价", "成交价", "均价"],
    "amount": ["成交金额", "成交额"],
    "stock_balance": ["股票余额", "证券余额", "持仓余额"],  # 识别但不在契约字段中
    "cash_amount": ["发生金额"],  # 识别但不在契约字段中
    "fee": ["手续费"],
    "stamp_tax": ["印花税"],
    "misc_fee": ["其他杂费", "其它杂费"],
    "balance": ["资金余额", "现金余额", "余额"],
    "contract_no": ["合同编号", "合同号", "合同序号"],
    "trade_date": ["交收日期", "成交日期", "交易日期", "日期"],
    "full_name": ["证券中文全称", "证券全称"],
    "commission": ["佣金"],
    "transfer_fee": ["过户费"],
    "settlement_fee": ["清算费(b股)", "清算费", "b股清算费"],
    "currency": ["币种", "货币"],
}

_ALL_ALIASES: dict[str, str] = {
    alias: canonical
    for canonical, aliases in _COLUMN_ALIASES.items()
    for alias in aliases
}

_REQUIRED_COLUMNS = ("op", "trade_date")


def _norm_header(value: Any) -> str:
    """表头归一化：去首尾/内部空白、全角括号转半角、转小写。"""
    if value is None:
        return ""
    text = str(value).strip()
    text = text.replace("（", "(").replace("）", ")")
    text = "".join(text.split())  # 去掉所有空白（含全角空格）
    return text.lower()


def _detect_header(raw: pd.DataFrame) -> Optional[tuple[int, list[str]]]:
    """在前 30 行内找命中别名最多的行作为表头（容忍标题行）。"""
    best_row, best_score = -1, -1
    for r in range(min(len(raw), 30)):
        score = sum(
            1 for cell in raw.iloc[r].tolist() if _norm_header(cell) in _ALL_ALIASES
        )
        if score > best_score:
            best_score, best_row = score, r
    if best_score < 2:
        return None
    return best_row, [_norm_header(c) for c in raw.iloc[best_row].tolist()]


def _resolve_columns(headers: list[str]) -> dict[str, int]:
    """把归一化后的表头映射为 规范字段 -> 列下标（首个命中优先）。"""
    found: dict[str, int] = {}
    for index, header in enumerate(headers):
        canonical = _ALL_ALIASES.get(header)
        if canonical is not None and canonical not in found:
            found[canonical] = index
    return found


# ---------------------------------------------------------------------------
# 单元格类型转换
# ---------------------------------------------------------------------------


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str):
        return not value.strip()
    return False


def _to_float(value: Any) -> float:
    """数值容错转换；空/非法 -> 0.0（金额为 0 的记录保留，不丢弃）。"""
    if value is None:
        return 0.0
    try:
        if pd.isna(value):
            return 0.0
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, Real):
        number = float(value)
        return 0.0 if math.isnan(number) else number
    if isinstance(value, str):
        text = (
            value.strip()
            .replace(",", "")
            .replace("¥", "")
            .replace("￥", "")
            .replace("元", "")
        )
        text = "".join(text.split())
        if text in ("", "-", "--", "null", "none", "nan"):
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_text(value: Any) -> str:
    """文本容错转换；空 -> ""；整型浮点（如 2962.0）去掉小数点。"""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(value, Integral):
        return str(int(value))
    if isinstance(value, Real):
        number = float(value)
        if math.isnan(number):
            return ""
        return str(int(number)) if number.is_integer() else str(number)
    return str(value).strip()


_DATE_TEXT_FORMATS = (
    "%Y%m%d",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y年%m月%d日",
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y%m%d%H%M%S",
)


def _to_date(value: Any, row_no: int) -> Optional[dt.date]:
    """日期容错：int(20251127)/float/datetime/str 均支持；空 -> None。"""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (Integral, Real)):
        number = int(float(value))
        if 10000000 <= number <= 99999999:  # YYYYMMDD
            year, month, day = number // 10000, (number // 100) % 100, number % 100
            try:
                return dt.date(year, month, day)
            except ValueError as exc:
                raise ParseError(f"第 {row_no} 行日期非法：{value!r}") from exc
        if 0 < number < 70000:  # Excel 序列号
            return dt.date(1899, 12, 30) + dt.timedelta(days=number)
        raise ParseError(f"第 {row_no} 行日期无法解析：{value!r}")
    text = str(value).strip()
    if not text:
        return None
    for fmt in _DATE_TEXT_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ParseError(f"第 {row_no} 行日期无法解析：{value!r}")


# ---------------------------------------------------------------------------
# 操作分类
# ---------------------------------------------------------------------------

OP_LABELS: dict[OpType, str] = {
    OpType.BUY: "证券买入",
    OpType.SELL: "证券卖出",
    OpType.BANK_TO_SEC: "银行转证券",
    OpType.SEC_TO_BANK: "证券转银行",
    OpType.REPO: "通用回购逆回",
    OpType.INTEREST: "利息归本",
    OpType.DIVIDEND: "红利入账",
    OpType.BONUS_SHARE: "红股入账",
    OpType.DIVIDEND_DIFF: "股息红利差异",
    OpType.DESIGNATED_TRADE: "指定交易",
    OpType.UNKNOWN: "其他业务",
}

_OP_EXACT: dict[str, OpType] = {
    label: op for op, label in OP_LABELS.items() if op is not OpType.UNKNOWN
}
_OP_EXACT["银转证"] = OpType.BANK_TO_SEC
_OP_EXACT["证转银"] = OpType.SEC_TO_BANK
_OP_EXACT["买入"] = OpType.BUY
_OP_EXACT["卖出"] = OpType.SELL
_OP_EXACT["逆回购"] = OpType.REPO
_OP_EXACT["回购"] = OpType.REPO
_OP_EXACT["利息入账"] = OpType.INTEREST
_OP_EXACT["股息入账"] = OpType.DIVIDEND
_OP_EXACT["分红入账"] = OpType.DIVIDEND
_OP_EXACT["送股入账"] = OpType.BONUS_SHARE
_OP_EXACT["股息红利税"] = OpType.DIVIDEND_DIFF
_OP_EXACT["红利差异"] = OpType.DIVIDEND_DIFF


def _classify_op(value: Any) -> OpType:
    """操作列 -> OpType；精确匹配优先，其次包含匹配，兜底 UNKNOWN（不报错）。"""
    text = _to_text(value).replace(" ", "").replace("\u3000", "")
    if not text:
        return OpType.UNKNOWN
    if text in _OP_EXACT:
        return _OP_EXACT[text]
    if "股息红利差异" in text or "红利差异" in text or "股息" in text:
        return OpType.DIVIDEND_DIFF
    if "红利入账" in text or "分红" in text:
        return OpType.DIVIDEND
    if "红股" in text or "送股" in text:
        return OpType.BONUS_SHARE
    if "银行转证券" in text or "银转证" in text:
        return OpType.BANK_TO_SEC
    if "证券转银行" in text or "证转银" in text:
        return OpType.SEC_TO_BANK
    if "回购" in text:
        return OpType.REPO
    if "利息" in text:
        return OpType.INTEREST
    if "指定交易" in text:
        return OpType.DESIGNATED_TRADE
    if "买入" in text or "买" in text:
        return OpType.BUY
    if "卖出" in text or "卖" in text:
        return OpType.SELL
    return OpType.UNKNOWN


def _mask_contract_no(value: str) -> str:
    """合同编号脱敏：保留末 4 位，其余以 * 代替。"""
    text = (value or "").strip()
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]


# ---------------------------------------------------------------------------
# 读取与解析
# ---------------------------------------------------------------------------


def _read_excel(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".xls":
        try:
            return pd.read_excel(path, header=None, sheet_name=0, engine="xlrd")
        except ImportError as exc:
            raise ParseError(
                f"解析 .xls 文件需要安装 xlrd：{exc}"
            ) from exc
    return pd.read_excel(path, header=None, sheet_name=0, engine="openpyxl")


def _read_csv(path: Path) -> pd.DataFrame:
    last_error: Optional[Exception] = None
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "gbk", "latin-1"):
        try:
            return pd.read_csv(
                path,
                header=None,
                dtype=object,
                keep_default_na=False,
                encoding=encoding,
            )
        except (UnicodeDecodeError, UnicodeError) as exc:
            last_error = exc
    raise ParseError(f"CSV 编码无法识别（已尝试 utf-8/gb18030/gbk 等）：{last_error}")


def _read_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        return _read_excel(path)
    if suffix == ".xls":
        return _read_excel(path)
    if suffix == ".csv":
        return _read_csv(path)
    # 未知扩展名：尽力而为，先按 Excel 再按 CSV 尝试
    try:
        return _read_excel(path)
    except ParseError:
        raise
    except Exception:
        return _read_csv(path)


def _rows_to_records(raw: pd.DataFrame, source: str) -> list[TradeRecord]:
    header = _detect_header(raw)
    if header is None:
        raise ParseError(
            f"{source}：文件为空或未找到表头行（需要包含「操作」「交收日期」等列）"
        )
    header_row, normalized_headers = header
    columns = _resolve_columns(normalized_headers)
    missing = [name for name in _REQUIRED_COLUMNS if name not in columns]
    if missing:
        label = {"op": "操作", "trade_date": "交收日期"}
        raise ParseError(
            f"{source}：缺少必需列：{', '.join(label[m] for m in missing)}"
        )

    records: list[TradeRecord] = []
    for row_no in range(header_row + 1, len(raw)):
        row = raw.iloc[row_no]
        if all(_is_empty(cell) for cell in row.tolist()):
            continue  # 空行跳过
        op_text = _to_text(_cell(row, columns, "op"))
        if not op_text:
            continue  # 无操作信息的脏行跳过（无法归类）
        trade_date = _to_date(_cell(row, columns, "trade_date"), row_no + 1)
        code = _to_text(_cell(row, columns, "code"))
        name = _to_text(_cell(row, columns, "name"))
        if not name:
            name = _to_text(_cell(row, columns, "full_name"))
        fee = _to_float(_cell(row, columns, "fee")) + _to_float(
            _cell(row, columns, "misc_fee")
        )
        transfer_fee = _to_float(_cell(row, columns, "transfer_fee")) + _to_float(
            _cell(row, columns, "settlement_fee")
        )
        records.append(
            TradeRecord(
                code=code,
                name=name,
                op_type=_classify_op(op_text),
                qty=_to_float(_cell(row, columns, "qty")),
                price=_to_float(_cell(row, columns, "price")),
                amount=_to_float(_cell(row, columns, "amount")),
                balance=_to_float(_cell(row, columns, "balance")),
                fee=fee,
                stamp_tax=_to_float(_cell(row, columns, "stamp_tax")),
                commission=_to_float(_cell(row, columns, "commission")),
                transfer_fee=transfer_fee,
                contract_no=_to_text(_cell(row, columns, "contract_no")),
                trade_date=trade_date,
                currency=_to_text(_cell(row, columns, "currency")),
            )
        )
    return records


def _cell(row: Any, columns: dict[str, int], name: str) -> Any:
    index = columns.get(name)
    if index is None:
        return None
    return row.iloc[index]


def parse_trades(path: str | os.PathLike[str]) -> list[TradeRecord]:
    """解析交割单文件，返回 ``TradeRecord`` 列表。

    支持 .xlsx（openpyxl）、.xls（xlrd，尽力而为）、.csv（utf-8/gbk 自动尝试）。
    文件不存在、不可解析或缺少必需列时抛出 ``ParseError``（中文信息）。
    """
    file_path = Path(path)
    if not file_path.exists():
        raise ParseError(f"文件不存在：{file_path}")
    if file_path.is_dir():
        raise ParseError(f"路径是目录而非文件：{file_path}")
    try:
        raw = _read_table(file_path)
    except ParseError:
        raise
    except Exception as exc:
        raise ParseError(f"无法解析文件 {file_path}：{exc}") from exc
    return _rows_to_records(raw, str(file_path))
