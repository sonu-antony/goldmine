"""The loader as Dagster assets: one asset per raw table, plus checks on each one."""

from typing import Optional

import psycopg
from dagster import (
    AssetCheckResult,
    AssetCheckSeverity,
    AssetCheckSpec,
    AssetExecutionContext,
    AssetKey,
    AssetSpec,
    Config,
    MaterializeResult,
    multi_asset,
    multi_asset_check,
)

from ingestion import reconcile
from ingestion.config import TABLES, WAREHOUSE_DSN
from ingestion.load import run

# raw table name (chargebee_customer) -> source table (chargebee.customer)
SOURCE_BY_RAW_NAME = {target.split(".")[1]: source for source, target in TABLES.items()}
RAW_KEYS = {name: AssetKey(["raw", name]) for name in SOURCE_BY_RAW_NAME}

# Hours without a successful load before the freshness check fails. Mirrors goldmine_dbt/models/staging/pipeline/_load_log.yml.
ERROR_AFTER_HOURS = {"product_messages": 6, "chargebee_plan": 24}
DEFAULT_ERROR_AFTER_HOURS = 24


class LoaderConfig(Config):
    """Run configuration. Set start_date (and end_date) to backfill a window instead of loading incrementally."""

    full_refresh: bool = False
    lookback_minutes: int = 60
    start_date: Optional[str] = None
    end_date: Optional[str] = None


@multi_asset(
    specs=[
        AssetSpec(
            key=key,
            group_name="ingestion",
            kinds={"python", "postgres"},
            description=f"Raw copy of {SOURCE_BY_RAW_NAME[name]}, loaded incrementally by ingestion/load.py.",
        )
        for name, key in RAW_KEYS.items()
    ],
    can_subset=True,
)
def raw_tables(context: AssetExecutionContext, config: LoaderConfig):
    sources = [SOURCE_BY_RAW_NAME[key.path[-1]] for key in context.selected_asset_keys]
    results = run(
        full_refresh=config.full_refresh,
        lookback_minutes=config.lookback_minutes,
        start_date=config.start_date,
        end_date=config.end_date,
        tables=sources,
    )
    for result in results:
        name = result["table"].split(".")[1]
        yield MaterializeResult(
            asset_key=RAW_KEYS[name],
            metadata={"mode": result["mode"], "rows_pulled": result["rows_pulled"], "rows_total": result["rows_total"]},
        )


@multi_asset_check(
    specs=[AssetCheckSpec(name="loader_ran_recently", asset=key, blocking=True) for key in RAW_KEYS.values()],
    can_subset=True,
    description="Fails if the loader has not finished a run for this table within its limit (reads raw._load_log).",
)
def loader_freshness(context):
    with psycopg.connect(WAREHOUSE_DSN, autocommit=True) as conn:
        for check_key in context.selected_asset_check_keys:
            name = check_key.asset_key.path[-1]
            limit = ERROR_AFTER_HOURS.get(name, DEFAULT_ERROR_AFTER_HOURS)
            row = conn.execute(
                "SELECT max(finished_at), extract(epoch FROM now() - max(finished_at)) / 3600 "
                "FROM raw._load_log WHERE table_name = %s",
                (name,),
            ).fetchone()
            age_hours = None if row[1] is None else float(row[1])
            yield AssetCheckResult(
                check_name=check_key.name,
                asset_key=check_key.asset_key,
                passed=age_hours is not None and age_hours <= limit,
                severity=AssetCheckSeverity.ERROR,
                metadata={"hours_since_last_load": age_hours, "error_after_hours": limit},
            )


@multi_asset_check(
    specs=[AssetCheckSpec(name="matches_source", asset=key) for key in RAW_KEYS.values()],
    can_subset=True,
    description="Compares row count, newest updated_at and numeric column sums between the source table and raw.",
)
def source_reconciliation(context):
    for check_key in context.selected_asset_check_keys:
        source = SOURCE_BY_RAW_NAME[check_key.asset_key.path[-1]]
        differences = reconcile.run(tables=[source]).get(source, [])
        yield AssetCheckResult(
            check_name=check_key.name,
            asset_key=check_key.asset_key,
            passed=not differences,
            severity=AssetCheckSeverity.WARN,
            metadata={"differences": [f"{name}: source={a} raw={b}" for name, a, b in differences]},
        )
