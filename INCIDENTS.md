## 2026-10-10 Stalled loader showed up as a stale source (and a false alarm trap)
What broke: Simulated a stalled loader by tightening the freshness limits to 1 hour (warn) and 3 hours (error) on `raw.chargebee_plan`, whose newest `_loaded_at` was about 3 hours 39 minutes old.
How I noticed: `dbt source freshness` returned an error saying the source was stale.
Root cause: Nothing had written to the table for longer than the error limit. Also found the check is unreliable for quiet tables: with an incremental loader, `_loaded_at` only changes on rows that were pulled, so a healthy loader on a table with no source changes would also look stale.
Fix: Ran the loader again, which wrote new rows and made the source fresh, then put the limits back to 12 and 24 hours. To remove the false alarm, the loader now writes one row per table per run into `raw._load_log` in the same transaction as the data, so freshness can be measured on when the loader last finished and not on when data last changed.
What I would say in an interview: I check freshness on the loader's own run log, not only on the data timestamps, and set limits per table based on how often it changes, so a stalled sync is caught and a quiet table does not raise a false alarm.

> Entries from 2026-10-16 were produced by running the failure drills in `sources/simulate_changes.py`
> against this project and recording what actually happened. They are staged failures, not production outages.

## 2026-10-16 A source row changed without a new updated_at
What broke: Someone edited a subscription's seat count directly in the source database (4 to 9) without the application, so `updated_at` and the events log were untouched. The incremental loader, which pulls rows by `updated_at`, never saw it.
How I noticed: I did not, from the pipeline. All 133 dbt tests passed and the loader printed nothing unusual. `python -m ingestion.reconcile`, which compares row counts and column sums between source and raw, reported `sum(quantity): source=1162 raw=1157`. (My first attempt at this drill was misleading: I ran `dbt test` against gold tables I had not rebuilt, so the MRR reconciliation test failed for the wrong reason. Redone with a clean `dbt build` before and after.)
Root cause: A cursor only sees rows whose `updated_at` moved, and the lookback window did not help because the row's timestamp was months old. Tests inside the warehouse compare the warehouse with itself, so they cannot see drift from the source.
Fix: Reloaded just that table with `--full-refresh --table chargebee.subscription`. That exposed a second signal: `assert_subscription_matches_its_last_event` failed, because the events log still said 4 seats. The manual edit was a mistake, so it was reverted in the source and the table reloaded. Reconciliation against the source is now a script that can run on a schedule.
What I would say in an interview: Incremental loads trust the cursor, so I add a reconciliation check against the source (counts and column sums) and keep an invariant between related tables, like subscription state against the events log. Either one catches a silent change that the cursor cannot.

## 2026-10-16 A late commit slipped behind the loader cursor
What broke: A workspace row became visible in the source with an `updated_at` 30 minutes older than the newest row the loader had already seen, as happens when a long transaction commits late. With `--lookback-minutes 0` the loader skipped it.
How I noticed: Reconcile reported `row count: source=303 raw=302` and `sum(id)` differing. The raw table had no row named "Late Commit Workspace".
Root cause: The loader pulled `updated_at >= newest value in raw`. A row stamped before that value is invisible to it.
Fix: The default lookback window of 60 minutes re-reads the hour before the cursor on every run. Running the loader with the default pulled the row (count back to 303). Safe because rows are replaced by `id`.
What I would say in an interview: I never advance a cursor exactly to the newest value. I re-read a window behind it, and I make the load idempotent so the overlap costs nothing. The window is a trade-off between catching late commits and re-reading rows.

## 2026-10-16 Late-arriving messages and the incremental activity model
What broke: Messages that were sent days ago arrived today. An incremental model that only reprocesses recent days by sent date would never correct the older days they belong to. Of 40 late messages inserted, 21 were sent more than 3 days before today.
How I noticed: By design, comparing `fct_workspace_activity_daily` after an incremental run with the result of `--full-refresh`. They matched (61,242 rows, same sums). While checking I also found a real defect in my own model: 25 messages stamped in the future by a server with a wrong clock created activity on days that had not happened yet, and I had first quoted the wrong number (40, measured against that future date) before checking.
Root cause: Event time (when sent) and arrival time (when we received it) differ. The model finds changed days from arrival time (`created_at`), then recomputes every touched (workspace, day) from all its messages. Future-dated rows came from the source and nothing filtered them.
Fix: Keep the arrival-based incremental filter with a lookback, exclude rows where `sent_at > created_at` (a message cannot be sent after it arrived), and add `assert_no_activity_in_the_future`.
What I would say in an interview: For incremental models I filter on arrival time, not event time, recompute the whole affected day, and prove it by comparing against a full refresh. I also put a plausibility rule in the model for impossible timestamps.

