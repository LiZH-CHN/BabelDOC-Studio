"""
SQLite 工具模块
提供带 WAL 和 busy_timeout 的安全 SQLite 连接工厂
"""

import sqlite3


def safe_sqlite_connect(db_path, timeout: float = 30.0):
    """创建带 WAL 和 busy_timeout 的 SQLite 连接。

    Args:
        db_path: 数据库路径
        timeout: busy_timeout（秒），默认 30s

    Returns:
        sqlite3.Connection 已配置 WAL 的连接
    """
    conn = sqlite3.connect(db_path, timeout=timeout)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        # 正常同步级别，兼顾安全与性能
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.OperationalError:
        pass
    return conn