"""SQLite 数据库管理模块

负责所有数据库操作：建表、插入、查询、持仓更新、每日快照。
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "portfolio.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker        TEXT NOT NULL,
    trade_date    TEXT NOT NULL,
    stock_code    TEXT NOT NULL,
    stock_name    TEXT,
    trade_type    TEXT NOT NULL,
    quantity      REAL NOT NULL,
    price         REAL NOT NULL,
    amount        REAL NOT NULL,
    commission    REAL DEFAULT 0,
    stamp_tax     REAL DEFAULT 0,
    transfer_fee  REAL DEFAULT 0,
    other_fee     REAL DEFAULT 0,
    settlement    REAL NOT NULL,
    created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS fund_flows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker      TEXT NOT NULL,
    flow_date   TEXT NOT NULL,
    flow_type   TEXT,
    stock_code  TEXT,
    stock_name  TEXT,
    amount      REAL NOT NULL,
    balance     REAL,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    broker      TEXT NOT NULL,
    stock_code  TEXT NOT NULL,
    stock_name  TEXT,
    quantity    REAL NOT NULL,
    cost_price  REAL NOT NULL,
    total_cost  REAL NOT NULL,
    updated_at  TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(broker, stock_code)
);

CREATE TABLE IF NOT EXISTS daily_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date TEXT NOT NULL UNIQUE,
    cash_balance  REAL NOT NULL,
    market_value  REAL NOT NULL,
    total_assets  REAL NOT NULL,
    net_value     REAL,
    created_at    TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS upload_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT NOT NULL,
    file_type    TEXT NOT NULL,
    broker       TEXT,
    upload_time  TEXT DEFAULT (datetime('now', 'localtime')),
    record_count INTEGER DEFAULT 0,
    status       TEXT DEFAULT 'success',
    message      TEXT
);

CREATE INDEX IF NOT EXISTS idx_tx_date  ON transactions(trade_date);
CREATE INDEX IF NOT EXISTS idx_tx_code  ON transactions(stock_code);
CREATE INDEX IF NOT EXISTS idx_ff_date  ON fund_flows(flow_date);
CREATE INDEX IF NOT EXISTS idx_da_date  ON daily_assets(snapshot_date);
"""


