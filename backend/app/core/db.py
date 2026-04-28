"""
Shared SQLite connection helper with performance-tuned PRAGMAs.

All services that call sqlite3.connect() should use optimized_connect()
instead to get consistent WAL-safe settings on every connection (not just
on the first init_db() call).
"""
from __future__ import annotations

import sqlite3

# Applied to every new connection.  These are safe under WAL mode:
# - synchronous=NORMAL: skips the extra fsync WAL doesn't need.
# - cache_size=-20000: 20 MB page cache per connection (negative = KB).
# - temp_store=MEMORY: temp tables/indexes live in RAM, not tmp files.
# - mmap_size: 128 MB memory-mapped I/O for read-heavy paths.
_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA cache_size=-20000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=134217728",
    "PRAGMA foreign_keys=ON",
)


def optimized_connect(db_path: str, timeout: float = 30.0) -> sqlite3.Connection:
    """Open a SQLite connection with WAL-optimized PRAGMAs pre-applied."""
    conn = sqlite3.connect(db_path, timeout=timeout, isolation_level=None)
    for pragma in _PRAGMAS:
        conn.execute(pragma)
    return conn
