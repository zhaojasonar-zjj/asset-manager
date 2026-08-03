"""Excel 文件解析模块（基于真实券商格式重写）

支持：
- 国泰君安交割单：交收日期/交易类别/资金发生数/资金余额
- 华泰证券交割单：成交日期/业务名称/发生金额/操作
- 华泰证券资金明细：日期/摘要/借方(收入)/贷方(支出)/资金余额
- 华泰证券每周资产：持仓日期/证券代码/证券名称/持仓数量/收盘价/持仓市值
"""
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import re


# ── 工具函数 ──────────────────────────────────────────────

def _normalize_col(col) -> str:
    """列名标准化：去除首尾空格、换行符，NaN → 空字符串"""
    if col is None or (isinstance(col, float) and pd.isna(col)):
        return ""
    return str(col).strip().replace("\n", "").replace("  ", " ")


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """规范化所有列名"""
    df.columns = [_normalize_col(c) for c in df.columns]
    return df


def _parse_date(val) -> str:
    """各种日期格式统一为 'YYYY-MM-DD' 字符串"""
    if pd.isna(val):
        return ""
    if isinstance(val, (int, float)):
        val = str(int(val))
    val = str(val).strip()
    # 20230103 格式
    if re.match(r"^\d{8}$", val):
        return f"{val[:4]}-{val[4:6]}-{val[6:8]}"
    # 2023-01-03 或 2023/01/03
    val = val.replace("/", "-")
    if re.match(r"^\d{4}-\d{2}-\d{2}", val):
        return val[:10]
    # 截取前 10 位
    return val[:10] if len(val) >= 10 else val


def _to_float(val) -> float:
    """安全转 float"""
    if pd.isna(val):
        return 0.0
    if isinstance(val, str):
        val = val.replace(",", "").replace("，", "").strip()
        if not val or val == "--":
            return 0.0
        try:
            return float(val)
        except ValueError:
            return 0.0
    return float(val)


def _extract_stock_info_from_summary(summary: str) -> tuple[str, str]:
    """从华泰资金明细的'摘要'字段提取证券代码和名称

    例: '证券买入601318中国平安' → ('601318', '中国平安')
        '证券买入601658邮储银行' → ('601658', '邮储银行')
    """
    if not summary:
        return "", ""
    # 匹配：数字+中文
    m = re.match(r".*?(\d{6})(.+)", summary)
    if m:
        return m.group(1), m.group(2).strip()
    return "", ""


def _normalize_trade_type(raw: str) -> str:
    """统一交易类别为 买入/卖出/其他"""
    if not raw:
        return "其他"
    raw = str(raw)
    if "买入" in raw or "买入" in raw:
        if "卖出" in raw:
            return "卖出"
        return "买入"
    if "卖出" in raw:
        return "卖出"
    return "其他"


# ── 国泰君安交割单 ────────────────────────────────────────

