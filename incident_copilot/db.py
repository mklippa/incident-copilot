"""SQLite schema and connection helpers for Incident Copilot."""

import sqlite3

from incident_copilot.paths import DATA_DIR

DB_PATH = DATA_DIR / "incident_copilot.db"

SCHEMA = """
CREATE TABLE customers (
    customer_id  TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    email        TEXT NOT NULL,
    plan         TEXT NOT NULL,
    signup_date  TEXT NOT NULL
);

CREATE TABLE tickets (
    ticket_id      TEXT PRIMARY KEY,
    customer_id    TEXT NOT NULL REFERENCES customers(customer_id),
    subject        TEXT NOT NULL,
    body           TEXT NOT NULL,
    seed_category  TEXT NOT NULL,
    seed_severity  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open',
    created_at     TEXT NOT NULL
);

CREATE TABLE resolutions (
    resolution_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id       TEXT NOT NULL REFERENCES tickets(ticket_id),
    resolution_type TEXT NOT NULL,
    summary         TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def reset_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS resolutions;
        DROP TABLE IF EXISTS tickets;
        DROP TABLE IF EXISTS customers;
        """
    )
    conn.executescript(SCHEMA)
    conn.commit()
