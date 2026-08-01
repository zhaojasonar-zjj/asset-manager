"""组合管理模块

持仓重建、市值计算、每日资产快照、历史资产曲线。
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .database import Database
from .price_fetcher import fetch_realtime_prices, fetch_history_close_prices


def recalculate_holdings(transactions: pd.DataFrame) -> list[dict]:
    """根据交割单重建当前持仓（加权平均成本法）

    返回: [{broker, stock_code, stock_name, quantity, cost_price, total_cost}]
    """
    if transactions.empty:
        return []

    tx_sorted = transactions.sort_values("trade_date").reset_index(drop=True)
    holdings: dict[str, dict] = {}

    for _, tx in tx_sorted.iterrows():
        code = str(tx["stock_code"]).strip().zfill(6)
        if code not in holdings:
            holdings[code] = {
                "broker": tx.get("broker", ""),
                "stock_code": code,
                "stock_name": tx.get("stock_name", ""),
                "quantity": 0.0,
                "total_cost": 0.0,
            }

        qty = float(tx["quantity"])
        settlement = abs(float(tx.get("settlement", 0)))
        # 如果 settlement 为 0，用 amount + fees 代替
        if settlement == 0:
            settlement = abs(float(tx.get("amount", 0))) + abs(float(tx.get("commission", 0))) + \
                         abs(float(tx.get("stamp_tax", 0))) + abs(float(tx.get("transfer_fee", 0)))
        trade_type = str(tx.get("trade_type", ""))

        if "买" in trade_type:
            holdings[code]["quantity"] += qty
            holdings[code]["total_cost"] += settlement
        elif "卖" in trade_type:
            current_qty = holdings[code]["quantity"]
            if current_qty <= 0:
                continue
            sell_qty = min(qty, current_qty)
            avg_cost = holdings[code]["total_cost"] / current_qty
            holdings[code]["quantity"] -= sell_qty
            holdings[code]["total_cost"] -= avg_cost * sell_qty

    result = []
    for h in holdings.values():
        if h["quantity"] > 0.001:  # 过滤极小残余
            h["cost_price"] = round(h["total_cost"] / h["quantity"], 4)
            h["quantity"] = round(h["quantity"], 0)
            h["total_cost"] = round(h["total_cost"], 2)
            result.append(h)

    return result


def calculate_market_value(holdings: pd.DataFrame, prices: dict) -> tuple[float, float, list[dict], bool]:
    """计算持仓市值

    返回: (total_market_value, total_pnl, enriched_holdings, all_prices_ok)
    """
    total_mv = 0.0
    total_pnl = 0.0
    enriched = []
    all_prices_ok = True

    for _, row in holdings.iterrows():
        code = str(row["stock_code"]).strip().zfill(6)
        price_info = prices.get(code, {})
        current_price = price_info.get("price", 0)

        # 如果实时价格为 0（接口失败），用成本价做 fallback
        if current_price <= 0:
            current_price = float(row.get("cost_price", 0))
            all_prices_ok = False

        quantity = float(row["quantity"])
        cost_price = float(row["cost_price"])
        total_cost = float(row["total_cost"])

        market_value = quantity * current_price
        pnl = market_value - total_cost
        pnl_pct = (pnl / total_cost * 100) if total_cost > 0 else 0
        today_change = price_info.get("change_pct", 0)

        total_mv += market_value
        total_pnl += pnl

        enriched.append(
            {
                "stock_code": code,
                "stock_name": row.get("stock_name", "") or price_info.get("name", ""),
                "quantity": quantity,
                "cost_price": cost_price,
                "current_price": current_price,
                "market_value": round(market_value, 2),
                "total_cost": total_cost,
                "pnl": round(pnl, 2),
                "pnl_pct": round(pnl_pct, 2),
                "today_change": today_change,
                "prev_close": price_info.get("prev_close", 0),
                "price_source": "实时" if price_info.get("price", 0) > 0 else "成本价",
            }
        )

    return round(total_mv, 2), round(total_pnl, 2), enriched, all_prices_ok


def get_current_holdings_codes(db: Database) -> list[str]:
    """获取当前持仓的所有股票代码"""
    holdings = db.get_holdings()
    if holdings.empty:
        return []
    return holdings["stock_code"].unique().tolist()


def take_daily_snapshot(db: Database, prices: dict | None = None) -> dict | None:
    """记录当日资产快照

    如果今日已有快照则更新，否则新建。
    返回快照数据 dict 或 None。
    """
    today = datetime.now().strftime("%Y-%m-%d")
    cash = db.get_cash_balance()

    holdings = db.get_holdings()
    if holdings.empty:
        market_value = 0.0
    else:
        if prices is None:
            codes = holdings["stock_code"].unique().tolist()
            prices = fetch_realtime_prices(codes)
        market_value, _, _, _ = calculate_market_value(holdings, prices)

    total_assets = cash + market_value
    deposits = db.get_total_deposits()
    net_value = round(total_assets / deposits, 4) if deposits > 0 else None

    snapshot = {
        "date": today,
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "total_assets": round(total_assets, 2),
        "net_value": net_value,
    }

    db.save_daily_asset(today, cash, market_value, total_assets, net_value)
    return snapshot


def build_asset_history(db: Database) -> pd.DataFrame:
    """构建资产历史数据

    合并来源：每日快照表 + 资金流水推算的历史现金
    """
    # 1. 获取已保存的每日快照
    snapshots = db.get_daily_assets()

    # 2. 从资金流水获取历史现金余额
    fund_flows = db.get_fund_flows()

    histories = []

    # 从资金流水中提取每日现金余额
    if not fund_flows.empty:
        ff = fund_flows.sort_values("flow_date").copy()
        ff["flow_date"] = ff["flow_date"].astype(str)
        # 取每天最后一条记录的余额
        daily_cash = ff.groupby("flow_date")["balance"].last().reset_index()
        daily_cash.columns = ["date", "cash"]
        daily_cash = daily_cash[daily_cash["cash"].notna()]
        for _, row in daily_cash.iterrows():
            histories.append(
                {
                    "date": row["date"],
                    "cash_balance": row["cash"],
                    "market_value": 0,
                    "total_assets": row["cash"],
                    "net_value": None,
                    "source": "fund_flow",
                }
            )

    # 从每日快照中获取
    if not snapshots.empty:
        for _, row in snapshots.iterrows():
            histories.append(
                {
                    "date": row["snapshot_date"],
                    "cash_balance": row["cash_balance"],
                    "market_value": row["market_value"],
                    "total_assets": row["total_assets"],
                    "net_value": row["net_value"],
                    "source": "snapshot",
                }
            )

    if not histories:
        return pd.DataFrame()

    df = pd.DataFrame(histories)
    # 同一日期：snapshot 优先于 fund_flow
    df = df.sort_values(["date", "source"], ascending=[True, False])
    df = df.drop_duplicates(subset="date", keep="first")
    df = df.sort_values("date").reset_index(drop=True)

    # 填充 net_value
    deposits = db.get_total_deposits()
    if deposits > 0:
        df["net_value"] = df["net_value"].fillna(df["total_assets"] / deposits)

    return df


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
