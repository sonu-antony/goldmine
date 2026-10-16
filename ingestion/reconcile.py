"""Reconciles every source table with its raw copy: row count, newest updated_at and the sum of each numeric column.

A cursor-based loader cannot see a row that changed without a new updated_at. This check compares
the two sides directly, so that kind of silent drift shows up. Run it from the repository root:

    .venv/bin/python -m ingestion.reconcile            exits with code 1 if anything differs
"""

import sys

import psycopg
from psycopg import sql

from ingestion.config import SOURCE_DSN, WAREHOUSE_DSN, TABLES

NUMERIC_TYPES = ("smallint", "integer", "bigint", "numeric")


def fingerprint(conn, schema, table, numeric_columns):
    parts = [sql.SQL("count(*)"), sql.SQL("max(updated_at)")]
    parts += [sql.SQL("sum({})").format(sql.Identifier(c)) for c in numeric_columns]
    query = sql.SQL("SELECT {} FROM {}").format(sql.SQL(", ").join(parts), sql.Identifier(schema, table))
    return conn.execute(query).fetchone()


def compare(src_conn, war_conn, source, target):
    src_schema, src_table = source.split(".")
    dst_schema, dst_table = target.split(".")
    numeric_columns = [
        row[0]
        for row in src_conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name = %s AND data_type = ANY(%s) ORDER BY ordinal_position",
            (src_schema, src_table, list(NUMERIC_TYPES)),
        ).fetchall()
    ]
    names = ["row count", "newest updated_at"] + [f"sum({c})" for c in numeric_columns]
    left = fingerprint(src_conn, src_schema, src_table, numeric_columns)
    right = fingerprint(war_conn, dst_schema, dst_table, numeric_columns)
    return [(name, a, b) for name, a, b in zip(names, left, right) if a != b]


def run(tables=None):
    """Returns {source table: list of (what, source value, raw value)} for every table that differs."""
    problems = {}
    with psycopg.connect(SOURCE_DSN, autocommit=True) as src_conn, psycopg.connect(WAREHOUSE_DSN, autocommit=True) as war_conn:
        for source, target in TABLES.items():
            if tables and source not in tables:
                continue
            differences = compare(src_conn, war_conn, source, target)
            if differences:
                problems[source] = differences
    return problems


def main():
    problems = run()
    if not problems:
        print(f"OK: all {len(TABLES)} raw tables match their source")
        return 0
    for source, differences in problems.items():
        print(f"MISMATCH {source}")
        for name, source_value, raw_value in differences:
            print(f"    {name}: source={source_value} raw={raw_value}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
