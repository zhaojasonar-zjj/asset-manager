"""数据上传页面 — 交割单/对账单/资金明细单"""
import streamlit as st
import pandas as pd
from datetime import datetime

from core.database import Database
from core.parsers import (
    parse_excel_file,
    detect_file_type,
    detect_broker,
    read_excel_robust,
)
from core.portfolio import recalculate_holdings

st.set_page_config(page_title="数据上传", page_icon="📁", layout="wide")

st.markdown("# 📁 数据上传")
st.markdown("上传券商导出的 Excel 交割单 / 对账单 / 资金明细单，系统自动识别格式并解析。")

# ── 数据库 ───────────────────────────────────────────────
db = Database()

# ── 上传区域 ─────────────────────────────────────────────
col1, col2 = st.columns([3, 1])

with col1:
    uploaded_files = st.file_uploader(
        "选择 Excel / CSV 文件",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
        help="支持多券商格式，一次可上传多个文件",
    )

with col2:
    manual_broker = st.selectbox(
        "券商（可选，留空自动检测）",
        ["自动检测", "华泰", "中信", "国泰君安", "海通", "广发", "招商", "东方财富", "平安", "银河", "申万", "通用"],
        index=0,
    )

# ── 处理上传 ─────────────────────────────────────────────
if uploaded_files:
    all_parsed = []
    errors = []

    for uploaded_file in uploaded_files:
        # 保存临时文件
        tmp_path = f"/tmp/{uploaded_file.name}"
        with open(tmp_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        # 检测券商
        broker = (
            detect_broker(pd.DataFrame(), uploaded_file.name)
            if manual_broker == "自动检测"
            else manual_broker
        )

        try:
            results = parse_excel_file(tmp_path, broker)
            if not results:
                errors.append(f"⚠️ **{uploaded_file.name}**：未识别出有效数据，请检查文件格式。"
                              f"\n\n提示：确保 Excel 包含「证券代码」「成交日期」「成交数量」等列名。")
            else:
                for r in results:
                    r["filename"] = uploaded_file.name
                    all_parsed.append(r)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            errors.append(f"❌ **{uploaded_file.name}**：{str(e)}\n\n```\n{tb}\n```")

    # 显示错误
    for err in errors:
        st.error(err)

    # 显示解析结果预览
    if all_parsed:
        st.markdown("---")
        st.markdown(f"### 📋 解析预览（共 {len(all_parsed)} 个数据表）")

        tx_count_total = 0
        ff_count_total = 0

        for i, parsed in enumerate(all_parsed):
            file_type_label = "交割单" if parsed["file_type"] == "transactions" else "资金明细单"
            data = parsed["data"]
            sheet = parsed.get("sheet", "")
            filename = parsed["filename"]

            st.markdown(f"#### {i + 1}. {filename} — {file_type_label}（{len(data)} 条）")
            if sheet:
                st.caption(f"工作表: {sheet}")

            # 预览前 20 行
            st.dataframe(data.head(20), use_container_width=True, height=300)

            if parsed["file_type"] == "transactions":
                tx_count_total += len(data)
            else:
                ff_count_total += len(data)

        # 确认导入
        st.markdown("---")
        st.markdown(f"**总计**: 交割单 {tx_count_total} 条 | 资金流水 {ff_count_total} 条")

        col_confirm, col_cancel = st.columns([1, 4])
        if col_confirm.button("✅ 确认导入数据库", type="primary"):
            progress = st.progress(0, "正在导入...")
            total = len(all_parsed)

            for i, parsed in enumerate(all_parsed):
                data = parsed["data"]
                file_type = parsed["file_type"]
                filename = parsed["filename"]
                broker = data["broker"].iloc[0] if "broker" in data.columns else "通用"

                try:
                    if file_type == "transactions":
                        db.insert_transactions(data)
                        # 重建持仓
                        all_tx = db.get_all_transactions()
                        holdings = recalculate_holdings(all_tx)
                        db.replace_holdings(holdings)
                    else:
                        db.insert_fund_flows(data)

                    db.log_upload(filename, file_type, broker, len(data), "success", "")
                except Exception as e:
                    db.log_upload(filename, file_type, broker, 0, "error", str(e))
                    st.error(f"导入失败: {filename} — {str(e)}")

                progress.progress((i + 1) / total, f"正在导入... ({i + 1}/{total})")

            progress.progress(1.0, "导入完成！")
            st.success(f"✅ 成功导入 {tx_count_total + ff_count_total} 条记录！持仓已自动更新。")
            st.balloons()

# ── 上传历史 ─────────────────────────────────────────────
st.markdown("---")
st.markdown("### 📜 上传历史")

history = db.get_upload_history()
if history.empty:
    st.info("暂无上传记录")
else:
    display_cols = ["upload_time", "filename", "file_type", "broker", "record_count", "status"]
    available_cols = [c for c in display_cols if c in history.columns]
    st.dataframe(history[available_cols], use_container_width=True, hide_index=True)

# ── 数据管理 ─────────────────────────────────────────────
st.markdown("---")
st.markdown("### ⚙️ 数据管理")

with st.expander("危险操作"):
    if st.button("🗑️ 清空所有数据", type="secondary"):
        st.session_state["confirm_clear"] = True

    if st.session_state.get("confirm_clear"):
        st.warning("确定要清空所有数据吗？此操作不可恢复！")
        col1, col2 = st.columns(2)
        if col1.button("确认清空", type="primary"):
            db.clear_all_data()
            st.success("所有数据已清空")
            st.session_state["confirm_clear"] = False
            st.rerun()
        if col2.button("取消"):
            st.session_state["confirm_clear"] = False
            st.rerun()
