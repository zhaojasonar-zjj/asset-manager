"""资产看板 — 多账户版"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from core.database import Database
from core.price_fetcher import fetch_realtime_prices
from core.portfolio import calculate_market_value, build_asset_history, get_capital_changes

st.set_page_config(page_title="资产看板", page_icon="📊", layout="wide")

st.markdown("# 📊 资产看板")

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
tx_count = db.get_transaction_count(account_id)
ff_count = db.get_fund_flow_count(account_id)
if tx_count == 0 and ff_count == 0:
    st.warning(f"账户「{selected['name']}」暂无数据，请先上传文件。")
    st.stop()

# ── 获取数据 ─────────────────────────────────────────────
holdings = db.get_holdings(account_id)
cash = db.get_cash_balance(account_id)
deposits = db.get_total_deposits(account_id)

# ── 实时行情 ─────────────────────────────────────────────
prices = {}
prices_ok = True
if not holdings.empty:
    codes = holdings["stock_code"].unique().tolist()
    with st.spinner("正在获取实时行情..."):
        prices = fetch_realtime_prices(codes)

market_value, pnl, enriched, prices_ok = calculate_market_value(holdings, prices)
total_assets = cash + market_value

# ── 数据来源标识 ─────────────────────────────────────────
if ff_count > 0:
    source_note = "💰 现金余额：来自资金明细单"
else:
    source_note = "⚠️ 现金余额：无资金明细单，由交割单推算（可能不准）"

# ── 汇总卡片 ────────────────────────────────────────────
st.markdown("---")
col1, col2, col3, col4 = st.columns(4)
col1.metric("总资产", f"¥ {total_assets:,.2f}")
col2.metric("现金余额", f"¥ {cash:,.2f}")
col3.metric("持仓市值", f"¥ {market_value:,.2f}")
col4.metric("累计盈亏", f"¥ {pnl:,.2f}")

st.caption(source_note)
if not prices_ok:
    st.warning("⚠️ 部分股票实时行情获取失败，市值用成本价估算。")

if deposits > 0:
    col_a, col_b = st.columns(2)
    col_a.metric("累计净转入", f"¥ {deposits:,.2f}")
    net_value = total_assets / deposits if deposits > 0 else 0
    col_b.metric("净值", f"{net_value:.4f}", f"{(net_value - 1) * 100:+.2f}%")

# ── 持仓明细表 ──────────────────────────────────────────
st.markdown("---")
st.markdown("### 📈 当前持仓")

if not enriched.empty:
    display = enriched.copy()
    display["cost_price"] = display["cost_price"].apply(lambda x: f"¥ {x:,.4f}")
    display["latest_price"] = display["latest_price"].apply(lambda x: f"¥ {x:,.4f}")
    display["market_value"] = display["market_value"].apply(lambda x: f"¥ {x:,.2f}")
    display["total_cost"] = display["total_cost"].apply(lambda x: f"¥ {x:,.2f}")
    display["pnl"] = display["pnl"].apply(lambda x: f"¥ {x:,.2f}")
    display["pnl_pct"] = display["pnl_pct"].apply(lambda x: f"{x:+.2f}%")

    show_cols = {
        "stock_code": "代码",
        "stock_name": "名称",
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
else:
    st.info("暂无持仓")

# ── 资产历史曲线 ────────────────────────────────────────
st.markdown("---")
st.markdown("### 📉 资产历史曲线")

asset_history = build_asset_history(db, account_id)

# 重建按钮
col_btn, col_info = st.columns([1, 3])
with col_btn:
    if st.button("🔄 重建历史曲线", help="重新获取历史行情并计算每日资产"):
        with st.spinner("正在重建，可能需要数十秒..."):
            asset_history = build_asset_history(db, account_id, force_rebuild=True)
        st.success(f"已重建：{len(asset_history)} 个交易日")
        st.rerun()
with col_info:
    if not asset_history.empty:
        st.caption(f"共 {len(asset_history)} 个交易日 ｜ {asset_history['date'].min()} ~ {asset_history['date'].max()}")

if not asset_history.empty:
    chart_data = asset_history.copy()
    chart_data["date"] = chart_data["date"].astype(str)

    fig = go.Figure()
    if "total_assets" in chart_data.columns:
        fig.add_trace(go.Scatter(
            x=chart_data["date"], y=chart_data["total_assets"],
            name="总资产", line=dict(color="#2563eb", width=2),
            mode="lines",
        ))
    if "cash_balance" in chart_data.columns:
        fig.add_trace(go.Scatter(
            x=chart_data["date"], y=chart_data["cash_balance"],
            name="现金", line=dict(color="#16a34a", width=1.5, dash="dot"),
            mode="lines",
        ))
    if "market_value" in chart_data.columns:
        fig.add_trace(go.Scatter(
            x=chart_data["date"], y=chart_data["market_value"],
            name="市值", line=dict(color="#f59e0b", width=1.5, dash="dot"),
            mode="lines",
        ))
    if "net_value" in chart_data.columns:
        fig.add_trace(go.Scatter(
            x=chart_data["date"], y=chart_data["net_value"],
            name="净值", line=dict(color="#8b5cf6", width=2),
            mode="lines", yaxis="y2",
        ))

    fig.update_layout(
        xaxis_title="日期",
        yaxis_title="金额 (¥)",
        yaxis2=dict(title="净值", overlaying="y", side="right"),
        height=400,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("暂无资产历史数据，请先上传数据")

# ── 每日资产明细表 ──────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 每日资产明细（按交易日）")

if not asset_history.empty:
    display_history = asset_history.copy()
    display_history["date"] = display_history["date"].astype(str)
    display_history = display_history.sort_values("date", ascending=False)
    
    # 格式化显示
    for col in ["cash_balance", "market_value", "total_assets"]:
        if col in display_history.columns:
            display_history[col] = display_history[col].apply(lambda x: f"¥ {x:,.2f}" if pd.notna(x) else "-")
    if "net_value" in display_history.columns:
        display_history["net_value"] = display_history["net_value"].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "-")
    
    st.dataframe(display_history, use_container_width=True, hide_index=True, height=500)
else:
    st.info("暂无每日资产记录")

# ── 本金变动记录 ────────────────────────────────────────
st.markdown("---")
st.markdown("### 🏦 本金变动记录（银行 ↔ 证券）")

capital_changes = get_capital_changes(db, account_id)

if not capital_changes.empty:
    # 汇总卡片
    inflow_total = capital_changes[capital_changes["direction"] == "转入"]["amount"].sum()
    outflow_total = capital_changes[capital_changes["direction"] == "转出"]["amount"].sum()
    net_total = inflow_total - outflow_total
    record_count = len(capital_changes)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("累计转入", f"¥ {inflow_total:,.2f}")
    col2.metric("累计转出", f"¥ {outflow_total:,.2f}")
    col3.metric("净转入本金", f"¥ {net_total:,.2f}")
    col4.metric("变动次数", f"{record_count} 次")

    st.markdown("")

    # 累计净转入曲线
    import plotly.graph_objects as go
    chart_df = capital_changes.copy()
    chart_df["date"] = chart_df["date"].astype(str)

    fig_capital = go.Figure()
    # 转入柱状图
    inflow_df = chart_df[chart_df["direction"] == "转入"]
    if not inflow_df.empty:
        fig_capital.add_trace(go.Bar(
            x=inflow_df["date"], y=inflow_df["amount"],
            name="转入", marker_color="#16a34a",
        ))
    # 转出柱状图
    outflow_df = chart_df[chart_df["direction"] == "转出"]
    if not outflow_df.empty:
        fig_capital.add_trace(go.Bar(
            x=outflow_df["date"], y=outflow_df["amount"],
            name="转出", marker_color="#dc2626",
        ))
    # 累计净转入折线
    fig_capital.add_trace(go.Scatter(
        x=chart_df["date"], y=chart_df["cumulative"],
        name="累计净转入", line=dict(color="#2563eb", width=2),
        mode="lines+markers", yaxis="y2",
    ))

    fig_capital.update_layout(
        barmode="grouped",
        xaxis_title="日期",
        yaxis_title="单笔金额 (¥)",
        yaxis2=dict(title="累计净转入 (¥)", overlaying="y", side="right"),
        height=350,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig_capital, use_container_width=True)

    # 明细表
    st.markdown("#### 📋 变动明细")
    display_changes = capital_changes.copy()
    display_changes["date"] = display_changes["date"].astype(str)
    display_changes["amount"] = display_changes["amount"].apply(lambda x: f"¥ {x:,.2f}")
    display_changes["balance_after"] = display_changes["balance_after"].apply(
        lambda x: f"¥ {x:,.2f}" if x else "-"
    )
    display_changes["cumulative"] = display_changes["cumulative"].apply(lambda x: f"¥ {x:,.2f}")
    display_changes = display_changes.rename(columns={
        "date": "日期",
        "type": "类型",
        "direction": "方向",
        "amount": "金额",
        "balance_after": "转账后余额",
        "bank": "存管银行",
        "cumulative": "累计净转入",
        "description": "备注",
    })
    display_changes = display_changes[["日期", "方向", "类型", "金额", "转账后余额", "存管银行", "累计净转入", "备注"]]
    st.dataframe(display_changes, use_container_width=True, hide_index=True, height=400)
else:
    st.info("暂无银行↔证券资金变动记录")
