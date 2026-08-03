"""数据上传页面 — 多账户版"""
import streamlit as st
import pandas as pd
from datetime import datetime
from pathlib import Path
import shutil

from core.database import Database
from core.parsers import parse_excel_file, detect_format, read_excel_robust, summarize_weekly_assets
from core.portfolio import recalculate_holdings, build_asset_history

st.set_page_config(page_title="数据上传", page_icon="📁", layout="wide")

st.markdown("# 📁 数据上传")

db = Database()

# ── 账户管理 ─────────────────────────────────────────────
st.markdown("### 📂 账户管理")

accounts = db.get_all_accounts()

col1, col2, col3 = st.columns([2, 2, 1])
with col1:
    new_account_name = st.text_input("账户名称", placeholder="如：国泰君安-姜", key="new_acc_name")
with col2:
    new_broker = st.selectbox("证券公司", ["国泰君安", "华泰证券", "中信证券", "招商证券", "海通证券", "广发证券", "其他"], key="new_broker")
with col3:
    new_holder = st.text_input("持有人", placeholder="姓名", key="new_holder")
    if st.button("➕ 创建账户", type="primary", use_container_width=True):
        if new_account_name:
            existing = db.get_account_by_name(new_account_name)
            if existing:
                st.warning(f"账户「{new_account_name}」已存在")
            else:
                db.create_account(new_account_name, new_broker, new_holder)
                st.success(f"账户「{new_account_name}」创建成功")
                st.rerun()
        else:
            st.warning("请输入账户名称")

# 显示已有账户
if accounts:
    st.markdown("---")
    st.markdown("#### 已有账户")
    for acc in accounts:
        tx_count = db.get_transaction_count(acc["id"])
        ff_count = db.get_fund_flow_count(acc["id"])
        col_a, col_b, col_c, col_d = st.columns([3, 2, 2, 1])
        col_a.markdown(f"**{acc['name']}** 　{acc['broker']}")
        col_b.markdown(f"交割单: **{tx_count}** 条")
        col_c.markdown(f"资金流水: **{ff_count}** 条")
        with col_d:
            if st.button("🗑️", key=f"del_{acc['id']}", help=f"删除账户 {acc['name']}"):
                db.delete_account(acc["id"])
                st.success(f"已删除账户「{acc['name']}」")
                st.rerun()
else:
    st.info("👆 请先创建一个账户")
    st.stop()

# ── 上传区域 ─────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📤 上传文件")

col_acc, col_file = st.columns([1, 2])
with col_acc:
    selected_account_id = st.selectbox(
        "上传到账户",
        accounts,
        format_func=lambda x: f"{x['name']} ({x['broker']})",
        key="upload_acc",
    )
with col_file:
    uploaded_files = st.file_uploader(
        "选择 Excel 文件",
        type=["xlsx", "xls"],
        accept_multiple_files=True,
        help="支持国泰君安交割单、华泰证券交割单/资金明细单/每周资产",
    )

if uploaded_files and selected_account_id:
    account_id = selected_account_id["id"]
    all_parsed = []
    errors = []

    for uploaded_file in uploaded_files:
        tmp_path = Path("/tmp") / uploaded_file.name
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(uploaded_file, f)

        try:
            results = parse_excel_file(tmp_path)
            if not results:
                sheets = read_excel_robust(tmp_path)
                diag_msg = f"⚠️ **{uploaded_file.name}**：未识别出有效数据。\n\n"
                for sheet_name, df in sheets:
                    fmt = detect_format(df)
                    diag_msg += f"**工作表**: {sheet_name} | **识别格式**: {fmt}\n"
                    diag_msg += f"**列名**: {df.columns.tolist()}\n\n"
                    diag_msg += f"**前 5 行**:\n```\n{df.head().to_string()}\n```\n\n---\n\n"
                errors.append(diag_msg)
            else:
                for r in results:
                    r["filename"] = uploaded_file.name
                    all_parsed.append(r)
        except Exception as e:
            import traceback
            errors.append(f"❌ **{uploaded_file.name}**：{str(e)}\n\n```\n{traceback.format_exc()}\n```")

    # 显示错误
    for err in errors:
        st.error(err)

    # 显示解析结果
    if all_parsed:
        st.markdown("---")
        st.markdown("### ✅ 解析结果预览")

        for r in all_parsed:
            st.markdown(f"**{r['filename']}** — 工作表: {r['sheet']} — 格式: {r['format']} — {len(r['data'])} 条")

            data = r["data"]
            st.dataframe(data.head(10), use_container_width=True, hide_index=True)

        # 确认导入
        st.markdown("---")
        if st.button("✅ 确认导入数据库", type="primary"):
            for r in all_parsed:
                fmt = r["format"]
                data = r["data"]
                fname = r["filename"]

                if fmt == "gtja_transactions" or fmt == "huatai_transactions":
                    db.insert_transactions(data, account_id)
                    # 重建持仓
                    all_tx = db.get_transactions(account_id)
                    holdings_list = recalculate_holdings(all_tx)
                    db.replace_holdings(account_id, holdings_list)
                    db.log_upload(account_id, fname, "交割单", len(data))
                    st.success(f"✅ {fname}：{len(data)} 条交割单已导入，持仓已重建（{len(holdings_list)} 只持仓）")

                elif fmt == "huatai_fund_flows":
                    db.insert_fund_flows(data, account_id)
                    db.log_upload(account_id, fname, "资金明细", len(data))
                    st.success(f"✅ {fname}：{len(data)} 条资金流水已导入")

                elif fmt == "huatai_weekly_assets":
                    # 汇总为每周快照
                    weekly_summary = summarize_weekly_assets(data)
                    db.insert_weekly_assets(weekly_summary, account_id)
                    db.log_upload(account_id, fname, "每周资产", len(weekly_summary))
                    st.success(f"✅ {fname}：{len(weekly_summary)} 周资产快照已导入")

            # 导入完成后自动构建历史资产快照
            with st.spinner("正在构建历史资产曲线（获取历史行情，可能需要数十秒）..."):
                try:
                    history_df = build_asset_history(db, account_id, force_rebuild=True)
                    if not history_df.empty:
                        st.info(f"📈 历史资产曲线已构建：{len(history_df)} 个交易日")
                except Exception as e:
                    st.warning(f"历史资产曲线构建失败（不影响数据导入）: {e}")

            st.balloons()

# ── 上传历史 ─────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📋 上传历史")
history = db.get_upload_history()
if not history.empty:
    display_cols = {
        "upload_time": "上传时间",
        "account_name": "账户",
        "broker": "券商",
        "filename": "文件名",
        "file_type": "类型",
        "record_count": "记录数",
        "status": "状态",
    }
    available = [c for c in display_cols if c in history.columns]
    st.dataframe(history[available].rename(columns=display_cols), use_container_width=True, hide_index=True)
else:
    st.info("暂无上传记录")
