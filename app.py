"""个人股票资产管理 — 主页（多账户版）

运行: streamlit run app.py
"""
import streamlit as st
from core.database import Database
from core.price_fetcher import fetch_realtime_prices
from core.portfolio import calculate_market_value

st.set_page_config(
    page_title="股票资产管理",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 自定义样式 ───────────────────────────────────────────
st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1200px; }
    [data-testid="stMetric"] {
        background: #f8fafc;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border: 1px solid #e2e8f0;
    }
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
    [data-testid="stSidebar"] { background: #fafbfc; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("# 📊 股票资产管理")
st.markdown("多账户 · 多券商 · 独立管理")

db = Database()
accounts = db.get_all_accounts()

if not accounts:
    st.markdown("---")
    st.info("👆 请先在左侧「数据上传」页面创建账户并导入数据")
    st.stop()

# ── 全局概览：所有账户汇总 ───────────────────────────────
st.markdown("---")
st.markdown("### 📂 账户概览")

total_assets_all = 0
total_cash_all = 0
total_mv_all = 0
total_pnl_all = 0
total_deposits_all = 0

for acc in accounts:
    account_id = acc["id"]
    cash = db.get_cash_balance(account_id)
    holdings = db.get_holdings(account_id)
    deposits = db.get_total_deposits(account_id)

    if not holdings.empty:
        codes = holdings["stock_code"].unique().tolist()
        prices = fetch_realtime_prices(codes)
        mv, pnl, _, _ = calculate_market_value(holdings, prices)
    else:
        mv, pnl = 0, 0

    total_assets = cash + mv
    total_assets_all += total_assets
    total_cash_all += cash
    total_mv_all += mv
    total_pnl_all += pnl
    total_deposits_all += deposits

    tx_count = db.get_transaction_count(account_id)
    ff_count = db.get_fund_flow_count(account_id)

    with st.expander(f"**{acc['name']}** ({acc['broker']}) — 总资产 ¥ {total_assets:,.2f}", expanded=True):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("总资产", f"¥ {total_assets:,.2f}")
        col2.metric("现金余额", f"¥ {cash:,.2f}")
        col3.metric("持仓市值", f"¥ {mv:,.2f}")
        col4.metric("累计盈亏", f"¥ {pnl:,.2f}")

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("累计净转入", f"¥ {deposits:,.2f}")
        col_b.metric("交割单", f"{tx_count} 条")
        col_c.metric("资金流水", f"{ff_count} 条")

# ── 汇总 ────────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📊 全部账户汇总")

col1, col2, col3, col4 = st.columns(4)
col1.metric("总资产", f"¥ {total_assets_all:,.2f}")
col2.metric("总现金", f"¥ {total_cash_all:,.2f}")
col3.metric("总市值", f"¥ {total_mv_all:,.2f}")
col4.metric("总盈亏", f"¥ {total_pnl_all:,.2f}")

if total_deposits_all > 0:
    net_value = total_assets_all / total_deposits_all
    st.metric("整体净值", f"{net_value:.4f}", f"{(net_value - 1) * 100:+.2f}%")

st.markdown("---")
st.info("👆 在左侧导航栏选择具体页面查看详细信息")
