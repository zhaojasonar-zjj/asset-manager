"""持仓明细页面 — 持仓、成本分析"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

from core.database import Database
from core.price_fetcher import fetch_realtime_prices
from core.portfolio import calculate_market_value

st.set_page_config(page_title="持仓明细", page_icon="📈", layout="wide")

st.markdown("# 📈 持仓明细")

db = Database()

# ── 检查数据 ─────────────────────────────────────────────
holdings = db.get_holdings()
if holdings.empty:
    st.warning("暂无持仓数据，请先导入交割单。")
    st.stop()

# ── 实时行情 ─────────────────────────────────────────────
codes = holdings["stock_code"].unique().tolist()
with st.spinner("正在获取实时行情..."):
    prices = fetch_realtime_prices(codes)

market_value, total_pnl, enriched, prices_ok = calculate_market_value(holdings, prices)

if not prices_ok:
    st.warning("⚠️ 部分股票实时行情获取失败，最新价使用成本价估算。")

# ── 汇总卡片 ────────────────────────────────────────────
st.markdown("### 💰 持仓概览")

total_cost = sum(h["total_cost"] for h in enriched)
total_pnl_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("持仓市值", f"¥ {market_value:,.2f}")
col2.metric("持仓成本", f"¥ {total_cost:,.2f}")
col3.metric("累计盈亏", f"¥ {total_pnl:,.2f}", f"{total_pnl_pct:+.2f}%")
col4.metric("持仓股票数", f"{len(enriched)}")

# ── 持仓表格 ────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 持仓列表")

df = pd.DataFrame(enriched)

# 按市值排序
df = df.sort_values("market_value", ascending=False)

# 格式化显示
df_display = df.copy()
df_display["cost_price"] = df_display["cost_price"].apply(lambda x: f"{x:.3f}")
df_display["current_price"] = df_display["current_price"].apply(lambda x: f"{x:.2f}")
df_display["market_value"] = df_display["market_value"].apply(lambda x: f"¥ {x:,.2f}")
df_display["total_cost"] = df_display["total_cost"].apply(lambda x: f"¥ {x:,.2f}")
df_display["pnl"] = df_display["pnl"].apply(lambda x: f"¥ {x:,.2f}")
df_display["pnl_pct"] = df_display["pnl_pct"].apply(lambda x: f"{x:+.2f}%")
df_display["today_change"] = df_display["today_change"].apply(lambda x: f"{x:+.2f}%")

# 持仓占比
total_mv = df["market_value"].sum()
df_display["weight"] = (df["market_value"] / total_mv * 100).apply(lambda x: f"{x:.1f}%")

display_cols = {
    "stock_code": "代码",
    "stock_name": "名称",
    "quantity": "数量",
    "cost_price": "成本价",
    "current_price": "最新价",
    "today_change": "今日涨跌",
    "market_value": "市值",
    "weight": "占比",
    "total_cost": "成本",
    "pnl": "盈亏",
    "pnl_pct": "盈亏%",
}
df_display = df_display[list(display_cols.keys())].rename(columns=display_cols)
st.dataframe(df_display, use_container_width=True, hide_index=True)

# ── 可视化 ──────────────────────────────────────────────
st.markdown("---")

col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.markdown("### 🥧 持仓占比")

    # 只显示市值 > 0 的
    pie_data = df[df["market_value"] > 0].copy()
    if not pie_data.empty:
        fig_pie = go.Figure(
            data=[
                go.Pie(
                    labels=pie_data["stock_name"] + " (" + pie_data["stock_code"] + ")",
                    values=pie_data["market_value"],
                    hole=0.5,
                    textinfo="label+percent",
                    textposition="outside",
                )
            ]
        )
        fig_pie.update_layout(
            height=400,
            margin=dict(l=20, r=20, t=20, b=20),
            showlegend=False,
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("暂无可显示的持仓")

with col_chart2:
    st.markdown("### 📊 盈亏对比")

    pnl_data = df[df["pnl"] != 0].copy()
    if not pnl_data.empty:
        pnl_data["color"] = pnl_data["pnl"].apply(lambda x: "#16a34a" if x >= 0 else "#dc2626")
        fig_bar = go.Figure(
            data=[
                go.Bar(
                    x=pnl_data["stock_name"] + " (" + pnl_data["stock_code"] + ")",
                    y=pnl_data["pnl"],
                    marker_color=pnl_data["color"],
                    text=pnl_data["pnl"].apply(lambda x: f"¥ {x:,.0f}"),
                    textposition="auto",
                )
            ]
        )
        fig_bar.update_layout(
            height=400,
            xaxis_title="",
            yaxis_title="盈亏 (¥)",
            margin=dict(l=20, r=20, t=20, b=80),
            xaxis_tickangle=-30,
        )
        st.plotly_chart(fig_bar, use_container_width=True)
    else:
        st.info("暂无盈亏数据")

# ── 交易明细 ────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📜 交易明细")

transactions = db.get_transactions()
if not transactions.empty:
    tx_display = transactions.copy()
    tx_display["trade_date"] = tx_display["trade_date"].astype(str)
    tx_display["price"] = tx_display["price"].apply(lambda x: f"{x:.3f}")
    tx_display["amount"] = tx_display["amount"].apply(lambda x: f"¥ {x:,.2f}")
    tx_display["settlement"] = tx_display["settlement"].apply(lambda x: f"¥ {x:,.2f}")
    tx_display["commission"] = tx_display["commission"].apply(lambda x: f"¥ {x:,.2f}")
    tx_display["stamp_tax"] = tx_display["stamp_tax"].apply(lambda x: f"¥ {x:,.2f}")

    show_cols = {
        "trade_date": "日期",
        "stock_code": "代码",
        "stock_name": "名称",
        "trade_type": "买卖",
        "quantity": "数量",
        "price": "价格",
        "amount": "金额",
        "commission": "手续费",
        "stamp_tax": "印花税",
        "settlement": "结算金额",
        "broker": "券商",
    }
    available = [c for c in show_cols if c in tx_display.columns]
    tx_display = tx_display[available].rename(columns=show_cols)
    st.dataframe(tx_display, use_container_width=True, hide_index=True, height=400)
else:
    st.info("暂无交易记录")
