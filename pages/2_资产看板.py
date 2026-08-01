"""资产看板 — 持仓、资产曲线、净值曲线"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from core.database import Database
from core.price_fetcher import fetch_realtime_prices
from core.portfolio import (
    calculate_market_value,
    take_daily_snapshot,
    build_asset_history,
)

st.set_page_config(page_title="资产看板", page_icon="📊", layout="wide")

st.markdown("# 📊 资产看板")

db = Database()

# ── 检查是否有数据 ───────────────────────────────────────
tx_count = db.get_transaction_count()
if tx_count == 0 and db.get_fund_flow_count() == 0:
    st.warning("暂无数据，请先前往「数据上传」页面导入交割单或资金明细单。")
    st.stop()

# ── 获取数据 ─────────────────────────────────────────────
holdings = db.get_holdings()
cash = db.get_cash_balance()
deposits = db.get_total_deposits()

# ── 实时行情 ─────────────────────────────────────────────
prices = {}
if not holdings.empty:
    codes = holdings["stock_code"].unique().tolist()
    with st.spinner("正在获取实时行情..."):
        prices = fetch_realtime_prices(codes)

# ── 记录今日快照 ─────────────────────────────────────────
snapshot = take_daily_snapshot(db, prices)

# ── 计算市值 ─────────────────────────────────────────────
if not holdings.empty:
    market_value, total_pnl, enriched_holdings = calculate_market_value(holdings, prices)
else:
    market_value, total_pnl, enriched_holdings = 0, 0, []

total_assets = cash + market_value
net_value = total_assets / deposits if deposits > 0 else 0
pnl_pct = (total_pnl / (market_value - total_pnl) * 100) if (market_value - total_pnl) > 0 else 0

# ── KPI 卡片 ────────────────────────────────────────────
st.markdown("### 💰 资产概览")

col1, col2, col3, col4 = st.columns(4)
col1.metric("总资产", f"¥ {total_assets:,.2f}")
col2.metric("现金余额", f"¥ {cash:,.2f}")
col3.metric("持仓市值", f"¥ {market_value:,.2f}")
col4.metric("累计盈亏", f"¥ {total_pnl:,.2f}", f"{pnl_pct:+.2f}%")

st.markdown("")

col5, col6, col7, col8 = st.columns(4)
col5.metric("累计净转入", f"¥ {deposits:,.2f}")
col6.metric("净值", f"{net_value:.4f}", f"{(net_value - 1) * 100:+.2f}%")
col7.metric("持仓股票数", f"{len(holdings)}")
today_str = datetime.now().strftime("%Y-%m-%d %H:%M")
col8.metric("数据更新", today_str)

# ── 持仓列表 ────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📈 持仓列表")

if enriched_holdings:
    df_holdings = pd.DataFrame(enriched_holdings)

    # 格式化显示
    df_display = df_holdings.copy()
    df_display["current_price"] = df_display["current_price"].apply(lambda x: f"{x:.2f}")
    df_display["market_value"] = df_display["market_value"].apply(lambda x: f"¥ {x:,.2f}")
    df_display["total_cost"] = df_display["total_cost"].apply(lambda x: f"¥ {x:,.2f}")
    df_display["pnl"] = df_display["pnl"].apply(lambda x: f"¥ {x:,.2f}")
    df_display["pnl_pct"] = df_display["pnl_pct"].apply(lambda x: f"{x:+.2f}%")
    df_display["today_change"] = df_display["today_change"].apply(lambda x: f"{x:+.2f}%")

    display_cols = {
        "stock_code": "代码",
        "stock_name": "名称",
        "quantity": "持仓数量",
        "cost_price": "成本价",
        "current_price": "最新价",
        "market_value": "市值",
        "total_cost": "持仓成本",
        "pnl": "盈亏",
        "pnl_pct": "盈亏%",
        "today_change": "今日涨跌",
    }
    df_display = df_display[list(display_cols.keys())].rename(columns=display_cols)
    st.dataframe(df_display, use_container_width=True, hide_index=True)
else:
    st.info("暂无持仓数据")

# ── 资产曲线 ────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📉 历史资产曲线")

asset_history = build_asset_history(db)

if asset_history.empty:
    st.info("暂无历史资产数据。系统会在每次查看看板时自动记录当日资产快照。")
else:
    col_chart1, col_chart2 = st.columns([3, 2])

    with col_chart1:
        # 总资产曲线
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=asset_history["date"],
                y=asset_history["total_assets"],
                mode="lines+markers",
                name="总资产",
                line=dict(color="#2563eb", width=2),
                fill="tozeroy",
                fillcolor="rgba(37, 99, 235, 0.1)",
                hovertemplate="日期: %{x}<br>总资产: ¥%{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=asset_history["date"],
                y=asset_history["cash_balance"],
                mode="lines",
                name="现金",
                line=dict(color="#16a34a", width=1.5, dash="dot"),
                hovertemplate="日期: %{x}<br>现金: ¥%{y:,.2f}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=asset_history["date"],
                y=asset_history["market_value"],
                mode="lines",
                name="市值",
                line=dict(color="#d97706", width=1.5, dash="dot"),
                hovertemplate="日期: %{x}<br>市值: ¥%{y:,.2f}<extra></extra>",
            )
        )
        fig.update_layout(
            title="总资产趋势",
            xaxis_title="日期",
            yaxis_title="金额 (¥)",
            height=400,
            hovermode="x unified",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(l=20, r=20, t=50, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_chart2:
        # 净值曲线
        if "net_value" in asset_history.columns and asset_history["net_value"].notna().any():
            fig_nv = go.Figure()
            fig_nv.add_trace(
                go.Scatter(
                    x=asset_history["date"],
                    y=asset_history["net_value"],
                    mode="lines+markers",
                    name="净值",
                    line=dict(color="#8b5cf6", width=2),
                    fill="tozeroy",
                    fillcolor="rgba(139, 92, 246, 0.1)",
                    hovertemplate="日期: %{x}<br>净值: %{y:.4f}<extra></extra>",
                )
            )
            # 基准线 1.0
            fig_nv.add_hline(
                y=1.0,
                line_dash="dash",
                line_color="#94a3b8",
                annotation_text="基准线 1.0",
            )
            fig_nv.update_layout(
                title="净值曲线",
                xaxis_title="日期",
                yaxis_title="净值",
                height=400,
                hovermode="x unified",
                margin=dict(l=20, r=20, t=50, b=20),
            )
            st.plotly_chart(fig_nv, use_container_width=True)
        else:
            st.info("净值数据需要资金流水中有银行转入/转出记录来计算累计净转入资金。")

# ── 每日资产明细表 ──────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 每日资产明细")

if not asset_history.empty:
    display_history = asset_history.copy()
    display_history["cash_balance"] = display_history["cash_balance"].apply(lambda x: f"¥ {x:,.2f}")
    display_history["market_value"] = display_history["market_value"].apply(lambda x: f"¥ {x:,.2f}")
    display_history["total_assets"] = display_history["total_assets"].apply(lambda x: f"¥ {x:,.2f}")
    if "net_value" in display_history.columns:
        display_history["net_value"] = display_history["net_value"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) else "-"
        )
    display_history = display_history.sort_values("date", ascending=False)
    st.dataframe(display_history, use_container_width=True, hide_index=True)
else:
    st.info("暂无每日资产记录")
