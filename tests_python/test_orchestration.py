from unittest import mock

from dagster import AssetKey

from orchestration import defs
from orchestration.alerts import send_alert
from orchestration.ingestion_assets import RAW_KEYS
from ingestion.config import TABLES


def test_every_raw_table_is_an_asset():
    keys = {spec.key for spec in defs.resolve_all_asset_specs()}
    assert set(RAW_KEYS.values()) <= keys
    assert len(RAW_KEYS) == len(TABLES)


def test_dbt_staging_models_depend_on_the_loader_assets():
    specs = {spec.key: spec for spec in defs.resolve_all_asset_specs()}
    customer = specs[AssetKey(["staging", "stg_chargebee__customer"])]
    assert AssetKey(["raw", "chargebee_customer"]) in {dep.asset_key for dep in customer.deps}


def test_gold_models_are_downstream_of_staging():
    specs = {spec.key: spec for spec in defs.resolve_all_asset_specs()}
    mrr = specs[AssetKey(["gold", "fct_mrr_monthly"])]
    assert {dep.asset_key.path[0] for dep in mrr.deps} == {"intermediate"}


def test_pipeline_has_a_daily_schedule_and_an_hourly_freshness_schedule():
    schedules = {schedule.name: schedule.cron_schedule for schedule in defs.schedules}
    assert schedules["daily_pipeline_schedule"] == "0 5 * * *"
    assert schedules["freshness_job_schedule"] == "15 * * * *"


def test_alert_goes_to_the_log_without_a_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    log = mock.Mock()
    assert send_alert("run failed", log) is False
    log.error.assert_called_once_with("run failed")


def test_alert_posts_to_slack_with_a_webhook(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.example.com/abc")
    with mock.patch("urllib.request.urlopen") as post:
        assert send_alert("run failed", mock.Mock()) is True
    assert post.call_args[0][0].full_url == "https://hooks.example.com/abc"
