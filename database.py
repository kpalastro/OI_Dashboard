"""
Minimal database module for OI Dashboard.
Uses OI_TRACKER_DB_* env vars (load from .env).
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import psycopg2
    from psycopg2 import pool
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

pg_pool = None


def get_db_connection():
    """Create and return a database connection (PostgreSQL)."""
    if not POSTGRES_AVAILABLE:
        raise ImportError("psycopg2 is required. pip install psycopg2-binary")

    db_type = (os.getenv("OI_TRACKER_DB_TYPE") or "postgres").lower()
    if db_type != "postgres":
        raise ValueError("Only PostgreSQL is supported. Set OI_TRACKER_DB_TYPE=postgres")

    global pg_pool
    if pg_pool is None:
        pg_pool = psycopg2.pool.SimpleConnectionPool(
            1, 50,
            user=os.getenv("OI_TRACKER_DB_USER", "root"),
            password=os.getenv("OI_TRACKER_DB_PASSWORD", ""),
            host=os.getenv("OI_TRACKER_DB_HOST", "localhost"),
            port=int(os.getenv("OI_TRACKER_DB_PORT", "5432")),
            database=os.getenv("OI_TRACKER_DB_NAME", "oi_db_live"),
        )
    conn = pg_pool.getconn()
    conn.autocommit = False
    return conn


def release_db_connection(conn):
    """Release connection back to pool."""
    if pg_pool:
        pg_pool.putconn(conn)
    else:
        try:
            conn.close()
        except Exception:
            pass
