"""个人股票资产管理 — 主页

运行: streamlit run app.py
"""
import streamlit as st
from core.database import Database

# ── 页面配置 ─────────────────────────────────────────────
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
    /* 减少顶部留白 */
    .block-container { padding-top: 2rem; padding-bottom: 2rem; max-width: 1200px; }
    /* 卡片样式 */
    [data-testid="stMetric"] {
        background: #f8fafc;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        border: 1px solid #e2e8f0;
    }
    [data-testid="stMetricValue"] { font-size: 1.4rem; }
    /* 侧边栏 */
    [data-testid="stSidebar"] { background: #fafbfc; }
    /* 表格 */
    .stDataFrame { border-radius: 8px; overflow: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── 数据库实例 ───────────────────────────────────────────
@st.cache_resource
def get_db():
    return Database()


db = get_db()

# ── 侧边栏 ───────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 📊 股票资产管理")
    st.markdown("---")

    tx_count = db.get_transaction_count()
    ff_count = db.get_fund_flow_count()
    brokers = db.get_brokers()

    st.markdown("**数据概览**")
    st.markdown(f"- 交割单记录: **{tx_count}** 条")
    st.markdown(f"- 资金流水: **{ff_count}** 条")
    st.markdown(f"- 券商数量: **{len(brokers)}** 个")
    if brokers:
        st.markdown(f"  {' · '.join(brokers)}")
    st.markdown("---")

    st.markdown("**导航**")
    st.markdown("📁 [数据上传](数据上传)")
    st.markdown("📊 [资产看板](资产看板)")
    st.markdown("💰 [资金流水](资金流水)")
    st.markdown("📈 [持仓明细](持仓明细)")
    st.markdown("---")
    st.caption("基于 Streamlit + SQLite")


# ── 主页内容 ─────────────────────────────────────────────
if tx_count == 0 and ff_count == 0:
    # 空状态引导
    st.markdown("## 👋 欢迎使用股票资产管理")
    st.markdown(
        """
        一个轻量级的个人 A 股资产管理工具，支持：

        - 📁 **多券商交割单/对账单/资金明细单**自动解析（Excel）
        - 📈 **实时行情**自动拉取（腾讯财经接口）
        - 💰 **资金流水**对账与汇总
        - 📊 **资产看板**：持仓市值、历史曲线、净值曲线

        ---

        ### 🚀 快速开始

        1. 在左侧导航点击 **数据上传**
        2. 上传你的券商交割单 Excel 文件
        3. 系统自动识别格式并导入数据库
        4. 前往 **资产看板** 查看持仓与资产概况
        """
    )
else:
    # 有数据时显示概览
    st.markdown("## 📊 资产概览")

    holdings = db.get_holdings()
    cash = db.get_cash_balance()
    deposits = db.get_total_deposits()

    if not holdings.empty:
        from core.price_fetcher import fetch_realtime_prices
        from core.portfolio import calculate_market_value

        codes = holdings["stock_code"].unique().tolist()
        with st.spinner("正在获取实时行情..."):
            prices = fetch_realtime_prices(codes)
        market_value, pnl, enriched = calculate_market_value(holdings, prices)
    else:
        market_value = 0
        pnl = 0
        prices = {}

    total_assets = cash + market_value
    net_value = total_assets / deposits if deposits > 0 else 0
    pnl_pct = (pnl / (market_value - pnl) * 100) if (market_value - pnl) > 0 else 0

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

    st.markdown("---")
    st.info("👆 在左侧导航栏选择 **资产看板** 查看完整图表与分析")
