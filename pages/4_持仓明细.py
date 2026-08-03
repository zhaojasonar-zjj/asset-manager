"""持仓明细页面 — 多账户版"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from core.database import Database
from core.price_fetcher import fetch_realtime_prices
from core.portfolio import calculate_market_value

st.set_page_config(page_title="持仓明细", page_icon="📈", layout="wide")

st.markdown("# 📈 持仓明细")

db = Database()

# ── 账户选择器 ───────────────────────────────────────────
accounts = db.get_all_accounts()
if not accounts:
    st.warning("暂无账户，请先前往「数据上传」创建账户并导入数据。")
    st.stop()

selected = st.selectbox(
    "选择账户",
    accounts,
    format_func=lambda x: f"{x['name']} ({x['broker']})",
)
account_id = selected["id"]

# ── 检查数据 ─────────────────────────────────────────────
holdings = db.get_holdings(account_id)
if holdings.empty:
    st.warning(f"账户「{selected['name']}」暂无持仓数据，请先导入交割单。")
    st.stop()

# ── 实时行情（只拉股票，不拉类现金）──────────────────────
stock_codes = holdings[holdings.get("asset_type", "stock") != "cash_like"]["stock_code"].unique().tolist()
prices = {}
if stock_codes:
    with st.spinner("正在获取实时行情..."):
        prices = fetch_realtime_prices(stock_codes)

stock_value, cash_like_value, market_value, total_pnl, enriched, prices_ok = calculate_market_value(holdings, prices)

if not prices_ok:
    st.warning("⚠️ 部分股票实时行情获取失败，最新价使用成本价估算。")

# ── 汇总卡片 ────────────────────────────────────────────
st.markdown("---")
st.markdown("### 💰 持仓概览")

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("持仓市值", f"¥ {market_value:,.2f}")
col2.metric("股票市值", f"¥ {stock_value:,.2f}")
col3.metric("类现金", f"¥ {cash_like_value:,.2f}")
col4.metric("持仓成本", f"¥ {enriched['total_cost'].sum():,.2f}")
col5.metric("累计盈亏", f"¥ {total_pnl:,.2f}")

# ── 持仓表 ──────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 持仓明细")

display = enriched.copy()
display["cost_price"] = display["cost_price"].apply(lambda x: f"¥ {x:,.4f}")
display["latest_price"] = display["latest_price"].apply(lambda x: f"¥ {x:,.4f}")
display["market_value"] = display["market_value"].apply(lambda x: f"¥ {x:,.2f}")
display["total_cost"] = display["total_cost"].apply(lambda x: f"¥ {x:,.2f}")
display["pnl"] = display["pnl"].apply(lambda x: f"¥ {x:,.2f}")
display["pnl_pct"] = display["pnl_pct"].apply(lambda x: f"{x:+.2f}%")
if "asset_type" in display.columns:
    display["asset_type"] = display["asset_type"].apply(
        lambda x: "类现金" if x == "cash_like" else "股票"
    )

show_cols = {
    "stock_code": "代码",
    "stock_name": "名称",
    "asset_type": "类型",
    "quantity": "持仓数量",
    "cost_price": "成本价",
    "latest_price": "最新价",
    "market_value": "市值",
    "total_cost": "总成本",
    "pnl": "盈亏",
    "pnl_pct": "盈亏%",
}
available = [c for c in show_cols if c in display.columns]
st.dataframe(display[available].rename(columns=show_cols), use_container_width=True, hide_index=True)

# ── 持仓分布饼图 ────────────────────────────────────────
st.markdown("---")
st.markdown("### 🥧 持仓分布")

if not enriched.empty:
    pie_data = enriched.copy()
    pie_data["label"] = pie_data["stock_name"] + " (" + pie_data["stock_code"] + ")"

    fig = go.Figure(data=[go.Pie(
        labels=pie_data["label"],
        values=pie_data["market_value"],
        hole=0.4,
        textinfo="label+percent",
        textposition="outside",
    )])
    fig.update_layout(height=400, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

# ── 交易明细 ────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📝 交易明细")

transactions = db.get_transactions(account_id)
if not transactions.empty:
    tx_display = transactions.copy()
    tx_display["trade_date"] = tx_display["trade_date"].astype(str)
    tx_display["amount"] = tx_display["amount"].apply(lambda x: f"¥ {x:,.2f}")
    tx_display["settlement"] = tx_display["settlement"].apply(lambda x: f"¥ {x:,.2f}")
    tx_display["commission"] = tx_display["commission"].apply(lambda x: f"¥ {x:,.2f}")
    tx_display["stamp_tax"] = tx_display["stamp_tax"].apply(lambda x: f"¥ {x:,.2f}")

    show_cols = {
        "trade_date": "日期",
        "stock_code": "代码",
        "stock_name": "名称",
        "trade_type": "买卖",
        "asset_type": "类型",
        "quantity": "数量",
        "price": "价格",
        "amount": "金额",
        "commission": "手续费",
        "stamp_tax": "印花税",
        "settlement": "结算金额",
    }
    available = [c for c in show_cols if c in tx_display.columns]
    tx_display = tx_display[available].rename(columns=show_cols)
    # 类型列中文化
    if "类型" in tx_display.columns:
        tx_display["类型"] = tx_display["类型"].apply(
            lambda x: "类现金" if x == "cash_like" else "股票"
        )
    tx_display = tx_display.sort_values("日期", ascending=False)
    st.dataframe(tx_display, use_container_width=True, hide_index=True, height=400)
else:
    st.info("暂无交易记录")
