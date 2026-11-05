"""Tiny forward-only migration runner.

Applies every ``migrations/*.sql`` file that has not been recorded in the
``schema_migrations`` table yet, in filename order. Statements that a fresh
database has already satisfied (duplicate column / already exists) are skipped,
so running this against an up-to-date database is a no-op.

    python migrate.py          # apply pending migrations
    python migrate.py --status # show applied / pending, change nothing
"""
import glob
import os
import sqlite3
import sys

from config import DB_PATH

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "migrations")

IGNORABLE = ("duplicate column name", "already exists")


def _migration_files():
    return sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))


def applied_versions(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def _run(conn, path):
    with open(path, "r", encoding="utf-8") as handle:
        script = handle.read()
    skipped = []
    for statement in script.split(";"):
        statement = statement.strip()
        if not statement:
            continue
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as error:
            message = str(error).lower()
            if any(token in message for token in IGNORABLE):
                skipped.append(statement.splitlines()[0][:60])
                continue
            raise
    return skipped


def run_migrations(conn, verbose=True):
    done = applied_versions(conn)
    applied = []
    for path in _migration_files():
        version = os.path.basename(path)
        if version in done:
            continue
        _run(conn, path)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))
        applied.append(version)
        if verbose:
            print(f"applied {version}")
    if verbose and not applied:
        print("nothing to apply; database is up to date")
    return applied


def pending(conn):
    done = applied_versions(conn)
    return [os.path.basename(p) for p in _migration_files() if os.path.basename(p) not in done]


if __name__ == "__main__":
    connection = sqlite3.connect(DB_PATH)
    if "--status" in sys.argv:
        done = sorted(applied_versions(connection))
        todo = pending(connection)
        print("applied:", ", ".join(done) or "(none)")
        print("pending:", ", ".join(todo) or "(none)")
    else:
        run_migrations(connection)
    connection.close()
