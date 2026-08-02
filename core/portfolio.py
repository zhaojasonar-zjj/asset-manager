"""组合管理模块（多账户版）

持仓重建、市值计算、资产快照、历史资产曲线。
所有操作按 account_id 隔离。
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from .database import Database
from .price_fetcher import fetch_realtime_prices, fetch_history_close_prices, fetch_history_kline


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

    策略：从资金流水取每日现金余额，从交割单重建每日持仓，
    再用历史收盘价计算每日市值。
    """
    # 先取已有快照
    snapshots = db.get_daily_assets(account_id)
    if not snapshots.empty:
        return snapshots

    # 没有快照，从数据推算
    fund_flows = db.get_fund_flows(account_id)
    transactions = db.get_transactions(account_id)

    if fund_flows.empty and transactions.empty:
        return pd.DataFrame()

    # ── 1. 每日现金余额（来自资金流水）──────────────────────
    if not fund_flows.empty:
        ff = fund_flows.copy()
        ff["flow_date"] = ff["flow_date"].astype(str)
        daily_cash = ff.groupby("flow_date").agg(
            cash_balance=("balance", "last"),
        ).reset_index().sort_values("flow_date")
    else:
        # 没有资金明细，现金余额从交割单 settlement 推算
        tx = transactions.copy()
        tx["trade_date"] = tx["trade_date"].astype(str)
        daily_cash = tx.groupby("trade_date").agg(
            cash_balance=("settlement", "sum"),
        ).reset_index().sort_values("trade_date")
        # settlement 是累计的，需要 cumsum
        daily_cash["cash_balance"] = daily_cash["cash_balance"].cumsum()

    # 确保列名为 date
    date_col = [c for c in daily_cash.columns if c != "cash_balance"][0]
    daily_cash = daily_cash.rename(columns={date_col: "date"})

    # ── 2. 重建每日持仓 ─────────────────────────────────────
    # 按日期排序交易记录，逐日累加持仓
    if not transactions.empty:
        tx = transactions[transactions["trade_type"].isin(["买入", "卖出"])].copy()
        tx["trade_date"] = tx["trade_date"].astype(str)
        tx = tx.sort_values("trade_date").reset_index(drop=True)

        # 收集所有交易日期
        all_dates = sorted(set(daily_cash["date"].tolist()) | set(tx["trade_date"].tolist()))

        # 逐日持仓快照
        daily_holdings: dict[str, dict[str, float]] = {}  # {date: {code: quantity}}
        current_h: dict[str, float] = {}

        for d in all_dates:
            day_tx = tx[tx["trade_date"] == d]
            for _, row in day_tx.iterrows():
                code = str(row["stock_code"]).strip().zfill(6)
                qty = float(row["quantity"])
                if code not in current_h:
                    current_h[code] = 0.0
                if row["trade_type"] == "买入":
                    current_h[code] += qty
                elif row["trade_type"] == "卖出":
                    current_h[code] -= qty
            # 记录当日持仓快照（只保留 >0 的）
            daily_holdings[d] = {c: q for c, q in current_h.items() if q > 0.01}
    else:
        all_dates = daily_cash["date"].tolist()
        daily_holdings = {d: {} for d in all_dates}

    # ── 3. 获取历史收盘价，计算每日市值 ────────────────────
    # 收集所有需要的股票代码
    all_codes = set()
    for holdings in daily_holdings.values():
        all_codes.update(holdings.keys())

    # 获取每只股票的历史收盘价
    code_price_map: dict[str, dict[str, float]] = {}  # {code: {date: close_price}}
    if all_codes and all_dates:
        for code in all_codes:
            kline = fetch_history_kline(code, min(all_dates).replace("-", ""), max(all_dates).replace("-", ""), 400)
            code_price_map[code] = {item["date"]: item["close"] for item in kline}

    # 计算每日市值
    daily_market_values = []
    for d in all_dates:
        mv = 0.0
        for code, qty in daily_holdings.get(d, {}).items():
            price = code_price_map.get(code, {}).get(d, 0)
            mv += price * qty
        daily_market_values.append({"date": d, "market_value": round(mv, 2)})

    daily_mv_df = pd.DataFrame(daily_market_values)

    # ── 4. 合并现金和市值 ──────────────────────────────────
    if not daily_mv_df.empty:
        daily = daily_cash.merge(daily_mv_df, on="date", how="outer").sort_values("date")
    else:
        daily = daily_cash.copy()
        daily["market_value"] = 0.0

    # 前向填充现金余额（非交易日保持上一日余额）
    daily["cash_balance"] = daily["cash_balance"].ffill().fillna(0)
    daily["market_value"] = daily["market_value"].fillna(0)
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
