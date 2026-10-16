# Runbook

What to do when something breaks. Every item here was exercised as a drill; see `INCIDENTS.md` for what actually happened.

Commands assume the repository root and the virtual environment (`make` targets are in the `Makefile`).

## A dbt test fails

1. Read the failing test name. It says the model, the column and the rule.
2. Is it `warn` or `error`? Warn-level tests are known source defects, with the reason in the YAML beside them. Only an **increase** in a warn count is news.
3. Look at the rows. `dbt test --store-failures` saves failing rows; or run the test query from `target/compiled/`.
4. Walk backwards through the layers: is the value wrong in gold, in intermediate, in staging, or already in raw?
5. If raw is wrong, compare with the source: `python -m ingestion.reconcile`.
6. Fix at the earliest layer that owns the problem. Do not patch a number in gold if staging is wrong.

## The freshness check is stale

`dbt source freshness` or the `loader_ran_recently` check in Dagster fails. The loader has not finished a run for that table within its limit.

1. Look at `raw._load_log` for that table: when was the last row, and what mode?
2. Look at the loader run in Dagster, or run `python -m ingestion.load --table <source table>` and read the error.
3. Common causes: a source schema change, a connection failure, a long lock on the source.
4. After it succeeds, the next freshness run passes. Nothing to reset.

## Reconciliation mismatch

`python -m ingestion.reconcile` reports a table where source and raw differ.

- **Row count lower in raw:** rows missed. Late commit beyond the lookback, or a failed load. Backfill the window.
- **Row count higher in raw:** repeated rows from a retried load. Reload the table: `python -m ingestion.load --full-refresh --table <source table>`.
- **Counts match but a sum differs:** a row changed without a new `updated_at`, or a bad load corrupted values. Reload that table. Then ask the source owner why `updated_at` did not move.

## Backfill a date range

```
python -m ingestion.load --start-date 2026-07-01 --end-date 2026-10-01 --table chargebee.invoice
python -m ingestion.reconcile
cd goldmine_dbt && dbt build --select source:chargebee.chargebee_invoice+   # rebuild everything downstream
```

Safe to run twice: rows are replaced by `id`. Start with one table and check with reconcile before widening. In Dagster, pass `start_date` and `end_date` in the run configuration of `raw_tables`.

## A source column was renamed

The loader adds the new column to raw and keeps the old one, so it does not crash. The break shows up as nulls in a `not_null` test. Fix the staging model to accept both names (see `stg_product__users`), tell the source team, and keep the tolerant version until the old name is gone everywhere.

## Late-arriving data

`fct_workspace_activity_daily` finds changed days from message **arrival** time and recomputes each touched day. Rows arriving later than the three-day lookback need `dbt run --full-refresh --select fct_workspace_activity_daily`.

## Finance says MRR does not match Chargebee

1. Run `dbt test --select assert_mrr_reconciles_with_chargebee assert_mrr_bridge_balances`. The first compares this month's modelled MRR with the current state of every subscription; the second proves the monthly bridge adds up.
2. If both pass, the models are internally right. Compare definitions: does Chargebee's number include paused or trial subscriptions, taxes, or discounts? Do they count `non_renewing`?
3. Check the date: our current month is month to date, Chargebee's report may be for a closed month.
4. Check test accounts and internal workspaces, which are excluded here.
5. If the reconciliation test fails, check `ingestion.reconcile` first. A stale raw table makes both sides look right to dbt.

## Duplicates in a gold table

Check the grain: `unique_combination_of_columns` tests on the fact tables name the columns that define a row. A duplicate almost always comes from a join that multiplies rows, for example joining customers to subscriptions when a customer has two. Find the join in the intermediate model, and compare `count(*)` with `count(distinct <grain>)` before and after it.
