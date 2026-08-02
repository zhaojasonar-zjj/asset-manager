"""组合管理模块（多账户版）

持仓重建、市值计算、资产快照、历史资产曲线。
所有操作按 account_id 隔离。
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .database import Database
from .price_fetcher import fetch_realtime_prices, fetch_history_close_prices


def recalculate_holdings(transactions: pd.DataFrame) -> list[dict]:
    """根据交割单重建当前持仓（加权平均成本法）

    新股申购代码→正式代码的映射已在解析器层面完成。
    返回: [{stock_code, stock_name, quantity, cost_price, total_cost}]
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


def calculate_market_value(holdings: pd.DataFrame, prices: dict) -> tuple[float, float, pd.DataFrame, bool]:
    """计算持仓市值

    返回: (market_value, total_pnl, enriched_holdings, prices_ok)
    """
    if holdings.empty:
        return 0.0, 0.0, holdings, True

    enriched = holdings.copy()
    enriched["latest_price"] = 0.0
    enriched["market_value"] = 0.0
    enriched["pnl"] = 0.0
    enriched["pnl_pct"] = 0.0

    prices_ok = True
    for idx, row in enriched.iterrows():
        code = str(row["stock_code"]).strip().zfill(6)
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

    market_value = enriched["market_value"].sum()
    total_pnl = enriched["pnl"].sum()

    return market_value, total_pnl, enriched, prices_ok


def take_daily_snapshot(db: Database, account_id: int):
    """为指定账户生成今日资产快照"""
    holdings = db.get_holdings(account_id)
    cash = db.get_cash_balance(account_id)

    if not holdings.empty:
        codes = holdings["stock_code"].unique().tolist()
        prices = fetch_realtime_prices(codes)
        market_value, _, _, _ = calculate_market_value(holdings, prices)
    else:
        market_value = 0.0

    total_assets = cash + market_value
    deposits = db.get_total_deposits(account_id)
    net_value = total_assets / deposits if deposits > 0 else None

    today = datetime.now().strftime("%Y-%m-%d")
    db.save_daily_asset(account_id, today, cash, market_value, total_assets, net_value)


def build_asset_history(db: Database, account_id: int) -> pd.DataFrame:
    """构建历史资产曲线

    数据来源优先级：
    1. daily_assets 表中的历史快照
    2. 从资金流水 + 交易记录推算
    """
    # 先取已有快照
    snapshots = db.get_daily_assets(account_id)

    if not snapshots.empty:
        return snapshots

    # 没有快照，从资金流水推算
    fund_flows = db.get_fund_flows(account_id)
    if fund_flows.empty:
        return pd.DataFrame()

    # 按日期聚合每日余额
    ff = fund_flows.copy()
    ff["flow_date"] = ff["flow_date"].astype(str)
    daily = ff.groupby("flow_date").agg(
        cash_balance=("balance", "last"),
    ).reset_index().sort_values("flow_date")

    daily = daily.rename(columns={"flow_date": "date"})
    daily["market_value"] = 0.0
    daily["total_assets"] = daily["cash_balance"] + daily["market_value"]

    deposits = db.get_total_deposits(account_id)
    if deposits > 0:
        daily["net_value"] = daily["total_assets"] / deposits
    else:
        daily["net_value"] = None

    return daily


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
