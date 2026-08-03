"""SQLite 数据库管理模块（多账户版）

每个账户数据完全隔离：交割单、资金流水、持仓、快照均带 account_id。
"""
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "portfolio.db"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    broker      TEXT NOT NULL,
    holder      TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    trade_date  TEXT NOT NULL,
    stock_code  TEXT NOT NULL,
    stock_name  TEXT,
    trade_type  TEXT NOT NULL,
    quantity    REAL NOT NULL,
    price       REAL NOT NULL,
    amount      REAL NOT NULL,
    commission  REAL DEFAULT 0,
    stamp_tax   REAL DEFAULT 0,
    transfer_fee REAL DEFAULT 0,
    other_fee   REAL DEFAULT 0,
    settlement  REAL NOT NULL,
    asset_type  TEXT DEFAULT 'stock',
    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS fund_flows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    flow_date   TEXT NOT NULL,
    flow_type   TEXT,
    stock_code  TEXT,
    stock_name  TEXT,
    amount      REAL NOT NULL,
    balance     REAL,
    description TEXT,
    created_at  TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS holdings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER NOT NULL,
    stock_code  TEXT NOT NULL,
    stock_name  TEXT,
    quantity    REAL NOT NULL,
    cost_price  REAL NOT NULL,
    total_cost  REAL NOT NULL,
    asset_type  TEXT DEFAULT 'stock',
    updated_at  TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(account_id, stock_code),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS daily_assets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL,
    snapshot_date   TEXT NOT NULL,
    cash_balance    REAL NOT NULL,
    market_value    REAL NOT NULL,
    cash_like_value REAL DEFAULT 0,
    total_assets    REAL NOT NULL,
    net_value       REAL,
    created_at      TEXT DEFAULT (datetime('now', 'localtime')),
    UNIQUE(account_id, snapshot_date),
    FOREIGN KEY (account_id) REFERENCES accounts(id)
);

