"""Excel 文件解析模块

支持多券商交割单、对账单、资金明细单的自动识别与解析。
核心思路：通过列名同义词模糊匹配，将不同券商格式映射到统一字段。
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime


# ── 列名同义词表 ──────────────────────────────────────────

TRANSACTION_COL_MAP = {
    "trade_date":   ["成交日期", "委托日期", "交易日期", "日期", "发生日期", "业务日期", "清算日期", "交收日期"],
    "stock_code":   ["证券代码", "股票代码", "代码", "证券号", "标的代码"],
    "stock_name":   ["证券名称", "股票名称", "名称", "证券简称", "标的名称"],
    "trade_type":   ["买卖方向", "操作", "买卖类别", "委托方向", "业务名称", "交易类别", "方向", "操作方向", "交易类型"],
    "quantity":     ["成交数量", "委托数量", "数量", "成交股数", "成交单位数", "委托数量"],
    "price":        ["成交价格", "成交均价", "价格", "均价", "成交单价", "委托价格", "申报价格"],
    "amount":       ["成交金额", "金额", "成交总金额"],
    "commission":   ["手续费", "佣金", "手续费金额", "佣金费用", "手续费费"],
    "stamp_tax":    ["印花税", "印花税费", "印花"],
    "transfer_fee": ["过户费", "过户费金额", "沪市过户费", "结算过户费"],
    "other_fee":    ["其他费用", "其他费", "附加费", "其他", "其他杂费"],
    "settlement":   ["结算金额", "清算金额", "结算资金", "资金发生额", "收付金额"],
}

FUND_FLOW_COL_MAP = {
    "flow_date":   ["日期", "发生日期", "交易日期", "业务日期", "资金日期", "清算日期", "委托日期", "操作日期"],
    "flow_type":   ["业务类型", "业务名称", "交易类型", "操作", "业务摘要", "类型", "摘要", "操作类型", "操作方向", "交易类别", "业务种类"],
    "amount":      ["发生金额", "金额", "变动金额", "资金发生额", "收付金额", "发生额", "本次金额", "资金变动", "资金变动金额", "变动额", "成交金额"],
    "balance":     ["资金余额", "余额", "账户余额", "当前余额", "本次余额", "资金余额", "期末余额", "实时余额"],
    "description": ["备注", "说明", "描述", "信息", "详细", "摘要说明"],
    "stock_code":  ["证券代码", "股票代码", "代码", "标的代码"],
    "stock_name":  ["证券名称", "股票名称", "名称", "标的名称"],
}

# 金额列候选——用于资金明细中多种金额字段的识别
AMOUNT_CANDIDATES = [
    "发生金额", "金额", "变动金额", "资金发生额", "收付金额",
    "发生额", "本次金额", "资金变动", "变动额", "成交金额",
]


# ── 工具函数 ──────────────────────────────────────────────

def _normalize_header(h) -> str:
    """去除表头中的空格、换行等，确保返回字符串"""
    if h is None:
        return ""
    try:
        if pd.isna(h):
            return ""
    except (TypeError, ValueError):
        pass
    s = str(h).strip().replace(" ", "").replace("\n", "").replace("\r", "").replace("\t", "")
    if s.lower() in ("nan", "none", "nat", ""):
        return ""
    return s


def _find_header_row(df: pd.DataFrame, max_rows: int = 20) -> int:
    """在前 max_rows 行中寻找表头行（包含最多已知列名的行）"""
    keywords = [
        "证券代码", "股票代码", "成交日期", "日期", "买卖", "操作",
        "数量", "价格", "金额", "余额", "业务", "发生金额", "结算",
        "资金", "清算", "委托", "交易类型", "摘要",
    ]
    best_row, best_score = 0, 0
    for i in range(min(max_rows, len(df))):
        try:
            row_values = [str(v).strip() for v in df.iloc[i].tolist()]
        except Exception:
            continue
        score = sum(1 for v in row_values if v and v.lower() != "nan" and any(kw in v for kw in keywords))
        if score > best_score:
            best_score = score
            best_row = i
    return best_row


def _match_columns(headers: list, col_map: dict) -> dict:
    """将 Excel 列名匹配到标准字段名

    策略：先精确匹配，再包含匹配。每个标准字段只取第一个匹配的列。
    """
    normalized = [_normalize_header(h) for h in headers]
    mapping = {}

    # 第一轮：精确匹配
    for standard_name, synonyms in col_map.items():
        for syn in synonyms:
            syn_clean = _normalize_header(syn)
            if not syn_clean:
                continue
            for i, h in enumerate(normalized):
                if not h:
                    continue
                if h == syn_clean and i not in mapping.values():
                    mapping[standard_name] = i
                    break
        if standard_name in mapping:
            continue

    # 第二轮：包含匹配（短列名在长列名中查找）
    for standard_name, synonyms in col_map.items():
        if standard_name in mapping:
            continue
        for syn in synonyms:
            syn_clean = _normalize_header(syn)
            if not syn_clean or len(syn_clean) < 2:
                continue
            for i, h in enumerate(normalized):
                if not h or i in mapping.values():
                    continue
                try:
                    if syn_clean in h or h in syn_clean:
                        mapping[standard_name] = i
                        break
                except TypeError:
                    continue
        if standard_name in mapping:
            continue

    return mapping


def _normalize_trade_type(t: str) -> str:
    """统一买卖方向"""
    t = str(t)
    if "买" in t:
        return "买入"
    if "卖" in t:
        return "卖出"
    return t.strip()


def _parse_date(val) -> str:
    """将日期值统一为 YYYY-MM-DD 字符串"""
    if val is None:
        return ""
    try:
        if pd.isna(val):
            return ""
    except (TypeError, ValueError):
        pass
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    if isinstance(val, pd.Timestamp):
        return val.strftime("%Y-%m-%d")
    s = str(val).strip()
    if not s or s.lower() in ("nan", "none", "nat"):
        return ""
    # 处理 Excel 数字日期
    try:
        if s.replace(".", "").isdigit():
            n = float(s)
            if 30000 < n < 80000:
                return (datetime(1899, 12, 30) + pd.Timedelta(days=n)).strftime("%Y-%m-%d")
    except Exception:
        pass
    # 处理各种日期格式
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d", "%Y年%m月%d日", "%m/%d/%Y", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # 尝试 pandas 解析
    try:
        ts = pd.to_datetime(s)
        if pd.notna(ts):
            return ts.strftime("%Y-%m-%d")
    except Exception:
        pass
    return s


def _to_float(val) -> float:
    """安全转浮点数"""
    if val is None:
        return 0.0
    try:
        if pd.isna(val):
            return 0.0
    except (TypeError, ValueError):
        pass
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace(",", "").replace("，", "").replace(" ", "").replace("¥", "").replace("￥", "")
    if s in ("", "-", "nan", "NaN", "None", "null", "--"):
        return 0.0
    # 处理带正负号的金额
    try:
        return float(s)
    except ValueError:
        # 尝试提取数字部分
        import re
        m = re.search(r"-?[\d.]+", s)
        if m:
            try:
                return float(m.group())
            except ValueError:
                pass
        return 0.0


# ── 自动检测文件类型 ────────────────────────────────────

def detect_file_type(df: pd.DataFrame) -> str:
    """根据列名判断文件类型：transactions / fund_flows / unknown

    判定规则：
    - 含有「成交数量」「成交价格」等交易特有列 → transactions
    - 含有「资金余额」「发生金额」等资金特有列 → fund_flows
    - 同时含两组时，看谁得分高
    """
    headers = [_normalize_header(h) for h in df.columns.tolist()]

    # 交易单特有关键词（成交数量、成交价格等不会出现在资金明细中）
    tx_strong_keywords = ["成交数量", "成交价格", "成交均价", "委托数量", "成交股数", "买卖方向", "买卖类别"]
    # 资金明细特有关键词（资金余额不会出现在交割单中）
    ff_strong_keywords = ["资金余额", "余额", "账户余额", "当前余额", "本次余额"]

    tx_score = sum(1 for h in headers if h and any(kw in h for kw in tx_strong_keywords))
    ff_score = sum(1 for h in headers if h and any(kw in h for kw in ff_strong_keywords))

    # 强信号优先
    if ff_score >= 1 and tx_score == 0:
        return "fund_flows"
    if tx_score >= 1 and ff_score == 0:
        return "transactions"

    # 模糊匹配
    tx_weak_keywords = ["证券代码", "股票代码", "成交金额", "结算金额"]
    ff_weak_keywords = ["发生金额", "业务类型", "业务名称", "交易类型", "操作类型", "摘要", "变动金额"]

    tx_score += sum(1 for h in headers if h and any(kw in h for kw in tx_weak_keywords))
    ff_score += sum(1 for h in headers if h and any(kw in h for kw in ff_weak_keywords))

    if tx_score >= 2 and tx_score > ff_score:
        return "transactions"
    if ff_score >= 2 and ff_score >= tx_score:
        return "fund_flows"
    if tx_score >= 1:
        return "transactions"
    return "unknown"


def detect_broker(df: pd.DataFrame, filename: str = "") -> str:
    """尝试从文件名或内容中识别券商"""
    name = (filename or "").lower()
    broker_hints = {
        "华泰": ["华泰", "htsc", "huatai"],
        "中信": ["中信", "citics"],
        "国泰君安": ["国泰君安", "gtja", "guotai"],
        "海通": ["海通", "haitong", "htsec"],
        "广发": ["广发", "gfzq", "gfqs"],
        "招商": ["招商", "cmschina", "招商证券"],
        "东方财富": ["东方财富", "eastmoney"],
        "平安": ["平安", "pingan"],
        "银河": ["银河", "chinastock"],
        "申万": ["申万", "sws"],
    }
    for broker, hints in broker_hints.items():
        for hint in hints:
            if hint.lower() in name:
                return broker
    return "通用"


# ── 解析入口 ─────────────────────────────────────────────

def read_excel_robust(file_path: str | Path) -> list[tuple[str, pd.DataFrame]]:
    """稳健读取 Excel/CSV，处理表头行偏移，返回 [(sheet_name, df)]"""
    file_path = Path(file_path)
    sheets = []

    if file_path.suffix.lower() == ".csv":
        df = pd.read_csv(file_path, dtype=str)
        header_row = _find_header_row(df)
        new_cols = []
        for c in df.iloc[header_row].tolist():
            col_name = _normalize_header(c)
            if not col_name:
                col_name = f"col_{len(new_cols)}"
            new_cols.append(col_name)
        df.columns = new_cols
        df = df.iloc[header_row + 1:].reset_index(drop=True)
        df = df.dropna(how="all")
        if not df.empty:
            sheets.append(("csv", df))
    elif file_path.suffix.lower() in (".xls", ".xlsx", ".xlsm"):
        xls = pd.ExcelFile(file_path)
        for sheet_name in xls.sheet_names:
            raw = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
            if raw.empty:
                continue
            header_row = _find_header_row(raw)
            new_cols = []
            for c in raw.iloc[header_row].tolist():
                col_name = _normalize_header(c)
                if not col_name:
                    col_name = f"col_{len(new_cols)}"
                new_cols.append(col_name)
            raw.columns = new_cols
            raw = raw.iloc[header_row + 1:].reset_index(drop=True)
            raw = raw.dropna(how="all")
            if not raw.empty:
                sheets.append((sheet_name, raw))
    else:
        raise ValueError(f"不支持的文件格式: {file_path.suffix}")

    return sheets


def parse_transactions(df: pd.DataFrame, broker: str = "通用") -> pd.DataFrame:
    """解析交割单，返回标准 DataFrame"""
    mapping = _match_columns(df.columns.tolist(), TRANSACTION_COL_MAP)

    required = ["trade_date", "stock_code", "quantity", "price"]
    missing = [f for f in required if f not in mapping]
    if missing:
        raise ValueError(
            f"交割单缺少必要列: {missing}\n"
            f"已识别列: {list(mapping.keys())}\n"
            f"原始列名: {df.columns.tolist()}"
        )

    n = len(df)
    data = {}
    data["broker"] = [broker] * n
    data["trade_date"] = df.iloc[:, mapping["trade_date"]].apply(_parse_date).values
    data["stock_code"] = df.iloc[:, mapping["stock_code"]].apply(lambda x: str(x).strip().zfill(6)).values
    if "stock_name" in mapping:
        data["stock_name"] = df.iloc[:, mapping["stock_name"]].astype(str).str.strip().values
    else:
        data["stock_name"] = [""] * n
    if "trade_type" in mapping:
        data["trade_type"] = df.iloc[:, mapping["trade_type"]].apply(_normalize_trade_type).values
    else:
        data["trade_type"] = [""] * n
    qty = df.iloc[:, mapping["quantity"]].apply(_to_float).values
    price = df.iloc[:, mapping["price"]].apply(_to_float).values
    data["quantity"] = qty
    data["price"] = price
    if "amount" in mapping:
        data["amount"] = df.iloc[:, mapping["amount"]].apply(_to_float).values
    else:
        data["amount"] = [q * p for q, p in zip(qty, price)]
    data["commission"] = df.iloc[:, mapping["commission"]].apply(_to_float).values if "commission" in mapping else [0.0] * n
    data["stamp_tax"] = df.iloc[:, mapping["stamp_tax"]].apply(_to_float).values if "stamp_tax" in mapping else [0.0] * n
    data["transfer_fee"] = df.iloc[:, mapping["transfer_fee"]].apply(_to_float).values if "transfer_fee" in mapping else [0.0] * n
    data["other_fee"] = df.iloc[:, mapping["other_fee"]].apply(_to_float).values if "other_fee" in mapping else [0.0] * n
    if "settlement" in mapping:
        data["settlement"] = df.iloc[:, mapping["settlement"]].apply(_to_float).values
    else:
        # 没有结算金额列，用成交金额 + 各项费用计算
        fees = (data["commission"] + data["stamp_tax"] + data["transfer_fee"] + data["other_fee"])
        data["settlement"] = [
            a + f if t and "买" in t else a - f
            for a, f, t in zip(data["amount"], fees, data["trade_type"])
        ]

    result = pd.DataFrame(data)

    # 标准化结算金额符号：买入为负，卖出为正
    buy_mask = result["trade_type"] == "买入"
    sell_mask = result["trade_type"] == "卖出"
    result.loc[buy_mask, "settlement"] = -result.loc[buy_mask, "settlement"].abs()
    result.loc[sell_mask, "settlement"] = result.loc[sell_mask, "settlement"].abs()

    # 过滤无效行
    result = result[result["stock_code"].str.match(r"^\d{6}$", na=False)]
    result = result[result["quantity"] != 0]

    return result.reset_index(drop=True)


def parse_fund_flows(df: pd.DataFrame, broker: str = "通用") -> pd.DataFrame:
    """解析资金明细单，返回标准 DataFrame

    特殊处理：如果找不到 amount 列，尝试从多个候选金额列中选取。
    """
    mapping = _match_columns(df.columns.tolist(), FUND_FLOW_COL_MAP)

    required = ["flow_date"]
    missing = [f for f in required if f not in mapping]
    if missing:
        raise ValueError(
            f"资金明细单缺少必要列: {missing}\n"
            f"已识别列: {list(mapping.keys())}\n"
            f"原始列名: {df.columns.tolist()}"
        )

    # 如果没有找到 amount 列，尝试从候选金额列中找
    if "amount" not in mapping:
        headers = [_normalize_header(h) for h in df.columns.tolist()]
        for i, h in enumerate(headers):
            if not h or i in mapping.values():
                continue
            for cand in AMOUNT_CANDIDATES:
                if _normalize_header(cand) in h:
                    mapping["amount"] = i
                    break
            if "amount" in mapping:
                break

    n = len(df)
    data = {}
    data["broker"] = [broker] * n
    data["flow_date"] = df.iloc[:, mapping["flow_date"]].apply(_parse_date).values
    if "flow_type" in mapping:
        data["flow_type"] = df.iloc[:, mapping["flow_type"]].astype(str).str.strip().values
    else:
        data["flow_type"] = [""] * n
    if "amount" in mapping:
        data["amount"] = df.iloc[:, mapping["amount"]].apply(_to_float).values
    else:
        # 实在没有金额列，报错
        raise ValueError(
            f"资金明细单未找到金额列\n"
            f"已识别列: {list(mapping.keys())}\n"
            f"原始列名: {df.columns.tolist()}\n"
            f"需要以下任一列: {AMOUNT_CANDIDATES}"
        )
    if "balance" in mapping:
        data["balance"] = df.iloc[:, mapping["balance"]].apply(_to_float).values
    else:
        data["balance"] = [None] * n
    if "description" in mapping:
        data["description"] = df.iloc[:, mapping["description"]].astype(str).str.strip().values
    else:
        data["description"] = [""] * n
    if "stock_code" in mapping:
        data["stock_code"] = df.iloc[:, mapping["stock_code"]].apply(lambda x: str(x).strip().zfill(6) if str(x).strip() else "").values
    else:
        data["stock_code"] = [""] * n
    if "stock_name" in mapping:
        data["stock_name"] = df.iloc[:, mapping["stock_name"]].astype(str).str.strip().values
    else:
        data["stock_name"] = [""] * n

    result = pd.DataFrame(data)

    # 过滤无效行
    result = result[result["flow_date"] != ""]
    result = result[result["amount"] != 0]

    return result.reset_index(drop=True)


def parse_excel_file(file_path: str | Path, broker: str = "通用") -> list[dict]:
    """解析 Excel 文件，返回 [{'file_type': ..., 'data': DataFrame, 'sheet': ...}]"""
    sheets = read_excel_robust(file_path)
    results = []

    for sheet_name, df in sheets:
        try:
            file_type = detect_file_type(df)

            if file_type == "transactions":
                try:
                    parsed = parse_transactions(df, broker)
                    if not parsed.empty:
                        results.append({"file_type": "transactions", "data": parsed, "sheet": sheet_name})
                except Exception:
                    # 交割单解析失败，尝试资金明细
                    try:
                        parsed_ff = parse_fund_flows(df, broker)
                        if not parsed_ff.empty:
                            results.append({"file_type": "fund_flows", "data": parsed_ff, "sheet": sheet_name})
                    except Exception:
                        pass
            elif file_type == "fund_flows":
                try:
                    parsed = parse_fund_flows(df, broker)
                    if not parsed.empty:
                        results.append({"file_type": "fund_flows", "data": parsed, "sheet": sheet_name})
                except Exception:
                    # 资金明细解析失败，尝试交割单
                    try:
                        parsed_tx = parse_transactions(df, broker)
                        if not parsed_tx.empty:
                            results.append({"file_type": "transactions", "data": parsed_tx, "sheet": sheet_name})
                    except Exception:
                        pass
            else:
                # unknown: 尝试两种解析
                try:
                    parsed_tx = parse_transactions(df, broker)
                    if not parsed_tx.empty:
                        results.append({"file_type": "transactions", "data": parsed_tx, "sheet": sheet_name})
                except Exception:
                    pass
                try:
                    parsed_ff = parse_fund_flows(df, broker)
                    if not parsed_ff.empty:
                        results.append({"file_type": "fund_flows", "data": parsed_ff, "sheet": sheet_name})
                except Exception:
                    pass
        except Exception as e:
            raise type(e)(
                f"[Sheet: {sheet_name}] {e}\n"
                f"Columns: {df.columns.tolist()}\n"
                f"Shape: {df.shape}"
            ) from e

    return results
