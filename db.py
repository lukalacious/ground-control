"""
Ground Control — Shared Neon Database Connection
=================================================
Provides connection pooling and helpers for all Python modules.

Usage:
    from db import get_connection, get_dict_cursor

    conn = get_connection()
    with get_dict_cursor() as cur:
        cur.execute("SELECT * FROM listings LIMIT 5")
        rows = cur.fetchall()
"""

import logging
import os
from pathlib import Path

import psycopg2
import psycopg2.extras
from psycopg2.pool import SimpleConnectionPool

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ground-control.db")

_pool: SimpleConnectionPool | None = None


def _get_database_url() -> str:
    """Read DATABASE_URL from environment or from web/.env file."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    # Fall back to web/.env in the project root
    env_path = Path(__file__).parent / "web" / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1].strip().strip('"').strip("'")
                return url

    raise RuntimeError(
        "DATABASE_URL not found in environment or web/.env. "
        "Set DATABASE_URL or create web/.env with the Neon connection string."
    )


def _get_pool() -> SimpleConnectionPool:
    """Initialise or return the existing connection pool."""
    global _pool
    if _pool is None or _pool.closed:
        database_url = _get_database_url()
        _pool = SimpleConnectionPool(minconn=1, maxconn=5, dsn=database_url)
        log.info("Connection pool created (Neon PostgreSQL)")
    return _pool


# ──────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────

def get_connection():
    """Get a connection from the pool. Caller must call release_connection() when done."""
    pool = _get_pool()
    conn = pool.getconn()
    return conn


def release_connection(conn):
    """Return a connection to the pool."""
    pool = _get_pool()
    pool.putconn(conn)


def get_dict_cursor():
    """
    Context manager that yields a DictCursor.
    Automatically commits on success, rolls back on error,
    and releases the connection back to the pool.

    Usage:
        with get_dict_cursor() as cur:
            cur.execute("SELECT * FROM listings")
            rows = cur.fetchall()
    """
    return _DictCursorContext()


class _DictCursorContext:
    """Context manager for dict cursor with auto-commit and connection release."""

    def __init__(self):
        self.conn = None
        self.cursor = None

    def __enter__(self):
        self.conn = get_connection()
        self.cursor = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        return self.cursor

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            if self.cursor:
                self.cursor.close()
            if self.conn:
                release_connection(self.conn)
        return False


def close_pool():
    """Close all connections in the pool. Call on shutdown."""
    global _pool
    if _pool and not _pool.closed:
        _pool.closeall()
        log.info("Connection pool closed")
        _pool = None


# ──────────────────────────────────────────────────────────────────────
# CLI — quick connectivity test
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ground Control — Database Connection Test")
    parser.add_argument("--query", default="SELECT COUNT(*) AS cnt FROM listings", help="SQL to run")
    args = parser.parse_args()

    try:
        with get_dict_cursor() as cur:
            cur.execute(args.query)
            rows = cur.fetchall()
            for row in rows:
                print(dict(row))
        print("Connection OK")
    except Exception as e:
        print(f"Connection failed: {e}")
    finally:
        close_pool()