CREATE TABLE IF NOT EXISTS upload_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id  INTEGER,
    filename    TEXT NOT NULL,
    file_type   TEXT NOT NULL,
    upload_time TEXT DEFAULT (datetime('now', 'localtime')),
    record_count INTEGER DEFAULT 0,
    status      TEXT DEFAULT 'success',
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_tx_acc   ON transactions(account_id);
CREATE INDEX IF NOT EXISTS idx_tx_date  ON transactions(trade_date);
CREATE INDEX IF NOT EXISTS idx_tx_code  ON transactions(stock_code);
CREATE INDEX IF NOT EXISTS idx_ff_acc   ON fund_flows(account_id);
CREATE INDEX IF NOT EXISTS idx_ff_date  ON fund_flows(flow_date);
CREATE INDEX IF NOT EXISTS idx_da_acc   ON daily_assets(account_id);
"""


class Database:
    """SQLite 数据库管理器（多账户版）"""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        # ── 迁移检测：旧表没有 account_id 列，需要重建 ──
        # 先用独立连接检测，不经过 get_connection（避免 WAL 干扰）
        probe = sqlite3.connect(str(self.db_path))
        probe.row_factory = sqlite3.Row
        needs_rebuild = False
        for table in ("transactions", "fund_flows", "holdings", "daily_assets"):
            try:
                cols = probe.execute(f"PRAGMA table_info({table})").fetchall()
                if cols and not any(c["name"] == "account_id" for c in cols):
                    needs_rebuild = True
                    break
            except sqlite3.OperationalError:
                pass
        probe.close()

        if needs_rebuild:
            # 旧数据本身就是错的，直接删库重建
            for suffix in ("", "-wal", "-shm"):
                p = self.db_path.with_suffix(self.db_path.suffix + suffix) if suffix else self.db_path
                if p.exists():
                    p.unlink()

        with self.get_connection() as conn:
            conn.executescript(SCHEMA_SQL)

        # ── asset_type 列迁移（增量，不删数据）──
        # 用 get_connection 确保与 WAL 模式一致
        needs_asset_type_migration = False
        with self.get_connection() as conn:
            for table in ("transactions", "holdings"):
                try:
                    cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
                    if cols and not any(c["name"] == "asset_type" for c in cols):
                        needs_asset_type_migration = True
                        break
                except sqlite3.OperationalError:
                    pass
            try:
                da_cols = conn.execute("PRAGMA table_info(daily_assets)").fetchall()
                if da_cols and not any(c["name"] == "cash_like_value" for c in da_cols):
                    needs_asset_type_migration = True
            except sqlite3.OperationalError:
                pass

        if needs_asset_type_migration:
            with self.get_connection() as conn:
                for table in ("transactions", "holdings"):
                    try:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN asset_type TEXT DEFAULT 'stock'")
                    except sqlite3.OperationalError:
                        pass  # 列已存在
                try:
                    conn.execute("ALTER TABLE daily_assets ADD COLUMN cash_like_value REAL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass

                # 标记类现金记录：逆回购(204xxx)、券商货币基金(940xxx)
                for table in ("transactions", "holdings"):
                    conn.execute(
                        f"UPDATE {table} SET asset_type = 'cash_like' "
                        f"WHERE stock_code LIKE '204%' OR stock_code LIKE '940%'"
                    )

                # 修正 trade_type：cash_like 中 settlement<0 → 买入，settlement>0 → 卖出
                conn.execute(
                    "UPDATE transactions SET trade_type = '买入' "
                    "WHERE asset_type = 'cash_like' AND settlement < 0 AND trade_type = '其他'"
                )
                conn.execute(
                    "UPDATE transactions SET trade_type = '卖出' "
                    "WHERE asset_type = 'cash_like' AND settlement > 0 AND trade_type = '其他'"
                )

            # 重建所有账户持仓（trade_type 变了，持仓需要重算）
            from core.portfolio import recalculate_holdings
            for acc in self.get_all_accounts():
                tx_df = self.get_transactions(acc["id"])
                holdings_list = recalculate_holdings(tx_df)
                self.replace_holdings(acc["id"], holdings_list)

            # 清除历史快照（市值拆分变了，需要重建）
            with self.get_connection() as conn:
                conn.execute("DELETE FROM daily_assets")

    # ── 账户管理 ──────────────────────────────────────────

    def create_account(self, name: str, broker: str, holder: str = "") -> int:
        """创建账户，返回 account_id。如已存在则返回已有 id。"""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM accounts WHERE name = ?", (name,)
            ).fetchone()
            if row:
                return row["id"]
            cur = conn.execute(
                "INSERT INTO accounts (name, broker, holder) VALUES (?,?,?)",
                (name, broker, holder),
            )
            return cur.lastrowid

    def get_account(self, account_id: int) -> dict | None:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE id = ?", (account_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_account_by_name(self, name: str) -> dict | None:
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM accounts WHERE name = ?", (name,)
            ).fetchone()
            return dict(row) if row else None

    def get_all_accounts(self) -> list[dict]:
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM accounts ORDER BY id"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_account(self, account_id: int):
        """删除账户及其所有关联数据"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM fund_flows   WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM holdings     WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM daily_assets WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM upload_log   WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM accounts     WHERE id = ?", (account_id,))

    # ── 交割单 ────────────────────────────────────────────

    def insert_transactions(self, df: pd.DataFrame, account_id: int):
        with self.get_connection() as conn:
            for _, row in df.iterrows():
                code = str(row.get("stock_code", ""))
                # 只对纯数字代码 zfill，非数字代码（如 BANK）原样保留
                if code.isdigit():
                    code = code.zfill(6)
                conn.execute(
                    """INSERT INTO transactions
                       (account_id, trade_date, stock_code, stock_name, trade_type,
                        quantity, price, amount, commission, stamp_tax,
                        transfer_fee, other_fee, settlement, asset_type)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        account_id,
                        row.get("trade_date", ""),
                        code,
                        row.get("stock_name", ""),
                        row.get("trade_type", ""),
                        float(row.get("quantity", 0) or 0),
                        float(row.get("price", 0) or 0),
                        float(row.get("amount", 0) or 0),
                        float(row.get("commission", 0) or 0),
                        float(row.get("stamp_tax", 0) or 0),
                        float(row.get("transfer_fee", 0) or 0),
                        float(row.get("other_fee", 0) or 0),
                        float(row.get("settlement", 0) or 0),
                        row.get("asset_type", "stock"),
                    ),
                )

    def get_transactions(self, account_id: int, start_date=None, end_date=None) -> pd.DataFrame:
        sql = "SELECT * FROM transactions WHERE account_id = ?"
        params = [account_id]
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        sql += " ORDER BY trade_date ASC, id ASC"
        with self.get_connection() as conn:
            df = pd.read_sql_query(sql, conn, params=params)
        if "asset_type" not in df.columns:
            df["asset_type"] = "stock"
        return df

    # ── 资金流水 ──────────────────────────────────────────

    def insert_fund_flows(self, df: pd.DataFrame, account_id: int):
        with self.get_connection() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT INTO fund_flows
                       (account_id, flow_date, flow_type, stock_code, stock_name,
                        amount, balance, description)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (
                        account_id,
                        row.get("flow_date", ""),
                        row.get("flow_type", ""),
                        str(row.get("stock_code", "")).zfill(6) if row.get("stock_code") and str(row.get("stock_code")) != "nan" else "",
                        row.get("stock_name", ""),
                        float(row.get("amount", 0) or 0),
                        float(row["balance"]) if pd.notna(row.get("balance")) else None,
                        row.get("description", ""),
                    ),
                )

    def get_fund_flows(self, account_id: int, start_date=None, end_date=None) -> pd.DataFrame:
        sql = "SELECT * FROM fund_flows WHERE account_id = ?"
        params = [account_id]
        if start_date:
            sql += " AND flow_date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND flow_date <= ?"
            params.append(end_date)
        sql += " ORDER BY flow_date ASC, id ASC"
        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    # ── 持仓 ──────────────────────────────────────────────

    def get_holdings(self, account_id: int) -> pd.DataFrame:
        with self.get_connection() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM holdings WHERE account_id = ? AND quantity > 0 ORDER BY stock_code",
                conn, params=[account_id],
            )
        # 确保 asset_type 列存在（防御性，应对迁移边界情况）
        if "asset_type" not in df.columns:
            df["asset_type"] = "stock"
        return df

    def replace_holdings(self, account_id: int, holdings_list: list[dict]):
        with self.get_connection() as conn:
            conn.execute("DELETE FROM holdings WHERE account_id = ?", (account_id,))
            for h in holdings_list:
                conn.execute(
                    """INSERT INTO holdings
                       (account_id, stock_code, stock_name, quantity, cost_price, total_cost, asset_type)
                       VALUES (?,?,?,?,?,?,?)""",
                    (
                        account_id,
                        h["stock_code"],
                        h.get("stock_name", ""),
                        h["quantity"],
                        h["cost_price"],
                        h["total_cost"],
                        h.get("asset_type", "stock"),
                    ),
                )

    # ── 每日资产快照 ──────────────────────────────────────

    def get_daily_assets(self, account_id: int) -> pd.DataFrame:
        with self.get_connection() as conn:
            return pd.read_sql_query(
                "SELECT * FROM daily_assets WHERE account_id = ? ORDER BY snapshot_date ASC",
                conn, params=[account_id],
            )

    def save_daily_asset(self, account_id: int, date_str, cash, market_value, total, net_value=None, cash_like_value=0):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO daily_assets
                   (account_id, snapshot_date, cash_balance, market_value, cash_like_value, total_assets, net_value)
                   VALUES (?,?,?,?,?,?,?)""",
                (account_id, date_str, cash, market_value, cash_like_value, total, net_value),
            )

    def replace_daily_assets(self, account_id: int, records: list[dict]):
        """批量替换每日资产快照（先删后插）"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM daily_assets WHERE account_id = ?", (account_id,))
            conn.executemany(
                """INSERT INTO daily_assets
                   (account_id, snapshot_date, cash_balance, market_value, cash_like_value, total_assets, net_value)
                   VALUES (?,?,?,?,?,?,?)""",
                [
                    (account_id, r["date"], r["cash_balance"], r["market_value"],
                     r.get("cash_like_value", 0), r["total_assets"], r.get("net_value"))
                    for r in records
                ],
            )

    # ── 上传记录 ──────────────────────────────────────────

    def log_upload(self, account_id: int, filename, file_type, record_count, status="success", message=""):
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO upload_log
                   (account_id, filename, file_type, record_count, status, message)
                   VALUES (?,?,?,?,?,?)""",
                (account_id, filename, file_type, record_count, status, message),
            )

    def get_upload_history(self, account_id: int | None = None) -> pd.DataFrame:
        sql = "SELECT u.*, a.name as account_name, a.broker FROM upload_log u LEFT JOIN accounts a ON u.account_id = a.id"
        params = []
        if account_id is not None:
            sql += " WHERE u.account_id = ?"
            params.append(account_id)
        sql += " ORDER BY u.upload_time DESC"
        with self.get_connection() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    # ── 统计 & 辅助 ───────────────────────────────────────

    def get_cash_balance(self, account_id: int) -> float:
        """获取指定账户最新现金余额

        优先级：
        1. 资金流水表中最新的 balance 字段
        2. 资金流水 amount 字段累加
        3. 交割单 settlement 字段推算
        """
        with self.get_connection() as conn:
            # 优先：资金流水中的最新余额
            row = conn.execute(
                "SELECT balance FROM fund_flows WHERE account_id = ? AND balance IS NOT NULL "
                "ORDER BY flow_date DESC, id DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            if row and row["balance"] is not None:
                return row["balance"]

            # 其次：资金流水 amount 累加
            row = conn.execute(
                "SELECT COALESCE(SUM(amount), 0) AS v FROM fund_flows WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            if row and row["v"] != 0:
                return row["v"]

            # 最后：从交割单推算
            row = conn.execute(
                "SELECT COALESCE(SUM(settlement), 0) AS v FROM transactions WHERE account_id = ?",
                (account_id,),
            ).fetchone()
            return row["v"]

    def get_total_deposits(self, account_id: int) -> float:
        """累计净转入资金（银行转入 - 银行转出）"""
        with self.get_connection() as conn:
            # 转入类：银行转存、银行转证券、银证转入、入金
            row = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) AS v FROM fund_flows
                   WHERE account_id = ?
                     AND amount > 0
                     AND (flow_type LIKE '%银行转存%'
                       OR flow_type LIKE '%银行转取%'
                       OR flow_type LIKE '%银证转%'
                       OR flow_type LIKE '%存管%转入%'
                       OR flow_type LIKE '%银行转%证券%'
                       OR flow_type LIKE '%入金%'
                       OR flow_type LIKE '%存入%')""",
                (account_id,),
            ).fetchone()
            deposits = row["v"] if row["v"] > 0 else 0

            # 转出类：银行转取、证券转银行、银证转出、出金
            row = conn.execute(
                """SELECT COALESCE(SUM(amount), 0) AS v FROM fund_flows
                   WHERE account_id = ?
                     AND amount < 0
                     AND (flow_type LIKE '%银行转取%'
                       OR flow_type LIKE '%银行转存%'
                       OR flow_type LIKE '%银证转%'
                       OR flow_type LIKE '%存管%转出%'
                       OR flow_type LIKE '%银行转出%'
                       OR flow_type LIKE '%出金%'
                       OR flow_type LIKE '%取出%')""",
                (account_id,),
            ).fetchone()
            withdrawals = abs(row["v"]) if row["v"] < 0 else 0

            return deposits - withdrawals

    def get_transaction_count(self, account_id: int) -> int:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM transactions WHERE account_id = ?",
                (account_id,),
            ).fetchone()["c"]

    def get_fund_flow_count(self, account_id: int) -> int:
        with self.get_connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS c FROM fund_flows WHERE account_id = ?",
                (account_id,),
            ).fetchone()["c"]

    def clear_account_data(self, account_id: int):
        """清空指定账户的所有数据（不删账户本身）"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM transactions WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM fund_flows   WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM holdings     WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM daily_assets WHERE account_id = ?", (account_id,))
            conn.execute("DELETE FROM upload_log   WHERE account_id = ?", (account_id,))

    def clear_all_data(self):
        """清空全部数据（包括账户）"""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM transactions")
            conn.execute("DELETE FROM fund_flows")
            conn.execute("DELETE FROM holdings")
            conn.execute("DELETE FROM daily_assets")
            conn.execute("DELETE FROM upload_log")
            conn.execute("DELETE FROM accounts")
