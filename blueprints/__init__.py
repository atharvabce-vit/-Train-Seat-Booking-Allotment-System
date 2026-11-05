from contextlib import contextmanager

from db import get_connection


@contextmanager
def db():
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
