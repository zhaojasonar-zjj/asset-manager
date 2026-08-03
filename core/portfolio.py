"""组合管理模块（多账户版）

持仓重建、市值计算、资产快照、历史资产曲线。
所有操作按 account_id 隔离。
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .database import Database
from .price_fetcher import fetch_realtime_prices, fetch_history_close_prices, fetch_history_kline


# ── 常见 A 股名称→代码兜底映射（交易记录中可能没有的常见股票）──
COMMON_NAME_TO_CODE: dict[str, str] = {
    "中国平安": "601318",
    "邮储银行": "601658",
    "工商银行": "601398",
    "建设银行": "601939",
    "农业银行": "601288",
    "中国银行": "601988",
    "交通银行": "601328",
    "招商银行": "600036",
    "兴业银行": "601166",
    "浦发银行": "600000",
    "民生银行": "600016",
    "中信银行": "601998",
    "光大银行": "601818",
    "华夏银行": "600015",
    "北京银行": "601169",
    "南京银行": "601009",
    "宁波银行": "002142",
    "杭州银行": "600926",
    "上海银行": "601229",
    "江苏银行": "600919",
    "苏州银行": "002966",
    "成都银行": "601838",
    "长沙银行": "601577",
    "郑州银行": "002936",
    "青岛银行": "002948",
    "西安银行": "600928",
    "厦门银行": "601187",
    "重庆银行": "601963",
    "沪农商行": "601825",
    "苏农银行": "603323",
    "江阴银行": "002807",
    "张家港行": "002839",
    "无锡银行": "600908",
    "常熟银行": "601128",
    "紫金银行": "601860",
    "瑞丰银行": "601528",
    "青农商行": "002958",
    "中国建筑": "601668",
    "中国中铁": "601390",
    "中国铁建": "601186",
    "中国交建": "601800",
    "中国电建": "601669",
    "中国中冶": "601618",
    "中国石油": "601857",
    "中国石化": "600028",
    "中国海油": "600938",
    "中国神华": "601088",
    "中国铝业": "601600",
    "中国黄金": "600916",
    "山东黄金": "600547",
    "紫金矿业": "601899",
    "中国平安": "601318",
    "中国人寿": "601628",
    "中国太保": "601601",
    "新华保险": "601336",
    "中国电信": "601728",
    "中国移动": "600941",
    "中国联通": "600050",
    "中国中免": "601888",
    "中国神华": "601088",
    "贵州茅台": "600519",
    "五粮液": "000858",
    "洋河股份": "002304",
    "泸州老窖": "000568",
    "山西汾酒": "600809",
    "古井贡酒": "000596",
    "今世缘": "603369",
    "老白干酒": "600559",
    "海尔智家": "600690",
    "美的集团": "000333",
    "格力电器": "000651",
    "海康威视": "002415",
    "京东方A": "000725",
    "万科A": "000002",
    "保利发展": "600048",
    "招商蛇口": "001979",
    "绿地控股": "600606",
    "华夏幸福": "600340",
    "荣盛发展": "002146",
    "金地集团": "600383",
    "宋城演艺": "300144",
    "老凤祥": "600612",
    "爱尔眼科": "300015",
    "白云山": "600332",
    "云南白药": "000538",
    "片仔癀": "600436",
    "同仁堂": "600085",
    "恒瑞医药": "600276",
    "药明康德": "603259",
    "迈瑞医疗": "300760",
    "心脉医疗": "688016",
    "泰格医药": "300347",
    "长春高新": "000661",
    "智飞生物": "300122",
    "沃森生物": "300142",
    "康泰生物": "300601",
    "华兰生物": "002007",
    "上海医药": "601607",
    "华润三九": "000999",
    "白云山": "600332",
    "天士力": "600535",
    "康缘药业": "600557",
    "以岭药业": "002603",
    "康龙化成": "300759",
    "昭衍新药": "603127",
    "药石科技": "300725",
    "中信金属": "601618",
    "国泰君安": "601211",
    "中信证券": "600030",
    "海通证券": "600837",
    "华泰证券": "601688",
    "广发证券": "000776",
    "东方财富": "300059",
    "招商证券": "600999",
    "兴业证券": "601377",
    "东方证券": "600958",
    "申万宏源": "000166",
    "国信证券": "002736",
    "中金公司": "601995",
    "中国银河": "601881",
    "长城证券": "002939",
    "天风证券": "601162",
    "华林证券": "002945",
    "国元证券": "000728",
    "国海证券": "000750",
    "长江证券": "000783",
    "山西证券": "002500",
    "西部证券": "002673",
    "华安证券": "600909",
    "财通证券": "601108",
    "浙商证券": "601878",
    "东兴证券": "601198",
    "国投资本": "600061",
    "红塔证券": "601236",
    "中泰证券": "600918",
    "中银证券": "601696",
    "锦龙股份": "000712",
    "华鑫股份": "600621",
    "陕西能源": "001286",
    "华润新能": "001248",
    "华电新能": "600930",
    "宝地矿业": "601121",
    "屹唐股份": "688282",
    "星昊医药": "430021",
    "泰金新能": "688813",
    "中国黄金": "600916",
    "菜百股份": "605599",
    "周大生": "002867",
    "巨星科技": "002444",
    "惠科股份": "001399",
    "马可波罗": "001386",
    "300ETF": "510300",
    "H股ETF": "510900",
    "医药ETF": "512010",
    "创业板ETF": "159915",
    "上证50ETF": "510050",
    "中证500ETF": "510500",
    "科创50ETF": "588000",
    "沪深300ETF": "510300",
    "券商ETF": "512000",
    "银行ETF": "512800",
    "消费ETF": "159928",
    "红利ETF": "510880",
}


def recalculate_holdings(transactions: pd.DataFrame) -> list[dict]:
    """根据交割单重建当前持仓（加权平均成本法）

    新股申购代码→正式代码的映射已在解析器层面完成。
    返回: [{stock_code, stock_name, quantity, cost_price, total_cost, asset_type}]
    """
    if transactions.empty:
        return []

    # 只处理买卖交易，过滤掉非交易记录
    tx = transactions[transactions["trade_type"].isin(["买入", "卖出"])].copy()
    if tx.empty:
        return []

    tx_sorted = tx.sort_values("trade_date").reset_index(drop=True)
    holdings: dict[str, dict] = {}

    for _, row in tx_sorted.iterrows():
        code = str(row["stock_code"]).strip().zfill(6)
        qty = float(row["quantity"])
        settlement = float(row.get("settlement", 0))

        if code not in holdings:
            holdings[code] = {
                "stock_code": code,
                "stock_name": row.get("stock_name", ""),
                "quantity": 0.0,
                "total_cost": 0.0,
                "asset_type": row.get("asset_type", "stock"),
            }

        h = holdings[code]
        if row["trade_type"] == "买入":
            # 买入：成本增加（settlement 为负表示扣款，取绝对值）
            buy_cost = abs(settlement) if settlement != 0 else float(row.get("amount", 0))
            h["quantity"] += qty
            h["total_cost"] += buy_cost
            if h["quantity"] > 0:
                h["cost_price"] = h["total_cost"] / h["quantity"]
            else:
                h["cost_price"] = 0
        elif row["trade_type"] == "卖出":
            # 卖出：数量减少，成本按比例减少
            if h["quantity"] > 0:
                ratio = min(qty / h["quantity"], 1.0)
                h["total_cost"] -= h["total_cost"] * ratio
                h["quantity"] -= qty
                if h["quantity"] > 0:
                    h["cost_price"] = h["total_cost"] / h["quantity"]
                else:
                    h["total_cost"] = 0
                    h["cost_price"] = 0

    # 过滤掉数量为 0 或负数的持仓
    result = []
    for h in holdings.values():
        if h["quantity"] > 0.01:  # 容忍浮点误差
            h["quantity"] = round(h["quantity"], 0)
            h["cost_price"] = round(h["total_cost"] / h["quantity"], 4) if h["quantity"] > 0 else 0
            h["total_cost"] = round(h["total_cost"], 2)
            result.append(h)

    return result


def calculate_market_value(holdings: pd.DataFrame, prices: dict) -> tuple[float, float, float, float, pd.DataFrame, bool]:
    """计算持仓市值（拆分股票市值 + 类现金）

    返回: (stock_value, cash_like_value, total_market_value, total_pnl, enriched_holdings, prices_ok)
    """
    if holdings.empty:
        return 0.0, 0.0, 0.0, 0.0, holdings, True

    enriched = holdings.copy()
    # 确保 asset_type 列存在
    if "asset_type" not in enriched.columns:
        enriched["asset_type"] = "stock"
    enriched["latest_price"] = 0.0
    enriched["market_value"] = 0.0
    enriched["pnl"] = 0.0
    enriched["pnl_pct"] = 0.0

    prices_ok = True
    for idx, row in enriched.iterrows():
        code = str(row["stock_code"]).strip().zfill(6)
        asset_type = row["asset_type"]

        if asset_type == "cash_like":
            # 类现金：不拉行情，用成本价（货币基金 NAV≈1.0，逆回购面值）
            latest_price = float(row.get("cost_price", 0))
            enriched.at[idx, "latest_price"] = latest_price
            enriched.at[idx, "market_value"] = latest_price * row["quantity"]
        else:
            price_info = prices.get(code)
            if price_info and price_info.get("price", 0) > 0:
                latest_price = float(price_info["price"])
                enriched.at[idx, "latest_price"] = latest_price
                enriched.at[idx, "market_value"] = latest_price * row["quantity"]
            else:
                # 行情获取失败，用成本价兜底
                latest_price = float(row.get("cost_price", 0))
                enriched.at[idx, "latest_price"] = latest_price
                enriched.at[idx, "market_value"] = latest_price * row["quantity"]
                prices_ok = False

        cost = float(row.get("total_cost", 0))
        mv = float(enriched.at[idx, "market_value"])
        enriched.at[idx, "pnl"] = mv - cost
        enriched.at[idx, "pnl_pct"] = ((mv - cost) / cost * 100) if cost > 0 else 0.0

    stock_value = enriched[enriched["asset_type"] != "cash_like"]["market_value"].sum()
    cash_like_value = enriched[enriched["asset_type"] == "cash_like"]["market_value"].sum()
    total_market_value = enriched["market_value"].sum()
    total_pnl = enriched["pnl"].sum()

    return stock_value, cash_like_value, total_market_value, total_pnl, enriched, prices_ok


def take_daily_snapshot(db: Database, account_id: int):
    """为指定账户生成今日资产快照"""
    holdings = db.get_holdings(account_id)
    cash = db.get_cash_balance(account_id)

    if not holdings.empty:
        # 确保 asset_type 列存在
        if "asset_type" not in holdings.columns:
            holdings["asset_type"] = "stock"
        # 只拉股票行情，cash_like 不拉
        stock_codes = holdings[holdings["asset_type"] != "cash_like"]["stock_code"].unique().tolist()
        prices = fetch_realtime_prices(stock_codes) if stock_codes else {}
        stock_value, cash_like_value, market_value, _, _, _ = calculate_market_value(holdings, prices)
    else:
        stock_value = 0.0
        cash_like_value = 0.0
        market_value = 0.0

    total_assets = cash + market_value
    deposits = db.get_total_deposits(account_id)
    net_value = total_assets / deposits if deposits > 0 else None

    today = datetime.now().strftime("%Y-%m-%d")
    db.save_daily_asset(account_id, today, cash, market_value, total_assets, net_value, cash_like_value)


def build_asset_history(db: Database, account_id: int, force_rebuild: bool = False) -> pd.DataFrame:
    """构建历史资产曲线（按所有 A 股交易日填充）

    策略：
    1. 从资金流水取每日现金余额（前向填充到所有交易日）
    2. 从每周资产持仓明细建立持仓检查点（弥补交割单历史缺失）
    3. 从交割单逐日重建持仓（在检查点之间用交易增量）
    4. 批量获取所有股票的完整 K 线（同时得到交易日历）
    5. 按交易日 × 持仓 × 当日收盘价计算市值（类现金用成本价）
    6. 合并每周资产汇总数据（补充缺失日期 + 校对）
    7. 结果缓存到 daily_assets 表
    """
    # 有缓存且不强制重建 → 直接返回
    if not force_rebuild:
        snapshots = db.get_daily_assets(account_id)
        if not snapshots.empty:
            return snapshots.rename(columns={"snapshot_date": "date"})

    fund_flows = db.get_fund_flows(account_id)
    transactions = db.get_transactions(account_id)
    weekly_assets = db.get_weekly_assets(account_id)
    weekly_holdings = db.get_weekly_holdings(account_id)

    if fund_flows.empty and transactions.empty and weekly_assets.empty and weekly_holdings.empty:
        return pd.DataFrame()

    # ── 0. 准备每周资产汇总 ────────────────────────────────
    weekly_lookup: dict[str, dict] = {}  # date → {stock_value, cash_like_value, cash_balance, total_assets}
    if not weekly_assets.empty:
        for _, row in weekly_assets.iterrows():
            d = str(row["snapshot_date"])
            weekly_lookup[d] = {
                "stock_value": float(row.get("stock_value", 0) or 0),
                "cash_like_value": float(row.get("cash_like_value", 0) or 0),
                "cash_balance": float(row.get("cash_balance", 0) or 0),
                "total_assets": float(row.get("total_assets", 0) or 0),
            }

    # ── 0b. 准备每周持仓检查点 ────────────────────────────
    # 从交易记录建立 股票名称→代码 映射，叠加常见股票兜底映射
    name_to_code: dict[str, str] = {}
    # 先加载常见映射
    name_to_code.update(COMMON_NAME_TO_CODE)
    # 再叠加交易记录中的映射（优先级更高）
    if not transactions.empty:
        for _, tx_row in transactions.iterrows():
            name = str(tx_row.get("stock_name", "")).strip().replace(" ", "")
            code = str(tx_row.get("stock_code", "")).strip().zfill(6)
            if name and code and name != "nan" and code != "nan" and code.isdigit():
                name_to_code[name] = code

    # 创建每周持仓快照: date → {code → {qty, cost, asset_type}}
    weekly_snapshots: dict[str, dict[str, dict]] = {}
    if not weekly_holdings.empty:
        for date, group in weekly_holdings.groupby("snapshot_date"):
            snapshot = {}
            for _, wh_row in group.iterrows():
                name = str(wh_row.get("stock_name", "")).strip().replace(" ", "")
                code = str(wh_row.get("stock_code", "")).strip()
                if not code:
                    code = name_to_code.get(name, "")
                qty = float(wh_row.get("quantity", 0) or 0)
                mv = float(wh_row.get("market_value", 0) or 0)
                if code and mv > 0 and qty > 0:
                    asset_type = wh_row.get("asset_type", "stock")
                    snapshot[code] = {
                        "qty": qty,
                        "cost": mv,  # 用市值作为"成本"（仅影响PnL基准，不影响市值计算）
                        "asset_type": asset_type,
                    }
            if snapshot:
                weekly_snapshots[str(date)] = snapshot

    # ── 1. 每日现金余额 ──────────────────────────────────────
    if not fund_flows.empty:
        ff = fund_flows.copy()
        ff["flow_date"] = ff["flow_date"].astype(str)
        daily_cash = ff.groupby("flow_date").agg(
            cash_balance=("balance", "last"),
        ).reset_index().sort_values("flow_date")
        daily_cash = daily_cash.rename(columns={"flow_date": "date"})
    elif "fund_balance" in transactions.columns:
        # 国泰君安：从交割单的 资金余额 字段取每日现金余额
        tx_fb = transactions[transactions["fund_balance"].notna() & (transactions["fund_balance"] != 0)].copy()
        if not tx_fb.empty:
            tx_fb["trade_date"] = tx_fb["trade_date"].astype(str)
            daily_cash = tx_fb.groupby("trade_date").agg(
                cash_balance=("fund_balance", "last"),
            ).reset_index().sort_values("trade_date")
            daily_cash = daily_cash.rename(columns={"trade_date": "date"})
        else:
            daily_cash = pd.DataFrame(columns=["date", "cash_balance"])
    else:
        # 无资金明细和资金余额，从交割单 settlement 累计推算
        tx = transactions.copy()
        tx["trade_date"] = tx["trade_date"].astype(str)
        daily_cash = tx.groupby("trade_date").agg(
            cash_balance=("settlement", "sum"),
        ).reset_index().sort_values("trade_date")
        daily_cash = daily_cash.rename(columns={"trade_date": "date"})
        daily_cash["cash_balance"] = daily_cash["cash_balance"].cumsum()

    # ── 2. 逐日重建持仓（交割单 + 每周检查点）──────────────
    tx_buy_sell = transactions[transactions["trade_type"].isin(["买入", "卖出"])].copy()
    if not tx_buy_sell.empty:
        tx_buy_sell["trade_date"] = tx_buy_sell["trade_date"].astype(str)
        tx_buy_sell = tx_buy_sell.sort_values("trade_date").reset_index(drop=True)

    # 所有事件日期（资金流水 + 交割单 + 每周快照）
    tx_dates = sorted(set(daily_cash["date"].tolist()) |
                      set(tx_buy_sell["trade_date"].tolist()) if not tx_buy_sell.empty else set())
    if weekly_snapshots:
        tx_dates = sorted(set(tx_dates) | set(weekly_snapshots.keys()))

    # 用最早的每周快照作为初始持仓
    current_h: dict[str, dict] = {}
    if weekly_snapshots:
        earliest_weekly = min(weekly_snapshots.keys())
        current_h = {c: dict(v) for c, v in weekly_snapshots[earliest_weekly].items()}

    # 逐日处理：遇到每周检查点就重置持仓，然后用交割单增量更新
    daily_holdings: dict[str, dict[str, dict]] = {}
    for d in tx_dates:
        # 每周检查点：重置为每周快照（弥补缺失的交割单）
        if d in weekly_snapshots:
            current_h = {c: dict(v) for c, v in weekly_snapshots[d].items()}

        # 应用当日交割单增量
        if not tx_buy_sell.empty:
            day_tx = tx_buy_sell[tx_buy_sell["trade_date"] == d]
            for _, row in day_tx.iterrows():
                code = str(row["stock_code"]).strip().zfill(6)
                qty = float(row["quantity"])
                settlement = float(row.get("settlement", 0))
                if code not in current_h:
                    current_h[code] = {"qty": 0.0, "cost": 0.0, "asset_type": row.get("asset_type", "stock")}
                if row["trade_type"] == "买入":
                    current_h[code]["qty"] += qty
                    current_h[code]["cost"] += abs(settlement) if settlement != 0 else float(row.get("amount", 0))
                elif row["trade_type"] == "卖出":
                    if current_h[code]["qty"] > 0:
                        ratio = min(qty / current_h[code]["qty"], 1.0)
                        current_h[code]["cost"] -= current_h[code]["cost"] * ratio
                        current_h[code]["qty"] -= qty
        daily_holdings[d] = {c: dict(v) for c, v in current_h.items() if v["qty"] > 0.01}

    # ── 3. 获取所有股票的完整 K 线（只拉股票，不拉类现金）──
    code_asset_type: dict[str, str] = {}
    for holdings_snapshot in daily_holdings.values():
        for code, h in holdings_snapshot.items():
            code_asset_type[code] = h.get("asset_type", "stock")

    stock_codes = sorted([c for c, t in code_asset_type.items() if t != "cash_like"])

    code_kline: dict[str, list[dict]] = {}
    all_trading_days: set[str] = set()

    start_d = min(tx_dates) if tx_dates else datetime.now().strftime("%Y-%m-%d")
    end_d = datetime.now().strftime("%Y-%m-%d")

    for code in stock_codes:
        kline = fetch_history_kline(code, start_d, end_d, 640)
        code_kline[code] = kline
        for item in kline:
            all_trading_days.add(item["date"])

    # 交易日历：K线日期 + 每周快照日期
    trading_days = sorted(all_trading_days | set(weekly_lookup.keys()))
    if not trading_days:
        trading_days = sorted(set(daily_cash["date"].tolist()) | set(weekly_lookup.keys()))

    # ── 4. 按交易日计算每日市值 ────────────────────────────
    code_price: dict[str, dict[str, float]] = {}
    for code, kline in code_kline.items():
        code_price[code] = {item["date"]: item["close"] for item in kline}

    records = []
    prev_holdings: dict[str, dict] = {}
    prev_cash = 0.0

    for d in trading_days:
        # 更新当日持仓快照
        if d in daily_holdings:
            prev_holdings = daily_holdings[d]

        # 现金余额：取当日或最近的前一天
        cash_rows = daily_cash[daily_cash["date"] <= d]
        if not cash_rows.empty:
            prev_cash = float(cash_rows.iloc[-1]["cash_balance"])

        # 市值：股票用当日收盘价，类现金用成本价
        stock_mv = 0.0
        cash_like_mv = 0.0
        for code, h in prev_holdings.items():
            if h.get("asset_type", "stock") == "cash_like":
                cash_like_mv += h["cost"]
            else:
                price = code_price.get(code, {}).get(d, 0)
                stock_mv += price * h["qty"]

        mv = stock_mv + cash_like_mv
        total = prev_cash + mv

        # 合并每周资产数据
        data_source = "calc"
        if d in weekly_lookup:
            wa = weekly_lookup[d]
            if total < 1 or (not prev_holdings and prev_cash == 0):
                # 推算为0，直接用每周数据
                stock_mv = wa["stock_value"]
                cash_like_mv = wa["cash_like_value"]
                prev_cash = wa["cash_balance"]
                total = wa["total_assets"]
                data_source = "weekly"
            else:
                data_source = "calc+weekly"

        records.append({
            "date": d,
            "cash_balance": round(prev_cash, 2),
            "market_value": round(mv, 2),
            "cash_like_value": round(cash_like_mv, 2),
            "total_assets": round(total, 2),
            "data_source": data_source,
        })

    # ── 4b. 补充每周资产中独有的日期（K线缺失的交易日）──
    existing_dates = set(r["date"] for r in records)
    for d, wa in weekly_lookup.items():
        if d not in existing_dates:
            records.append({
                "date": d,
                "cash_balance": round(wa["cash_balance"], 2),
                "market_value": round(wa["stock_value"] + wa["cash_like_value"], 2),
                "cash_like_value": round(wa["cash_like_value"], 2),
                "total_assets": round(wa["total_assets"], 2),
                "data_source": "weekly",
            })

    if not records:
        return pd.DataFrame()

    records.sort(key=lambda r: r["date"])

    daily_df = pd.DataFrame(records)
    deposits = db.get_total_deposits(account_id)
    if deposits > 0:
        daily_df["net_value"] = daily_df["total_assets"] / deposits
    else:
        daily_df["net_value"] = None

    # ── 5. 缓存到数据库 ────────────────────────────────────
    cache_records = [
        {k: v for k, v in r.items() if k != "data_source"}
        for r in records
    ]
    db.replace_daily_assets(account_id, cache_records)

    return daily_df


def cross_check_weekly_assets(db: Database, account_id: int, threshold_pct: float = 0.5) -> pd.DataFrame:
    """校对每日资产与每周资产

    对比同一日期的 daily_assets 和 weekly_assets 的 total_assets。
    误差超过 threshold_pct 的标记为 "需核验"。

    返回: DataFrame[date, daily_total, weekly_total, diff, diff_pct, status]
          status: 'ok' | 'warn' | 'no_daily' | 'no_weekly'
    """
    daily = db.get_daily_assets(account_id)
    weekly = db.get_weekly_assets(account_id)

    if daily.empty and weekly.empty:
        return pd.DataFrame()

    daily_map: dict[str, float] = {}
    if not daily.empty:
        for _, row in daily.iterrows():
            daily_map[str(row["snapshot_date"])] = float(row["total_assets"])

    weekly_map: dict[str, float] = {}
    if not weekly.empty:
        for _, row in weekly.iterrows():
            weekly_map[str(row["snapshot_date"])] = float(row["total_assets"])

    all_dates = sorted(set(daily_map.keys()) | set(weekly_map.keys()))

    records = []
    for d in all_dates:
        dt = daily_map.get(d)
        wt = weekly_map.get(d)

        if dt is not None and wt is not None and wt > 0:
            diff = dt - wt
            diff_pct = abs(diff) / wt * 100
            status = "ok" if diff_pct <= threshold_pct else "warn"
        elif dt is not None and wt is None:
            diff = 0
            diff_pct = 0
            status = "no_weekly"
        elif dt is None and wt is not None:
            diff = 0
            diff_pct = 0
            status = "no_daily"
        else:
            continue

        records.append({
            "date": d,
            "daily_total": round(dt, 2) if dt is not None else None,
            "weekly_total": round(wt, 2) if wt is not None else None,
            "diff": round(diff, 2) if dt is not None and wt is not None else None,
            "diff_pct": round(diff_pct, 2) if dt is not None and wt is not None else None,
            "status": status,
        })

    return pd.DataFrame(records)


def get_fund_flow_summary(fund_flows: pd.DataFrame) -> dict:
    """资金流水汇总统计"""
    if fund_flows.empty:
        return {
            "total_inflow": 0,
            "total_outflow": 0,
            "net_flow": 0,
            "latest_balance": 0,
            "record_count": 0,
        }

    inflow = fund_flows[fund_flows["amount"] > 0]["amount"].sum()
    outflow = fund_flows[fund_flows["amount"] < 0]["amount"].sum()

    latest = fund_flows.sort_values(["flow_date", "id"], ascending=[False, False]).iloc[0]
    latest_balance = latest["balance"] if pd.notna(latest.get("balance")) else None

    return {
        "total_inflow": round(inflow, 2),
        "total_outflow": round(outflow, 2),
        "net_flow": round(inflow + outflow, 2),
        "latest_balance": latest_balance,
        "record_count": len(fund_flows),
    }


def get_capital_changes(db: Database, account_id: int) -> pd.DataFrame:
    """获取银行↔证券 资金变动记录

    数据来源：
    - 华泰资金明细：flow_type 含 "银行转存"（转入）/"银行转取"（转出）
    - 国泰君安交割单：stock_code="BANK"，stock_name 含 "证券转银行"/"银行转证券"

    返回: DataFrame[date, type, direction, amount, balance_after, description]
    """
    records = []

    # ── 从资金流水提取 ──
    fund_flows = db.get_fund_flows(account_id)
    if not fund_flows.empty:
        bank_mask = fund_flows["flow_type"].str.contains("银行转存|银行转取", na=False)
        bank_ff = fund_flows[bank_mask].copy()
        for _, row in bank_ff.iterrows():
            amount = float(row["amount"])
            direction = "转入" if amount > 0 else "转出"
            # 提取银行名称，如 "银行转存[招行存管]" → "招行存管"
            flow_type = str(row["flow_type"])
            bank_name = ""
            if "[" in flow_type and "]" in flow_type:
                bank_name = flow_type[flow_type.index("[")+1:flow_type.index("]")]
            records.append({
                "date": str(row["flow_date"]),
                "type": flow_type,
                "direction": direction,
                "amount": round(abs(amount), 2),
                "balance_after": float(row.get("balance", 0) or 0),
                "bank": bank_name,
                "description": str(row.get("description", "")),
            })

    # ── 从交割单提取（国泰君安等）──
    transactions = db.get_transactions(account_id)
    if not transactions.empty:
        bank_tx = transactions[transactions["stock_code"] == "BANK"].copy()
        for _, row in bank_tx.iterrows():
            settlement = float(row["settlement"])
            direction = "转入" if settlement > 0 else "转出"
            name = str(row.get("stock_name", ""))
            records.append({
                "date": str(row["trade_date"]),
                "type": name,
                "direction": direction,
                "amount": round(abs(settlement), 2),
                "balance_after": 0.0,  # 国泰君安交割单中没有余额字段
                "bank": "",
                "description": name,
            })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df = df.sort_values("date").reset_index(drop=True)

    # 计算累计净转入
    df["cumulative"] = df.apply(
        lambda r: r["amount"] if r["direction"] == "转入" else -r["amount"],
        axis=1,
    ).cumsum()

    return df