## 2026-10-16 A renamed source column turned into nulls downstream
What broke: The product team renamed `users.email` to `email_address`. The loader did not crash: it added the new column to raw and kept the old one. New and updated rows arrived with `email` empty.
How I noticed: `not_null_stg_product__users_email` failed with 26 rows. The loader log said `schema drift: added column email_address`.
Root cause: Staging read only the old column name. Raw is append-only for columns, so one rename upstream silently emptied a column downstream.
Fix: Staging checks which columns exist in raw and reads `coalesce(email_address, email)` when the new one is present. After the product team reverted the rename, a table refresh normalised raw, and the staging model still works for either name.
What I would say in an interview: I make the loader tolerant of added columns, never dropping data, and I rely on `not_null` tests in staging to notice when a rename leaves a column empty. Then I absorb the rename in one staging model and tell the source team.

## 2026-10-16 Repeated rows in raw after a retried load
What broke: Rows were appended to raw twice (3 invoices, 2 customers), as can happen when a sync retries after a partial failure. Redshift does not enforce primary keys, so nothing stops it.
How I noticed: `source_unique_chargebee_chargebee_invoice_id` and `..._customer_id` warned with 3 and 2 repeats, and reconcile showed `row count: source=2690 raw=2693`.
Root cause: Raw accepts whatever arrives. Downstream views were protected by the latest-row guard in staging (staging showed 2,690 invoices and 273 customers while raw held 2,693 and 275), so dashboards stayed right, but nothing would have told anyone without the source tests.
Fix: Reloaded the two tables from the source. The tests went back to passing.
What I would say in an interview: Constraints are not enforced on Redshift, so I deduplicate by key in staging so consumers are protected, and I also test uniqueness on the raw tables so the problem is not hidden.

## 2026-10-16 A bad load corrupted three months of invoice amounts
What broke: A simulated loader bug divided invoice amounts by 100 for July to September (708 rows). Raw no longer matched Chargebee.
How I noticed: Reconcile reported `sum(amount_cents): source=433144601 raw=341986228`.
Root cause: Rows already loaded stay wrong. The incremental cursor only moves forward, so a normal run would never fix them.
Fix: A backfill of just that window: `--start-date 2026-07-01 --end-date 2026-10-01 --table chargebee.invoice`. It pulled 708 rows and replaced them by `id`. Running it a second time pulled the same 708 and changed nothing. Reconcile then reported all 11 tables matching, and the dbt build passed.
What I would say in an interview: I backfill a bounded window, not the whole table, and the load replaces rows by key, so the backfill can run twice safely. I confirm by reconciling source against raw before I rebuild dbt.

## 2026-10-16 The messages loader stalled and the freshness check caught it
What broke: The loader for the busiest table stopped. Simulated by back-dating its entries in `raw._load_log` by 30 hours.
How I noticed: `dbt source freshness` reported `ERROR STALE` for `load_log_product_messages` (limits for that table: warn after 2 hours, error after 6).
Root cause: Nothing wrote to the table for longer than the limit. Because freshness reads the loader's own log, a quiet table that the loader keeps visiting does not trigger a false alarm.
Fix: Ran the loader again. It wrote a new log row and the check passed.
What I would say in an interview: I check freshness on the loader's run log, with a limit per table sized to how often it changes. The busy table has a tight limit and the price list a loose one.

## 2026-10-16 A pull request broke the MRR bridge and CI blocked it
What broke: A pull request changed `fct_mrr_movements` so paused revenue was no longer recorded as a movement ("stop counting paused MRR"). It looked reasonable in review: pauses are not churn, so why show them? The monthly bridge `closing = opening + movements` then no longer added up.
How I noticed: GitHub Actions failed the `dbt build` job on the pull request: `FAIL 3 assert_mrr_bridge_balances`, `Got 3 results, configured to fail if != 0`. The Python tests job passed. The pull request could not merge.
Root cause: A paused customer's revenue leaves MRR, so it must appear as a movement or the bridge has a hole. Pause is a separate movement type from churn, not a missing one. The change fixed a misunderstanding in one place and broke the invariant everywhere else.
Fix: Closed the pull request without merging. The bridge test stays at error severity, not warn, because it protects the definition itself.
What I would say in an interview: CI runs the full dbt build against a database on every pull request, so a change that breaks an invariant, not only a syntax error, is stopped before it merges. I keep the checks that protect metric definitions at error level, and warn only for known source defects.
