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
ff_count = db.get_fund_flow_count()
if tx_count == 0 and ff_count == 0:
    st.warning("暂无数据，请先前往「数据上传」页面导入交割单或资金明细单。")
    st.stop()

# ── 获取数据 ─────────────────────────────────────────────
holdings = db.get_holdings()
cash = db.get_cash_balance()
deposits = db.get_total_deposits()

# 数据来源标识
has_fund_flows = ff_count > 0

# ── 实时行情 ─────────────────────────────────────────────
prices = {}
prices_ok = True
if not holdings.empty:
    codes = holdings["stock_code"].unique().tolist()
    with st.spinner("正在获取实时行情..."):
        prices = fetch_realtime_prices(codes)

# ── 计算市值 ─────────────────────────────────────────────
if not holdings.empty:
    market_value, pnl, enriched, prices_ok = calculate_market_value(holdings, prices)
else:
    market_value = 0
    pnl = 0
    enriched = []

total_assets = cash + market_value
net_value = total_assets / deposits if deposits > 0 else 0
pnl_pct = (pnl / (market_value - pnl) * 100) if (market_value - pnl) > 0 else 0

# ── 概览卡片 ────────────────────────────────────────────
st.markdown("### 💰 资产概览")

col1, col2, col3, col4 = st.columns(4)
col1.metric("总资产", f"¥ {total_assets:,.2f}")
col2.metric("现金余额", f"¥ {cash:,.2f}")
col3.metric("持仓市值", f"¥ {market_value:,.2f}")
col4.metric("累计盈亏", f"¥ {pnl:,.2f}", f"{pnl_pct:+.2f}%")

st.markdown("---")

if deposits > 0:
    col_a, col_b = st.columns(2)
    col_a.metric("累计净转入", f"¥ {deposits:,.2f}")
    col_b.metric("净值", f"{net_value:.4f}", f"{(net_value - 1) * 100:+.2f}%")

# ── 数据来源提示 ────────────────────────────────────────
if not has_fund_flows:
    st.markdown("---")
    st.info(
        "📌 **现金余额** 由交割单推算（累计结算金额），可能不准确。"
        "上传资金明细单可获得准确的现金余额和净值数据。"
    )
if not prices_ok and not holdings.empty:
    st.markdown("---")
    st.warning(
        "⚠️ 部分股票实时行情获取失败，市值使用成本价估算。请稍后刷新页面重试。"
    )

# ── 快照 ────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📸 今日快照")

snapshot = take_daily_snapshot(db, prices if holdings.empty else prices)
if snapshot:
    col1, col2, col3 = st.columns(3)
    col1.metric("快照日期", snapshot["date"])
    col2.metric("快照总资产", f"¥ {snapshot['total_assets']:,.2f}")
    if snapshot.get("net_value"):
        col3.metric("快照净值", f"{snapshot['net_value']:.4f}")

# ── 资产历史曲线 ────────────────────────────────────────
st.markdown("---")
st.markdown("### 📈 资产历史曲线")

asset_history = build_asset_history(db)

if not asset_history.empty:
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
        )
    )
    if asset_history["cash_balance"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=asset_history["date"],
                y=asset_history["cash_balance"],
                mode="lines",
                name="现金",
                line=dict(color="#16a34a", width=1.5, dash="dot"),
            )
        )
    if (asset_history.get("market_value", 0) != 0).any():
        fig.add_trace(
            go.Scatter(
                x=asset_history["date"],
                y=asset_history["market_value"],
                mode="lines",
                name="市值",
                line=dict(color="#f59e0b", width=1.5, dash="dot"),
            )
        )
    fig.update_layout(
        xaxis_title="日期",
        yaxis_title="金额 (¥)",
        height=400,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("暂无历史数据。每日快照会在访问资产看板时自动记录。")

# ── 净值曲线 ────────────────────────────────────────────
if deposits > 0 and not asset_history.empty and asset_history["net_value"].notna().any():
    st.markdown("---")
    st.markdown("### 📊 净值曲线")

    fig_nv = go.Figure()
    fig_nv.add_trace(
        go.Scatter(
            x=asset_history["date"],
            y=asset_history["net_value"],
            mode="lines+markers",
            name="净值",
            line=dict(color="#8b5cf6", width=2),
        )
    )
    fig_nv.add_hline(
        y=1.0,
        line_dash="dash",
        line_color="#94a3b8",
        annotation_text="基准线 1.0",
    )
    fig_nv.update_layout(
        xaxis_title="日期",
        yaxis_title="净值",
        height=350,
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_nv, use_container_width=True)
elif not has_fund_flows:
    st.markdown("---")
    st.info("净值数据需要资金明细单中有银行转入/转出记录来计算累计净转入资金。")

# ── 每日资产明细表 ──────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 每日资产明细")

if not asset_history.empty:
    display_history = asset_history.copy()
    display_history["cash_balance"] = display_history["cash_balance"].apply(lambda x: f"¥ {x:,.2f}" if pd.notna(x) else "-")
    display_history["market_value"] = display_history["market_value"].apply(lambda x: f"¥ {x:,.2f}" if pd.notna(x) else "-")
    display_history["total_assets"] = display_history["total_assets"].apply(lambda x: f"¥ {x:,.2f}" if pd.notna(x) else "-")
    if "net_value" in display_history.columns:
        display_history["net_value"] = display_history["net_value"].apply(
            lambda x: f"{x:.4f}" if pd.notna(x) else "-"
        )
    display_history = display_history.sort_values("date", ascending=False)
    st.dataframe(display_history, use_container_width=True, hide_index=True)
else:
    st.info("暂无每日资产记录")
