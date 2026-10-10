import argparse
from datetime import timedelta

import psycopg
from psycopg import sql

from ingestion.config import SOURCE_DSN, WAREHOUSE_DSN, TABLES


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


def stream(src_cur, war_cur, select_sql, params, target, column_list):
    """Stream rows from a source query into a warehouse table with two COPY statements."""
    copy_out = sql.SQL("COPY ({}) TO STDOUT WITH BINARY").format(select_sql)
    copy_in = sql.SQL("COPY {} ({}) FROM STDIN WITH BINARY").format(target, column_list)
    with src_cur.copy(copy_out, params) as source:
        with war_cur.copy(copy_in) as destination:
            for block in source:
                destination.write(block)


def load(src_conn, war_conn, src_schema, src_table, dst_schema, dst_table, full_refresh, lookback_minutes):
    src, dst = sql.Identifier(src_schema, src_table), sql.Identifier(dst_schema, dst_table)
    columns = get_columns(src_conn, src_schema, src_table)
    column_list = sql.SQL(", ").join(sql.Identifier(c[0]) for c in columns)

    with src_conn.cursor() as src_cur, war_conn.cursor() as war_cur:
        ensure_raw_table(war_cur, dst, columns)
        war_cur.execute(sql.SQL("SELECT max(updated_at) FROM {}").format(dst))
        cursor_value = war_cur.fetchone()[0]

        if full_refresh or cursor_value is None:
            war_cur.execute(sql.SQL("TRUNCATE {}").format(dst))
            select_all = sql.SQL("SELECT {} FROM {}").format(column_list, src)
            stream(src_cur, war_cur, select_all, None, dst, column_list)
            mode, pulled = "full", None
        else:
            cutoff = cursor_value - timedelta(minutes=lookback_minutes)
            war_cur.execute(
                sql.SQL("CREATE TEMP TABLE batch ON COMMIT DROP AS SELECT {} FROM {} LIMIT 0").format(
                    column_list, dst
                )
            )
            select_new = sql.SQL("SELECT {} FROM {} WHERE updated_at >= %s").format(column_list, src)
            stream(src_cur, war_cur, select_new, (cutoff,), sql.Identifier("batch"), column_list)
            war_cur.execute("SELECT count(*) FROM batch")
            pulled = war_cur.fetchone()[0]
            war_cur.execute(sql.SQL("DELETE FROM {} AS t USING batch WHERE t.id = batch.id").format(dst))
            war_cur.execute(
                sql.SQL("INSERT INTO {} ({}) SELECT {} FROM batch").format(dst, column_list, column_list)
            )
            mode = "incremental"

        war_cur.execute(sql.SQL("SELECT count(*) FROM {}").format(dst))
        total = war_cur.fetchone()[0]
    war_conn.commit()

    detail = "" if pulled is None else f", pulled {pulled}"
    print(f"{dst_schema}.{dst_table}: {mode}{detail}, {total} rows in raw")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--full-refresh", action="store_true", help="truncate and reload every table")
    parser.add_argument(
        "--lookback-minutes", type=int, default=60,
        help="re-read this much time before the cursor to catch late commits",
    )
    args = parser.parse_args()

    with psycopg.connect(SOURCE_DSN, autocommit=True) as src_conn, psycopg.connect(WAREHOUSE_DSN) as war_conn:
        for source, target in TABLES.items():
            src_schema, src_table = source.split(".")
            dst_schema, dst_table = target.split(".")
            load(
                src_conn, war_conn, src_schema, src_table, dst_schema, dst_table,
                args.full_refresh, args.lookback_minutes,
            )


if __name__ == "__main__":
    main()