class Database:
    """SQLite 数据库管理器"""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ── 连接管理 ──────────────────────────────────────────

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)

    # ── 交割单 ────────────────────────────────────────────

    def insert_transactions(self, df: pd.DataFrame):
        with self.get_connection() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT INTO transactions
                       (broker, trade_date, stock_code, stock_name, trade_type,
                        quantity, price, amount, commission, stamp_tax,
                        transfer_fee, other_fee, settlement)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        row.get("broker", ""),
                        row.get("trade_date", ""),
                        str(row.get("stock_code", "")).zfill(6),
                        row.get("stock_name", ""),
                        row.get("trade_type", ""),
                        float(row.get("quantity", 0)),
                        float(row.get("price", 0)),
                        float(row.get("amount", 0)),
                        float(row.get("commission", 0)),
                        float(row.get("stamp_tax", 0)),
                        float(row.get("transfer_fee", 0)),
                        float(row.get("other_fee", 0)),
                        float(row.get("settlement", 0)),
                    ),
                )

    def get_transactions(self, broker=None, start_date=None, end_date=None) -> pd.DataFrame:
        sql = "SELECT * FROM transactions WHERE 1=1"
        params = []
        if broker:
            sql += " AND broker = ?"
            params.append(broker)
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        sql += " ORDER BY trade_date DESC, id DESC"
        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def get_all_transactions(self) -> pd.DataFrame:
        with self.get_connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM transactions ORDER BY trade_date ASC", conn
            )

    # ── 资金流水 ──────────────────────────────────────────

    def insert_fund_flows(self, df: pd.DataFrame):
        with self.get_connection() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT INTO fund_flows
                       (broker, flow_date, flow_type, stock_code, stock_name,
                        amount, balance, description)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        row.get("broker", ""),
                        row.get("flow_date", ""),
                        row.get("flow_type", ""),
                        str(row.get("stock_code", "")).zfill(6) if row.get("stock_code") else "",
                        row.get("stock_name", ""),
                        float(row.get("amount", 0)),
                        float(row.get("balance")) if pd.notna(row.get("balance")) else None,
                        row.get("description", ""),
                    ),
                )

    def get_fund_flows(self, broker=None, start_date=None, end_date=None) -> pd.DataFrame:
        sql = "SELECT * FROM fund_flows WHERE 1=1"
        params = []
        if broker:
            sql += " AND broker = ?"
            params.append(broker)
        if start_date:
            sql += " AND flow_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND flow_date <= ?"
            params.append(end_date)
        sql += " ORDER BY flow_date DESC, id DESC"
        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    # ── 持仓 ──────────────────────────────────────────────

    def get_holdings(self, broker=None) -> pd.DataFrame:
        sql = "SELECT * FROM holdings WHERE quantity > 0"
        params = []
        if broker:
            sql += " AND broker = ?"
            params.append(broker)
        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def replace_holdings(self, holdings_list: list[dict]):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM holdings")
            for h in holdings_list:
                conn.execute(
                    """INSERT INTO holdings
                       (broker, stock_code, stock_name, quantity, cost_price, total_cost)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        h["broker"],
                        h["stock_code"],
                        h.get("stock_name", ""),
                        h["quantity"],
                        h["cost_price"],
                        h["total_cost"],
                    ),
                )

    # ── 每日资产快照 ──────────────────────────────────────

    def get_daily_assets(self) -> pd.DataFrame:
        with self.get_connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM daily_assets ORDER BY snapshot_date ASC", conn
            )

    def save_daily_asset(self, date_str, cash, market_value, total, net_value=None):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO daily_assets
                   (snapshot_date, cash_balance, market_value, total_assets, net_value)
                   VALUES (?,?,?,?,?)""",
                (date_str, cash, market_value, total, net_value),
            )

    # ── 上传记录 ──────────────────────────────────────────

    def log_upload(self, filename, file_type, broker, record_count, status="success", message=""):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO upload_log
                   (filename, file_type, broker, record_count, status, message)
                   VALUES (?,?,?,?,?,?)""",
                (filename, file_type, broker, record_count, status, message),
            )

    def get_upload_history(self) -> pd.DataFrame:
        with self.get_connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM upload_log ORDER BY upload_time DESC", conn
            )

    # ── 统计 & 辅助 ───────────────────────────────────────

    def get_brokers(self) -> list[str]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT broker FROM transactions WHERE broker != '' "
                "UNION SELECT DISTINCT broker FROM fund_flows WHERE broker != ''"
            ).fetchall()
            return [r["broker"] for r in rows]

    def get_cash_balance(self) -> float:
        """获取最新现金余额

        优先级：
        1. 资金流水表中最新的 balance 字段
        2. 从资金流水 amount 字段累加
        3. 从交割单 settlement 字段推算（初始 0 + 累计结算金额）
        """
        with self.get_connection() as conn:
            # 优先：资金流水中的最新余额
            row = conn.execute(
                "SELECT balance FROM fund_flows WHERE balance IS NOT NULL "
                "ORDER BY flow_date DESC, id DESC LIMIT 1"
            ).fetchone()
            if row and row["balance"] is not None:
                return row["balance"]

            # 其次：资金流水 amount 累加
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS v FROM fund_flows"
            ).fetchone()
            if row and row["v"] != 0:
                return row["v"]

            # 最后：从交割单推算（0 + 累计结算金额，买入为负卖出为正）
            row = conn.execute(
                "SELECT COALESCE(SUM(settlement), 0) AS v FROM transactions"
            ).fetchone()
            return row["v"]

    def get_total_deposits(self) -> float:
        """累计净转入资金（银行转入 - 银行转出）

        匹配关键词更宽松，覆盖各券商不同写法。
        """
        with self.get_connection() as conn:
            # 银行转入类
            row = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) AS v FROM fund_flows
                   WHERE flow_type LIKE '%银行%转%证券%'
                      OR flow_type LIKE '%银行%转%%'
                      OR flow_type LIKE '%银证%转入%'
                      OR flow_type LIKE '%银证转%'
                      OR flow_type LIKE '%存管%转入%'
                      OR flow_type LIKE '%资金%转入%'
                      OR flow_type LIKE '%转入%'
                      OR flow_type LIKE '%入金%'"""
            ).fetchone()
            deposits = row["v"] if row["v"] > 0 else 0

            # 银行转出类
            row = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) AS v FROM fund_flows
                   WHERE flow_type LIKE '%证券%转%银行%'
                      OR flow_type LIKE '%银行%转出%'
                      OR flow_type LIKE '%银证%转出%'
                      OR flow_type LIKE '%银证转出%'
                      OR flow_type LIKE '%存管%转出%'
                      OR flow_type LIKE '%资金%转出%'
                      OR flow_type LIKE '%转出%'
                      OR flow_type LIKE '%出金%'"""
            ).fetchone()
            withdrawals = abs(row["v"]) if row["v"] < 0 else 0

            return deposits - withdrawals

    def get_transaction_count(self) -> int:
        with self.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM transactions").fetchone()["c"]

    def get_fund_flow_count(self) -> int:
        with self.get_connection() as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM fund_flows").fetchone()["c"]

    def clear_all_data(self):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM fund_flows")
            conn.execute("DELETE FROM holdings")
            conn.execute("DELETE FROM daily_assets")
            conn.execute("DELETE FROM upload_log")