def parse_guojun_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """解析国泰君安交割单

    真实列名（第一行即表头，无合并单元格）：
    交收日期, 合同号, 资金账号, 股东代码, 证券代码, 证券名称,
    交易类别, 成交价格, 成交数量, 证券余额, 成交金额, 资金发生数,
    资金余额, 费用合计, 佣金, 规费, 印花税, 过户费, ...

    特点：
    - 交收日期格式: '20230103' (字符串)
    - 交易类别: '上海A股普通股票竞价买入' / '上海跨市场股票ETF竞价卖出'
    - 资金发生数: 买入为负，卖出为正 (即结算金额，已含手续费)
    - 资金余额: 该笔交易后的账户余额
    - 成交数量: 始终为正数
    """
    df = _normalize_columns(df.copy())

    # 过滤空行
    df = df.dropna(subset=["交收日期", "证券代码"], how="all")
    df = df[df["交收日期"].astype(str).str.match(r"^\d{8}$", na=False)]

    if df.empty:
        return pd.DataFrame()

    result = pd.DataFrame({
        "trade_date":   df["交收日期"].apply(_parse_date),
        "stock_code":   df["证券代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6),
        "stock_name":   df["证券名称"].astype(str).str.strip(),
        "trade_type":   df["交易类别"].apply(_normalize_trade_type),
        "quantity":     df["成交数量"].apply(_to_float).abs(),
        "price":        df["成交价格"].apply(_to_float),
        "amount":       df["成交金额"].apply(_to_float).abs(),
        "commission":   df.get("佣金", pd.Series(dtype=float)).apply(_to_float),
        "stamp_tax":    df.get("印花税", pd.Series(dtype=float)).apply(_to_float),
        "transfer_fee": df.get("过户费", pd.Series(dtype=float)).apply(_to_float),
        "other_fee":    df.get("规费", pd.Series(dtype=float)).apply(_to_float),
        "settlement":   df["资金发生数"].apply(_to_float),
        "asset_type":   "stock",
    })

    # 合并所有费用为 other_fee（规费 + 经手费 + 清算费 + 前台费用 + 交易规费 + 证管费）
    for extra_col in ["经手费", "清算费", "前台费用", "交易规费", "证管费"]:
        if extra_col in df.columns:
            result["other_fee"] += df[extra_col].apply(_to_float)

    # ── 保留银行转存/转取记录（证券代码非数字，如 \t）──
    bank_mask = df["交易类别"].astype(str).str.contains("证券转银行|银行转证券", na=False)
    if bank_mask.any():
        bank_rows = result[bank_mask].copy()
        bank_rows["stock_code"] = "BANK"
        bank_rows["stock_name"] = df.loc[bank_mask, "交易类别"].astype(str).str.strip()
        bank_rows["trade_type"] = "其他"
        bank_rows["quantity"] = 0.0

    # 过滤无效行（6位数字代码 + 数量>0），但保留银行转存记录
    normal_mask = (result["stock_code"].str.match(r"^\d{6}$", na=False)) & (result["quantity"] > 0)
    if bank_mask.any():
        result = pd.concat([result[normal_mask], bank_rows], ignore_index=True)
    else:
        result = result[normal_mask]

    return result.reset_index(drop=True)


# ── 华泰证券交割单 ────────────────────────────────────────

def parse_huatai_transactions(df: pd.DataFrame) -> pd.DataFrame:
    """解析华泰证券交割单

    真实列名（第一行即表头）：
    成交日期, 业务名称, 证券代码, 证券名称, 委托编号, 成交数量, 成交均价,
    成交金额, 手续费, 印花税, 过户费, 其他杂费, 发生金额, 股东代码, 操作, 备注

    业务名称分类：
    - 证券买入 / 证券卖出          → 正常买卖
    - 股息入帐 / 股息红利税补缴     → 分红
    - 申购配号                     → 新股配号（不产生持仓，不计资金）
    - 市值申购中签                  → 中签通知（不产生持仓，不计资金）
    - 交收资金冻结 / 交收资金冻结取消 → 申购资金冻结/解冻（不产生持仓）
    - 托管转出                     → 申购代码转出（不产生持仓）
    - 新股申购确认缴款              → 真正扣款买入！产生持仓
    - 新股入帐                     → 转入正式代码（不重复计持仓）
    - 基金资金拨出 / 基金资金拨入    → 货币基金申赎
    - 质押回购拆出 / 拆出质押购回   → 国债逆回购
    """
    df = _normalize_columns(df.copy())

    # 过滤空行
    df = df.dropna(subset=["成交日期", "证券代码"], how="all")
    df = df[df["成交日期"].astype(str).str.match(r"^\d{8}$", na=False)]

    if df.empty:
        return pd.DataFrame()

    # 证券代码统一为 6 位字符串
    def _norm_code(val):
        if pd.isna(val):
            return ""
        s = str(val).replace(".0", "").strip()
        if s.isdigit():
            return s.zfill(6)
        return s

    result = pd.DataFrame({
        "trade_date":   df["成交日期"].apply(_parse_date),
        "stock_code":   df["证券代码"].apply(_norm_code),
        "stock_name":   df["证券名称"].astype(str).str.strip(),
        "biz_name":     df["业务名称"].astype(str).str.strip(),
        "trade_type":   df["操作"].apply(_normalize_trade_type),
        "quantity":     df["成交数量"].apply(_to_float).abs(),
        "price":        df["成交均价"].apply(_to_float),
        "amount":       df["成交金额"].apply(_to_float).abs(),
        "commission":   df["手续费"].apply(_to_float),
        "stamp_tax":    df["印花税"].apply(_to_float),
        "transfer_fee": df["过户费"].apply(_to_float),
        "other_fee":    df["其他杂费"].apply(_to_float),
        "settlement":   df["发生金额"].apply(_to_float),
    })

    # 过滤无效代码
    result = result[result["stock_code"].str.match(r"^\d{6}$", na=False)]

    # ── 根据 biz_name 分类，设置 trade_type 和 asset_type ───
    # "证券买入" / "新股申购确认缴款" → 买入（产生持仓）
    # "证券卖出" → 卖出
    # "基金资金拨出" → 货币基金申购 → 买入, cash_like
    # "基金资金拨入" → 货币基金赎回 → 卖出, cash_like
    # "质押回购拆出" → 国债逆回购拆出 → 买入, cash_like
    # "拆出质押购回" → 国债逆回购购回 → 卖出, cash_like
    # 其他全部标记为 "其他"（不参与持仓重建）
    def _classify(row):
        biz = row["biz_name"]
        if biz in ("证券买入", "新股申购确认缴款"):
            return pd.Series(["买入", "stock"])
        if biz == "证券卖出":
            return pd.Series(["卖出", "stock"])
        if "基金资金拨出" in biz:
            return pd.Series(["买入", "cash_like"])
        if "基金资金拨入" in biz:
            return pd.Series(["卖出", "cash_like"])
        if "质押回购拆出" in biz:
            return pd.Series(["买入", "cash_like"])
        if "拆出质押购回" in biz:
            return pd.Series(["卖出", "cash_like"])
        return pd.Series(["其他", "stock"])

    result[["trade_type", "asset_type"]] = result.apply(_classify, axis=1)

    # 过滤掉 quantity=0 且 settlement=0 的纯通知记录（如市值申购中签、交收资金冻结/解冻）
    # 但保留 settlement≠0 的记录（如新股申购确认缴款有 settlement）
    result = result[(result["quantity"] > 0) | (result["settlement"] != 0)]

    # ── 新股申购代码 → 正式代码映射 ──────────────────────────
    # 通过「新股入帐」记录建立映射（入帐记录的代码为正式代码）
    # 再通过同数量、同价格匹配对应的「新股申购确认缴款」记录（代码为申购代码）
    entries = result[result["biz_name"] == "新股入帐"]
    for _, entry in entries.iterrows():
        formal_code = str(entry["stock_code"]).strip().zfill(6)
        entry_qty = float(entry["quantity"])
        entry_price = float(entry["price"])
        # 找匹配的确认缴款记录
        confirms = result[
            (result["biz_name"] == "新股申购确认缴款")
            & (result["quantity"] == entry_qty)
            & (result["price"] == entry_price)
        ]
        for _, conf in confirms.iterrows():
            purchase_code = str(conf["stock_code"]).strip().zfill(6)
            if purchase_code != formal_code:
                # 替换所有该申购代码的记录为正式代码
                result.loc[result["stock_code"] == purchase_code, "stock_code"] = formal_code

    # 删除「新股入帐」记录（避免在持仓重建中重复计算）
    # 这些记录的 amount=0, settlement=0，不携带资金信息
    result = result[result["biz_name"] != "新股入帐"].reset_index(drop=True)

    return result


# ── 华泰证券资金明细 ──────────────────────────────────────

def parse_huatai_fund_flows(df: pd.DataFrame) -> pd.DataFrame:
    """解析华泰证券资金明细

    真实列名（第一行即表头）：
    日期, 摘要, 借方(收入), 贷方(支出), 资金余额, 货币单位, 备注

    特点：
    - 日期: 20220711 (整数)
    - 摘要: '银行转存[招行存管]' / '银行转取[交行存管]' / '证券买入601318中国平安' / '基金资金拨出'
    - 借方(收入): 有值表示资金流入 (正数)
    - 贷方(支出): 有值表示资金流出 (需取负数)
    - 资金余额: 该笔交易后的账户余额
    """
    df = _normalize_columns(df.copy())

    # 过滤空行
    df = df.dropna(subset=["日期"], how="all")
    df = df[df["日期"].astype(str).str.match(r"^\d{8}$", na=False)]

    if df.empty:
        return pd.DataFrame()

    # 合并借方/贷方为统一 amount 字段
    amounts = []
    for _, row in df.iterrows():
        inflow = _to_float(row.get("借方(收入)"))
        outflow = _to_float(row.get("贷方(支出)"))
        if inflow != 0:
            amounts.append(inflow)
        elif outflow != 0:
            amounts.append(-outflow)
        else:
            amounts.append(0.0)

    # 从摘要中提取证券代码和名称
    stock_codes = []
    stock_names = []
    for summary in df["摘要"].astype(str):
        code, name = _extract_stock_info_from_summary(summary)
        stock_codes.append(code)
        stock_names.append(name)

    result = pd.DataFrame({
        "flow_date":   df["日期"].apply(_parse_date),
        "flow_type":   df["摘要"].astype(str).str.strip(),
        "stock_code":  stock_codes,
        "stock_name":  stock_names,
        "amount":      amounts,
        "balance":     df["资金余额"].apply(_to_float),
        "description": df.get("备注", pd.Series([""] * len(df))).astype(str),
    })

    return result.reset_index(drop=True)


# ── 华泰证券每周资产 ──────────────────────────────────────

def parse_huatai_weekly_assets(df: pd.DataFrame) -> pd.DataFrame:
    """解析华泰证券每周资产文件

    列名：持仓日期, 证券代码, 证券名称, 持仓数量, 收盘价, 持仓市值

    数据结构：
    - 每个日期一组行，包含股票持仓、货币基金、现金
    - "小计" 行的持仓市值 = 该日总资产
    - "银证转入" 行记录当日的银证转账金额
    - 股票行的证券代码为 NaN，证券名称为股票名称

    返回 DataFrame 列:
      date, stock_name, quantity, close_price, market_value, row_type
      row_type: 'stock' | 'cash' | 'cash_like' | 'subtotal' | 'bank_transfer'
    """
    df = _normalize_columns(df.copy())

    # 过滤空行
    df = df.dropna(subset=["持仓日期"], how="all")
    if df.empty:
        return pd.DataFrame()

    records = []
    for _, row in df.iterrows():
        date_str = _parse_date(row["持仓日期"])
        if not date_str:
            continue

        code = str(row.get("证券代码", "")).strip()
        name = str(row.get("证券名称", "")).strip()
        if name == "nan":
            name = ""
        qty = _to_float(row.get("持仓数量"))
        close_price = _to_float(row.get("收盘价"))
        mv = _to_float(row.get("持仓市值"))

        if code == "小计":
            row_type = "subtotal"
        elif code == "银证转入":
            row_type = "bank_transfer"
        elif name == "现金":
            row_type = "cash"
        elif name == "货币基金":
            row_type = "cash_like"
        elif name and mv != 0:
            row_type = "stock"
        else:
            continue

        records.append({
            "date": date_str,
            "stock_name": name,
            "quantity": qty,
            "close_price": close_price,
            "market_value": mv,
            "row_type": row_type,
        })

    if not records:
        return pd.DataFrame()

    result = pd.DataFrame(records)
    # 按日期排序
    result = result.sort_values(["date", "row_type"]).reset_index(drop=True)
    return result


def summarize_weekly_assets(weekly_df: pd.DataFrame) -> pd.DataFrame:
    """将每周资产明细汇总为每日快照

    返回: [{date, stock_value, cash_like_value, cash_balance, total_assets}]
    """
    if weekly_df.empty:
        return pd.DataFrame()

    records = []
    for date, group in weekly_df.groupby("date"):
        stock_value = group.loc[group["row_type"] == "stock", "market_value"].sum()
        cash_like_value = group.loc[group["row_type"] == "cash_like", "market_value"].sum()
        cash_balance = group.loc[group["row_type"] == "cash", "market_value"].sum()
        subtotal = group.loc[group["row_type"] == "subtotal", "market_value"].sum()
        bank_transfer = group.loc[group["row_type"] == "bank_transfer", "market_value"].sum()

        if subtotal == 0:
            # 没有小计行（如首日只有银证转入），用成分加总
            subtotal = stock_value + cash_like_value + cash_balance
            if subtotal == 0 and bank_transfer > 0:
                # 首日只有银证转入，总资产 = 转入金额
                subtotal = bank_transfer

        records.append({
            "date": date,
            "stock_value": round(stock_value, 2),
            "cash_like_value": round(cash_like_value, 2),
            "cash_balance": round(cash_balance, 2),
            "total_assets": round(subtotal, 2),
        })

    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


# ── 自动识别 & 路由 ────────────────────────────────────────

def detect_format(df: pd.DataFrame) -> str:
    """根据列名自动识别格式

    返回: 'gtja_transactions' / 'huatai_transactions' / 'huatai_fund_flows' / 'huatai_weekly_assets' / 'unknown'
    """
    cols = set(_normalize_col(c) for c in df.columns)

    # 国泰君安交割单：有 交收日期 + 交易类别
    if "交收日期" in cols and "交易类别" in cols:
        return "gtja_transactions"

    # 华泰交割单：有 成交日期 + 业务名称 + 发生金额
    if "成交日期" in cols and "业务名称" in cols and "发生金额" in cols:
        return "huatai_transactions"

    # 华泰资金明细：有 日期 + 摘要 + 借方/贷方
    if "日期" in cols and "摘要" in cols and ("借方(收入)" in cols or "贷方(支出)" in cols):
        return "huatai_fund_flows"

    # 华泰每周资产：有 持仓日期 + 持仓市值
    if "持仓日期" in cols and "持仓市值" in cols:
        return "huatai_weekly_assets"

    return "unknown"


def read_excel_robust(path: str | Path) -> list[tuple[str, pd.DataFrame]]:
    """读取 Excel 所有 sheet，返回 [(sheet_name, df), ...]

    自动处理：跳过空 sheet、列名规范化。
    """
    path = Path(path)
    sheets = pd.read_excel(path, sheet_name=None, header=0)
    result = []
    for name, df in sheets.items():
        if df.empty:
            continue
        df = _normalize_columns(df)
        # 去掉全空的列
        df = df.dropna(axis=1, how="all")
        result.append((name, df))
    return result


def parse_excel_file(path: str | Path) -> list[dict]:
    """解析 Excel 文件，自动识别格式

    返回: [{"format": str, "data": pd.DataFrame, "sheet": str}, ...]
    """
    sheets = read_excel_robust(path)
    results = []

    for sheet_name, df in sheets:
        fmt = detect_format(df)
        if fmt == "gtja_transactions":
            parsed = parse_guojun_transactions(df)
            if not parsed.empty:
                results.append({"format": fmt, "data": parsed, "sheet": sheet_name})
        elif fmt == "huatai_transactions":
            parsed = parse_huatai_transactions(df)
            if not parsed.empty:
                results.append({"format": fmt, "data": parsed, "sheet": sheet_name})
        elif fmt == "huatai_fund_flows":
            parsed = parse_huatai_fund_flows(df)
            if not parsed.empty:
                results.append({"format": fmt, "data": parsed, "sheet": sheet_name})
        elif fmt == "huatai_weekly_assets":
            parsed = parse_huatai_weekly_assets(df)
            if not parsed.empty:
                results.append({"format": fmt, "data": parsed, "sheet": sheet_name})

    return results
