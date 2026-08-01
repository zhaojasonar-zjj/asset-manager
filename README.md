# 个人股票资产管理系统

基于 Python Streamlit 的轻量级个人 A 股资产管理 Web 应用。

## ✨ 功能

| 功能 | 说明 |
|------|------|
| 📁 数据上传 | 支持多券商交割单/对账单/资金明细单 Excel 自动解析 |
| 📊 资产看板 | 持仓市值、历史资产曲线、净值曲线、每日资产快照 |
| 💰 资金流水 | 资金账户流水表、对账汇总、每日资金变动趋势 |
| 📈 持仓明细 | 持仓列表（代码/数量/最新价/市值/盈亏/占比）、饼图、柱状图 |
| 🔄 实时行情 | 腾讯财经接口自动拉取 A 股实时价格 |

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 启动应用

```bash
cd stock-portfolio
streamlit run app.py
```

浏览器自动打开 `http://localhost:8501`。

### 3. 使用流程

1. **数据上传** → 上传券商导出的 Excel 文件
2. 系统自动识别文件格式并解析
3. 确认预览数据后导入数据库
4. **资产看板** 查看持仓与资产概况
5. **资金流水** 查看对账明细
6. **持仓明细** 查看持仓分析与图表

## 📂 项目结构

```
stock-portfolio/
├── app.py                  # 主入口（首页概览）
├── requirements.txt        # Python 依赖
├── .streamlit/config.toml  # Streamlit 配置
├── core/                   # 核心逻辑
│   ├── database.py         # SQLite 数据库管理
│   ├── parsers.py          # 多券商 Excel 解析器
│   ├── price_fetcher.py    # 腾讯财经行情接口
│   └── portfolio.py        # 持仓计算 & 资产快照
├── pages/                  # Streamlit 多页面
│   ├── 1_数据上传.py
│   ├── 2_资产看板.py
│   ├── 3_资金流水.py
│   └── 4_持仓明细.py
└── data/                   # SQLite 数据库（自动创建）
    └── portfolio.db
```

## 🔧 技术栈

- **前端**: Streamlit
- **数据库**: SQLite
- **数据处理**: Pandas
- **图表**: Plotly
- **行情接口**: 腾讯财经

## 📋 支持的券商

系统采用列名自动匹配机制，无需为每家券商单独编写解析器。以下券商格式已测试兼容：

- 华泰证券
- 中信证券
- 国泰君安
- 海通证券
- 广发证券
- 招商证券
- 东方财富
- 其他券商（通用模式自动匹配）

如果自动识别失败，可在上传时手动选择券商。

## 📐 数据库表结构

### transactions（交割单）
| 字段 | 说明 |
|------|------|
| broker | 证券公司 |
| trade_date | 成交日期 |
| stock_code | 证券代码 |
| stock_name | 证券名称 |
| trade_type | 买卖方向（买入/卖出）|
| quantity | 成交数量 |
| price | 成交价格 |
| amount | 成交金额 |
| commission | 手续费 |
| stamp_tax | 印花税 |
| transfer_fee | 过户费 |
| other_fee | 其他费用 |
| settlement | 结算金额 |

### fund_flows（资金流水）
| 字段 | 说明 |
|------|------|
| broker | 证券公司 |
| flow_date | 日期 |
| flow_type | 业务类型 |
| stock_code | 证券代码（关联交易）|
| stock_name | 证券名称 |
| amount | 发生金额（正=入账，负=出账）|
| balance | 资金余额 |
| description | 备注 |

### holdings（持仓）
| 字段 | 说明 |
|------|------|
| broker | 证券公司 |
| stock_code | 证券代码 |
| stock_name | 证券名称 |
| quantity | 持仓数量 |
| cost_price | 成本价（加权平均）|
| total_cost | 持仓总成本 |

### daily_assets（每日资产快照）
| 字段 | 说明 |
|------|------|
| snapshot_date | 日期 |
| cash_balance | 现金余额 |
| market_value | 持仓市值 |
| total_assets | 总资产 |
| net_value | 净值 |

## 🔄 行情接口

### 实时行情
```
http://qt.gtimg.cn/q=sh600000,sz000001
```

### 历史K线
```
http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600000,day,2024-01-01,2024-12-31,365,qfq
```

## ⚠️ 注意事项

- 本应用仅供个人使用，不构成投资建议
- 数据存储在本地 SQLite 数据库中，不上传任何信息
- 行情接口可能因网络原因偶尔超时，刷新页面即可
- 首次使用建议先导入少量数据测试格式兼容性

## 📄 License

MIT
