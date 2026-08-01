"""资金流水页面 — 对账与汇总"""
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

from core.database import Database
from core.portfolio import get_fund_flow_summary

st.set_page_config(page_title="资金流水", page_icon="💰", layout="wide")

st.markdown("# 💰 资金流水")

db = Database()

# ── 检查数据 ─────────────────────────────────────────────
ff_count = db.get_fund_flow_count()
if ff_count == 0:
    st.warning("暂无资金流水数据，请先上传资金明细单。")
    st.stop()

# ── 筛选器 ───────────────────────────────────────────────
st.markdown("### 🔍 筛选")

col1, col2, col3 = st.columns(3)

brokers = db.get_brokers()
broker_options = ["全部"] + brokers
selected_broker = col1.selectbox("券商", broker_options)

today = datetime.now()
default_start = today - timedelta(days=90)
date_range = col2.date_input(
    "日期范围",
    value=(default_start, today),
    max_value=today,
)

col3.markdown("&nbsp;")
col3.markdown("&nbsp;")
search_keyword = col3.text_input("关键词搜索", placeholder="如：转入、买入、分红...")

# ── 查询数据 ─────────────────────────────────────────────
start_date = date_range[0].strftime("%Y-%m-%d") if date_range else None
end_date = date_range[1].strftime("%Y-%m-%d") if len(date_range) > 1 else None

fund_flows = db.get_fund_flows(
    broker=None if selected_broker == "全部" else selected_broker,
    start_date=start_date,
    end_date=end_date,
)

# 关键词过滤
if search_keyword and not fund_flows.empty:
    mask = (
        fund_flows["flow_type"].astype(str).str.contains(search_keyword, case=False, na=False)
        | fund_flows["description"].astype(str).str.contains(search_keyword, case=False, na=False)
        | fund_flows["stock_name"].astype(str).str.contains(search_keyword, case=False, na=False)
    )
    fund_flows = fund_flows[mask]

# ── 汇总卡片 ────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📊 汇总")

summary = get_fund_flow_summary(fund_flows)

col1, col2, col3, col4 = st.columns(4)
col1.metric("流入合计", f"¥ {summary['total_inflow']:,.2f}")
col2.metric("流出合计", f"¥ {summary['total_outflow']:,.2f}")
col3.metric("净额", f"¥ {summary['net_flow']:,.2f}")
col4.metric(
    "最新余额",
    f"¥ {summary['latest_balance']:,.2f}" if summary["latest_balance"] else "—",
)

# ── 流水表 ──────────────────────────────────────────────
st.markdown("---")
st.markdown(f"### 📋 流水明细（{len(fund_flows)} 条）")

if fund_flows.empty:
    st.info("无符合条件的记录")
else:
    display = fund_flows.copy()

    # 格式化金额显示
    display["amount_display"] = display["amount"].apply(
        lambda x: f"¥ {x:,.2f}" if x >= 0 else f"¥ {x:,.2f}"
    )
    display["balance_display"] = display["balance"].apply(
        lambda x: f"¥ {x:,.2f}" if pd.notna(x) else "—"
    )

    # 排序列
    show_cols = {
        "flow_date": "日期",
        "flow_type": "业务类型",
        "stock_code": "证券代码",
        "stock_name": "证券名称",
        "amount_display": "发生金额",
        "balance_display": "资金余额",
        "description": "备注",
        "broker": "券商",
    }
    available = [c for c in show_cols if c in display.columns]
    display = display[available].rename(columns=show_cols)

    # 排序：日期降序
    display = display.sort_values("日期", ascending=False)
    st.dataframe(display, use_container_width=True, hide_index=True, height=500)

    # ── 资金流水趋势图 ────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📉 每日资金变动趋势")

    fund_flows_sorted = fund_flows.sort_values("flow_date")
    fund_flows_sorted["flow_date"] = fund_flows_sorted["flow_date"].astype(str)
    daily = fund_flows_sorted.groupby("flow_date").agg(
        inflow=("amount", lambda x: x[x > 0].sum()),
        outflow=("amount", lambda x: x[x < 0].sum()),
        net=("amount", "sum"),
    ).reset_index()

    import plotly.graph_objects as go

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=daily["flow_date"],
            y=daily["inflow"],
            name="流入",
            marker_color="#16a34a",
        )
    )
    fig.add_trace(
        go.Bar(
            x=daily["flow_date"],
            y=daily["outflow"],
            name="流出",
            marker_color="#dc2626",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=daily["flow_date"],
            y=daily["net"],
            name="净额",
            line=dict(color="#2563eb", width=2),
            mode="lines+markers",
        )
    )
    fig.update_layout(
        barmode="relative",
        xaxis_title="日期",
        yaxis_title="金额 (¥)",
        height=350,
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)
