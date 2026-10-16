"""Copies the source tables from app_db into warehouse.raw.

Three modes:
  full         first load of a table, or --full-refresh: truncate and reload everything
  incremental  default: pull rows changed since the newest updated_at in raw, minus a lookback window
  backfill     --start-date (and optionally --end-date): re-pull rows in that updated_at range

Incremental and backfill loads replace rows by id, so running them again changes nothing.
"""

import argparse
from datetime import date, datetime, time, timedelta, timezone

import psycopg
from psycopg import sql

from ingestion.config import SOURCE_DSN, WAREHOUSE_DSN, TABLES

LOG_TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS raw._load_log (
        table_name TEXT NOT NULL,
        mode TEXT NOT NULL,
        rows_pulled INTEGER,
        rows_total INTEGER NOT NULL,
        finished_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
"""


def get_columns(src_conn, schema, table):
    rows = src_conn.execute(
        """
        SELECT column_name, data_type, character_maximum_length
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        ORDER BY ordinal_position
        """,
        (schema, table),
    ).fetchall()
    if not rows:
        raise ValueError(f"Source table {schema}.{table} not found!")
    return rows


def column_type(data_type, max_len):
    if data_type in ("character varying", "character") and max_len:
        return f"{data_type}({max_len})"
    return data_type


def ensure_raw_table(war_cur, dst, columns):
    defs = [
        sql.SQL("{} {}").format(sql.Identifier(name), sql.SQL(column_type(data_type, max_len)))
        for name, data_type, max_len in columns
    ]
    war_cur.execute(
        sql.SQL("CREATE TABLE IF NOT EXISTS {} ({}, _loaded_at TIMESTAMPTZ DEFAULT NOW())").format(
            dst, sql.SQL(", ").join(defs)
        )
    )


def sync_columns(war_cur, dst, dst_schema, dst_table, columns):
    """Schema drift: a column that appeared in the source is added to raw. Never drops anything."""
    war_cur.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = %s AND table_name = %s",
        (dst_schema, dst_table),
    )
    existing = {row[0] for row in war_cur.fetchall()}
    for name, data_type, max_len in columns:
        if name not in existing:
            war_cur.execute(
                sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                    dst, sql.Identifier(name), sql.SQL(column_type(data_type, max_len))
                )
            )
            print(f"  schema drift: added column {name} to {dst_schema}.{dst_table}")
    source_names = {c[0] for c in columns}
    for name in sorted(existing - source_names - {"_loaded_at"}):
        print(f"  schema drift: column {name} is no longer in the source, raw keeps it (now null for new rows)")


def stream(src_cur, war_cur, select_sql, params, target, column_list):
    """Stream rows from a source query into a warehouse table with two COPY statements."""
    copy_out = sql.SQL("COPY ({}) TO STDOUT WITH BINARY").format(select_sql)
    copy_in = sql.SQL("COPY {} ({}) FROM STDIN WITH BINARY").format(target, column_list)
    with src_cur.copy(copy_out, params) as source:
        with war_cur.copy(copy_in) as destination:
            for block in source:
                destination.write(block)


def to_timestamp(day):
    return datetime.combine(date.fromisoformat(day), time.min, tzinfo=timezone.utc)


def load(src_conn, war_conn, source, target, full_refresh, lookback_minutes, start_date=None, end_date=None):
    src_schema, src_table = source.split(".")
    dst_schema, dst_table = target.split(".")
    src, dst = sql.Identifier(src_schema, src_table), sql.Identifier(dst_schema, dst_table)
    columns = get_columns(src_conn, src_schema, src_table)
    column_list = sql.SQL(", ").join(sql.Identifier(c[0]) for c in columns)
    backfill = start_date is not None

    with src_conn.cursor() as src_cur, war_conn.cursor() as war_cur:
        ensure_raw_table(war_cur, dst, columns)
        sync_columns(war_cur, dst, dst_schema, dst_table, columns)
        war_cur.execute(sql.SQL("SELECT max(updated_at) FROM {}").format(dst))
        cursor_value = war_cur.fetchone()[0]

        if full_refresh or (cursor_value is None and not backfill):
            war_cur.execute(sql.SQL("TRUNCATE {}").format(dst))
            select_all = sql.SQL("SELECT {} FROM {}").format(column_list, src)
            stream(src_cur, war_cur, select_all, None, dst, column_list)
            mode, pulled = "full", None
        else:
            if backfill:
                params = [to_timestamp(start_date)]
                where = sql.SQL("updated_at >= %s")
                if end_date:
                    params.append(to_timestamp(end_date))
                    where = sql.SQL("updated_at >= %s AND updated_at < %s")
                mode = "backfill"
            else:
                params = [cursor_value - timedelta(minutes=lookback_minutes)]
                where = sql.SQL("updated_at >= %s")
                mode = "incremental"
            war_cur.execute(
                sql.SQL("CREATE TEMP TABLE batch ON COMMIT DROP AS SELECT {} FROM {} LIMIT 0").format(
                    column_list, dst
                )
            )
            select_new = sql.SQL("SELECT {} FROM {} WHERE {}").format(column_list, src, where)
            stream(src_cur, war_cur, select_new, params, sql.Identifier("batch"), column_list)
            war_cur.execute("SELECT count(*) FROM batch")
            pulled = war_cur.fetchone()[0]
            war_cur.execute(sql.SQL("DELETE FROM {} AS t USING batch WHERE t.id = batch.id").format(dst))
            war_cur.execute(
                sql.SQL("INSERT INTO {} ({}) SELECT {} FROM batch").format(dst, column_list, column_list)
            )

        war_cur.execute(sql.SQL("SELECT count(*) FROM {}").format(dst))
        total = war_cur.fetchone()[0]
        # Same transaction as the data: a failed load rolls back its log row too.
        war_cur.execute(
            "INSERT INTO raw._load_log (table_name, mode, rows_pulled, rows_total) VALUES (%s, %s, %s, %s)",
            (dst_table, mode, pulled, total),
        )
    war_conn.commit()
    return {"table": f"{dst_schema}.{dst_table}", "mode": mode, "rows_pulled": pulled, "rows_total": total}


def run(full_refresh=False, lookback_minutes=60, start_date=None, end_date=None, tables=None):
    """Load every table (or the given source tables). Returns one result per table."""
    results = []
    with psycopg.connect(SOURCE_DSN, autocommit=True) as src_conn, psycopg.connect(WAREHOUSE_DSN) as war_conn:
        war_conn.execute("CREATE SCHEMA IF NOT EXISTS raw")
        war_conn.execute(LOG_TABLE_DDL)
        war_conn.commit()
        for source, target in TABLES.items():
            if tables and source not in tables:
                continue
            result = load(src_conn, war_conn, source, target, full_refresh, lookback_minutes, start_date, end_date)
            detail = "" if result["rows_pulled"] is None else f", pulled {result['rows_pulled']}"
            print(f"{result['table']}: {result['mode']}{detail}, {result['rows_total']} rows in raw")
            results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full-refresh", action="store_true", help="truncate and reload every table")
    parser.add_argument(
        "--lookback-minutes", type=int, default=60,
        help="re-read this much time before the cursor to catch late commits",
    )
    parser.add_argument("--start-date", help="backfill: re-pull rows with updated_at on or after this date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="backfill: stop before this date (YYYY-MM-DD), needs --start-date")
    parser.add_argument("--table", action="append", help="only this source table, for example chargebee.customer")
    args = parser.parse_args()
    if args.end_date and not args.start_date:
        parser.error("--end-date needs --start-date")
    if args.start_date and args.full_refresh:
        parser.error("--start-date and --full-refresh cannot be combined")
    run(args.full_refresh, args.lookback_minutes, args.start_date, args.end_date, args.table)


if __name__ == "__main__":
    main()
