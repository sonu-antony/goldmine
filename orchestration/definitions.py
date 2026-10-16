"""Everything Dagster needs to know: assets, checks, jobs, schedules and the failure alert."""

from dagster import (
    AssetSelection,
    DefaultScheduleStatus,
    DefaultSensorStatus,
    Definitions,
    RunFailureSensorContext,
    ScheduleDefinition,
    define_asset_job,
    run_failure_sensor,
)

from orchestration.alerts import send_alert
from orchestration.dbt_assets import dbt_resource, goldmine_dbt_models
from orchestration.ingestion_assets import loader_freshness, raw_tables, source_reconciliation

# Load the raw tables, then build and test every dbt model, in dependency order.
daily_pipeline = define_asset_job(
    name="daily_pipeline",
    selection=AssetSelection.all() | AssetSelection.all_asset_checks(),
    description="Loader, then dbt build, with all checks.",
)

# Cheap and frequent: only the freshness checks on the raw tables, so a stalled loader is noticed within an hour.
freshness_job = define_asset_job(
    name="freshness_job",
    selection=AssetSelection.checks_for_assets(raw_tables) & AssetSelection.checks(*loader_freshness.check_keys),
    description="Checks that the loader ran recently for every table.",
)

daily_schedule = ScheduleDefinition(
    job=daily_pipeline,
    cron_schedule="0 5 * * *",
    execution_timezone="Europe/Berlin",
    default_status=DefaultScheduleStatus.RUNNING,
)

hourly_freshness_schedule = ScheduleDefinition(
    job=freshness_job,
    cron_schedule="15 * * * *",
    execution_timezone="Europe/Berlin",
    default_status=DefaultScheduleStatus.RUNNING,
)


@run_failure_sensor(name="alert_on_failed_run", default_status=DefaultSensorStatus.RUNNING)
def alert_on_failed_run(context: RunFailureSensorContext):
    run = context.dagster_run
    send_alert(f":red_circle: Run {run.run_id[:8]} of {run.job_name} failed: {context.failure_event.message}", context.log)


defs = Definitions(
    assets=[raw_tables, goldmine_dbt_models],
    asset_checks=[loader_freshness, source_reconciliation],
    jobs=[daily_pipeline, freshness_job],
    schedules=[daily_schedule, hourly_freshness_schedule],
    sensors=[alert_on_failed_run],
    resources={"dbt": dbt_resource},
)
