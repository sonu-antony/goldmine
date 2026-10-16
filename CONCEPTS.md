# CONCEPTS.md: short notes to reread

One entry per concept, added when it is taught.

## Incremental model compared with full refresh
- Incremental: each run processes only rows that are new or changed since the last run. With a `unique_key` it updates existing rows, so it is not an append-only log. Backend analogy: a sync that pulls rows past the last cursor.
- Full refresh: rebuild the whole table from the source every run. Simple and always correct, but slow and expensive on tens of millions of rows.
- The trade-off is run cost and time against simplicity and correctness. The finished table reads equally fast either way.
- Risk of incremental: a wrong cursor loses or duplicates rows, and you repair it with a full refresh.
- Keeping history is a different feature (snapshots, Session 6), not a property of incremental models.

## Source system
- The system that owns the data: HubSpot, Chargebee, the product database. It is not the thing that extracts data (that is ingestion: Airbyte or my Python loader).
- It keeps only current state because it is an operational system: a plan change is an `UPDATE` and the old value is gone.
- Cost for an analyst: "which plan was this customer on last March?" cannot be answered unless the warehouse captured it at the time.

## `app_db` and `warehouse`, and where staging sits
- `app_db` pretends to be all the sources together (product database, Chargebee, HubSpot). `warehouse` pretends to be Redshift.
- Staging is a dbt layer (schema) inside the warehouse, not a database.
- They are separate databases because real sources and a real warehouse are different systems. Moving data across is the ingestion job. Redshift also restricts cross-database queries.

## dbt
- Builds tables and views inside the warehouse from SQL. It does not move data and does not store data. Ingestion (my Python loader, Airbyte) fills `raw`, then dbt takes over.
- A model is one `SELECT` in one `.sql` file. dbt adds the `CREATE VIEW` or `CREATE TABLE`.
- `ref('other_model')` works like an import: it tells dbt the build order and gives the dependency graph.
- Tests are assertions on data (not null, unique), written in YAML and run as queries against the built tables.
- Loop: write `SELECT` files, run `dbt build`, dbt builds in order and runs the tests.
- Pipeline: `app_db` --loader--> `warehouse.raw` --dbt--> staging, intermediate, gold.

## Who does what: warehouse, loader, dbt
- Warehouse (Redshift, here the `warehouse` database): stores data and runs SQL. It never pulls data from anywhere. Like PostgreSQL, which does not call the HubSpot API.
- Loader (Airbyte or custom Python): moves data from the sources into the warehouse. Like my adapter code writing API results into PostgreSQL.
- dbt: connects only to the warehouse and transforms data already inside it. It never touches `app_db`.
- Flow: sources --loader--> warehouse.raw --dbt--> staging, intermediate, gold.

## Shape of a SaaS company's data
- Three systems, each owns a slice: product database (what customers do: workspaces, users, messages), Chargebee (what they pay: customers, plans, subscriptions, invoices), HubSpot (what sales told them: companies, deals).
- No shared database, so no foreign keys across systems. The link is a plain value (for example a workspace identifier stored on a Chargebee customer). Nothing enforces it, so it can be missing or wrong.
- Every source keeps current state only: an upgrade updates the subscription row and the old plan is gone.
- `updated_at` on every table is what lets a loader ask "what changed since last time?" (the cursor, Session 2).

## Price on the subscription, not only on the plan
- `plan` is today's price list. A `subscription` is a contract signed at some price. Like an order line storing the price paid, not pointing at the product's current price.
- Existing customers can keep an old price after a plan price rise, get discounts, or have several seats. So the subscription stores its own `plan_amount_cents` and `quantity`.
- Monthly revenue of a subscription = `plan_amount_cents * quantity`. Joining to `plan` would rewrite past revenue whenever the list price changes.

## Chargebee billing lifecycle (real version, with what my build simplifies)
- Core objects: `customer`, `subscription` (central), `invoice` (one bill per billing event), `credit_note` (a credit or refund against an invoice).
- Subscription `status`: `future`, `in_trial`, `active`, `non_renewing`, `paused`, `cancelled`. (Also `transferred`, rare.)
  - `cancelled` is always the final state. Cancel immediately: straight to `cancelled`. Cancel at end of term: `active` then `non_renewing` (still access, still revenue) then `cancelled` when the term ends.
  - `paused`: no billing and no access, comes back later. MRR counts it as zero, but it is not churn.
- Plan change: the same subscription row is updated in place, `updated_at` moves, old plan gone. Upgrade mid-term raises a prorated invoice. Downgrade usually produces a credit note, not an invoice. Depending on settings the change can take effect at end of term instead of immediately.
- Cancellation: row never deleted. Reactivation flips the same row back to `active` and the cancellation disappears.
- Invoice statuses: `paid`, `posted`, `payment_due`, `not_paid`, `voided`, `pending`. `not_paid` is how failed payments show up, which feeds involuntary churn.
- Field names and types: `cancelled_at`, not `cancelled_date`. Dates are Unix timestamps (`created_at`, `updated_at`, `activated_at`, `current_term_start`, `current_term_end`, `trial_end`, `cancelled_at`). Amounts are in cents. Staging models clean both.
- Plan model: `plan` is the older shape. Newer accounts use Product Catalog 2.0: `item` (the product), `item_price` (a price point per currency and billing period), `subscription_item` (links a subscription to several item prices). Both shapes exist.
- Events log: Chargebee records every change (`subscription_changed`, `subscription_cancelled`, ...) as an event carrying the object's state at that moment, and connectors like Airbyte can sync it. So history is not lost at the source. But the events are messy to model.
- Why snapshots instead of events: the subscription table overwrites itself, events can rebuild history but are hard to model, so a dbt snapshot on the subscription table is the simpler way to capture plan history going forward (Session 6).
- What my build simplifies: `cancelled_date` instead of `cancelled_at`, `plan` instead of the item model, three invoice statuses (no `not_paid`, `posted`, `pending`), `DATE`/`TIMESTAMPTZ` instead of Unix timestamps. My build does include `paused` subscriptions and a `credit_note` table (downgrade credits and refunds).

## Grain
- Grain = what one row of a table represents, stated in one sentence ("one row per workspace").
- Like `orders` compared with `order_items`: join them and count rows, and you now count items, not orders.
- If you do not know the grain you cannot spot a join that duplicates rows, and sums and counts silently double.

## Orphan rows and nulls in join columns
- Orphan row: a row whose foreign key value points to nothing (a message whose `user_id` has no matching user). Real sources often lack enforced foreign keys or use soft deletes, so orphans appear.
- Inner join drops orphans and rows with a null key. Left join keeps them with null columns on the other side.
- dbt `relationships` test checks that every foreign key value exists in the parent table (Session 4).
- `users` grain: one row per person inside one workspace. Email is not unique, so the same person in two workspaces is two rows.

## Snapshots (preview, built by hand in Session 6)
- A real design choice used across data teams, not specific to this project. Slowly changing dimension type 2 (SCD2), built into dbt as `dbt snapshot`. Like an append-only ledger added onto a source that keeps only current state.
- Each run compares current source rows with the stored rows. Unchanged rows stay. A changed row gets its old version closed (`dbt_valid_to` set) and a new version inserted (`dbt_valid_from` set, `dbt_valid_to` empty). Result: one row per version of a subscription.
- Answers "which plan was this customer on last March?"
- Limits: it only sees the state at the time it ran (two changes between runs show only the final one), and it has no history before its first run.
- Snapshots compared with the events log: snapshot is simple and good going forward. Events are complete and can rebuild older history, but are messy to model.
- Ingestion here is Airbyte or custom Python, orchestration is Dagster. Never Airflow in this story.

## Layers and the raw layer
- Raw: data exactly as it arrived from the source, no cleaning, no business logic. Staging: clean each source's quirks once. Intermediate: combine cleaned sources. Gold: shaped for one consumer.
- Why layers: when something breaks you know which layer to look at, and raw lets you rebuild everything downstream without calling the source again.
- Raw tables have no primary key or foreign key constraints: they must accept whatever arrives, including duplicates. (Redshift does not enforce them anyway, they are informational only.)
- Real tools add load metadata: Airbyte adds `_airbyte_raw_id`, `_airbyte_extracted_at`, `_airbyte_meta`. We add `_loaded_at`.

## Full load compared with incremental load
- Full load: replace the whole raw table from the source every run. Simple, always correct, cost grows with table size.
- Incremental load: pull only rows with `updated_at` after the last cursor value. Fast, but a wrong cursor loses or duplicates rows.
- Redshift: bulk loads use `COPY` from S3, never row-by-row inserts. Row inserts are very slow on a columnar warehouse.

## Staging, intermediate and gold in detail
- Three jobs in my old adapter, now separate layers: clean each source's quirks (staging), combine cleaned sources into a business concept (intermediate), shape for one consumer (gold).
- Staging: one model per source table. Rename to one convention, cast types (for example Unix timestamp to timestamp), fix technical problems like repeated rows. No joins, no business logic. A changed source column is fixed in one place.
- Intermediate: joins and business logic across cleaned sources (for example one row per customer with subscription and plan joined in). State the grain in one sentence. Not for dashboards.
- Gold: shaped for one consumer and holds the agreed metric definitions (`dim_customers`, monthly MRR). What dashboards and analysts read.
- Debugging walks backwards: gold logic, intermediate join, staging cleaning, or bad data already in raw.

## Incremental load and the cursor
- Like my HubSpot sync: store when I last synced, ask for rows modified since. The marker is the cursor (high-water mark), here `updated_at`.
- Cursor can be read from the target: `max(updated_at)` in the raw table. Empty or missing raw table means never loaded, so do a full load.
- Pull `WHERE updated_at >= cursor`. Use `>=` not `>`: rows can share the cursor timestamp or commit late in the source. Re-reading the boundary is harmless because the batch replaces rows by `id`.
- Changed rows come back with the same `id` and a newer `updated_at`. Pattern: load the batch into a temporary table, delete matching `id` values from raw, insert the batch, one transaction. Result: one row per `id`, and re-running a window changes nothing (idempotent).
- Limit: a cursor cannot see hard-deleted source rows. Fix with soft deletes or periodic full reloads.
- Redshift: no `INSERT ... ON CONFLICT`. `MERGE` exists now, but delete plus insert in one transaction is the classic pattern. Deleted rows stay on disk until `VACUUM DELETE` (automatic vacuum does it in the background). PostgreSQL uses autovacuum.

## Lookback window
- Problem: a row can be written with an older `updated_at` than my cursor (a transaction that began earlier and committed later). A plain cursor has already moved past it and never sees it.
- Fix: on every run re-read some time before the cursor (`--lookback-minutes`, default 60). Safe because the batch replaces rows by `id`, so the overlap changes nothing (idempotent).
- Trade-off: a bigger window catches later commits but re-reads more rows each run.
- A lookback does not help when a source changes a row without moving `updated_at`. That needs reconciliation (compare counts or checksums between source and raw) or a periodic full refresh.

## The incremental load on real Redshift
- Same logic as my loader (cursor, batch, replace by `id`, one transaction). Different plumbing.
- Getting data in: extract changed rows to a file (Parquet or compressed CSV), upload to S3, run Redshift `COPY` from S3 with an IAM role. Loads in parallel across slices, so split into several files. Airbyte's Redshift destination stages through S3 the same way.
- Incremental step: `COPY` the batch into a temporary table, then in one transaction `MERGE` (added in 2023) or `DELETE` matching `id` plus `INSERT`. Commit.
- No enforced primary or unique keys, so a failed delete step silently leaves duplicates. dbt `unique` tests catch it.
- `TRUNCATE` commits immediately and cannot be rolled back. For a safe full refresh, load a new table and rename it into place, or use `DELETE`.
- `TEXT` becomes `VARCHAR(256)`. Choose string lengths on purpose.
- No binary `COPY`. Formats are CSV, JSON, Parquet, Avro and similar.
- Deleted rows stay on disk until vacuum. Automatic vacuum and automatic analyze run in the background.
- What my build simplifies: it streams between two PostgreSQL databases with binary `COPY` and builds raw tables from `information_schema`.

## What Airbyte does for you (compared with my hand-written loader)
- Ready-made, maintained connectors (Chargebee, HubSpot, Pipedrive, Intercom, Amplitude, PostgreSQL): authentication, pagination, rate limits handled.
- Schema discovery (like my `information_schema` step), its own saved state (my cursor), sync modes per table: full refresh overwrite or append, incremental append, incremental append plus deduplicated (my delete-then-insert by `id`).
- Redshift destination stages files in S3 and runs `COPY`. Adds `_airbyte_extracted_at` and similar metadata columns (my `_loaded_at`).
- It removes plumbing, not problems: cursor syncs still miss rows that change without a new `updated_at` (PostgreSQL has a change-data-capture mode), it does no cleaning or metrics (that is dbt), and it is another system to run and monitor.
- Rule: Airbyte when a maintained connector covers the source and the data needed. Custom Python when there is no connector, it misses an endpoint or field, or the logic is unusual.

## dbt sources, freshness and staging models
- A source declares "this table exists and someone else loads it" in a `sources` YAML file. Models then read it with `{{ source('name', 'table') }}` instead of a hard-coded table name. It gives lineage and lets dbt check freshness.
- Source freshness: tell dbt which column holds the load time (`_loaded_at`) and thresholds (`warn_after`, `error_after`). `dbt source freshness` fails if the newest row is too old. A health check on the loader.
- Staging model naming convention: `stg_<source>__<table>` (double underscore), one model per source table, in a staging folder. No joins, no business logic.
- Layers build into their own schemas (`staging`, `intermediate`, `gold`). In this project a macro, `generate_schema_name`, makes dbt use the schema name exactly.
- Redshift: a view depends on the tables it reads and blocks dropping them. dbt-redshift can create late-binding views (`bind: false`) to avoid that.

## View compared with table (materialization)
- A table stores rows on disk. A view stores only a query: selecting from it re-runs the saved `select` against the real table each time. Like a getter method compared with a stored field.
- A view is always current and costs no storage, but its query re-runs on every read. A table pays the cost once when built, then reads are fast.
- In dbt this choice is the materialization. Here: views for staging and intermediate, tables for gold (set in `dbt_project.yml`).

## Freshness in plain words
- Without a check, a stopped loader changes nothing visibly: raw just stops getting new rows and dashboards quietly show old numbers.
- `dbt source freshness` looks at the newest `_loaded_at` in a raw table and compares it with `warn_after` and `error_after`. It checks how long ago the loader last wrote, not whether the data is correct.

## Freshness on a load log, and how Airbyte handles it
- Freshness on the data column (`_loaded_at`) false-alarms on quiet tables. Fix: the loader writes one row per table per run into `raw._load_log` in the same transaction as the data. dbt reads it as a source with `loaded_at_field: finished_at` and a `filter` so each check covers one table. Limits then follow the loader schedule, not how often the data changes.
- `filter` is SQL text added as a `where` clause to dbt's freshness query. Placed under `freshness:`.
- Airbyte equivalent: it records every sync as a job (start, end, success or failure, records moved), visible in its interface and API, with failure notifications (Slack, email). Records carry `_airbyte_extracted_at` (same quiet-table trap as `_loaded_at`). The Dagster Airbyte integration runs syncs as assets and tracks whether they worked.
- Rule: run history answers "did the sync run?", per-table limits answer "is silence suspicious?". Notification options differ between Airbyte Cloud and self-hosted, so check the real version.

## How Airbyte and dbt connect
- dbt does not read Airbyte's job history. They are separate systems and neither knows the other.
- Three ways: (1) dbt freshness on `_airbyte_extracted_at` in the raw table, a safety net with the quiet-table trap. (2) A small job copies Airbyte's sync results (from its API) into a warehouse table that dbt reads as a source, like my `_load_log`. (3) The usual answer: Dagster triggers the Airbyte sync, waits, and runs dbt only if the sync succeeded. Dagster raises the alert on failure or lateness.
- dbt freshness stays as a second line of defence for the case where a sync succeeds but pulls nothing. Dagster setup is Session 10.

## dbt tests (generic tests)
- A test is a query that returns the rows that break a rule. No rows returned means pass. Any row means fail, and dbt reports how many.
- You name the rule in YAML under the model's column (key `data_tests`); dbt writes the query. Run with `dbt test`.
- `unique`: no value appears twice. `not_null`: no empty values. `relationships`: every value exists in another model's column (`to: ref(...)`, `field: ...`). `accepted_values`: only the listed values.
- Model YAML also holds `description:` for the model and each column, which feeds `dbt docs generate`.
- Profiling by hand finds a problem once. A test finds it every run.

## Two kinds of duplicates, and what staging does about messy sources
- Technical duplicate: the same row with the same `id` arrived twice (loader or sync overlap). Staging fixes it: keep the latest copy of each `id`. No business judgement.
- Business duplicate: two different ids for the same real-world entity (found: 4 workspaces with two Chargebee customers, one empty copy). Staging does not delete silently: choosing the survivor is a business decision, the best rule needs a join to subscriptions (not allowed in staging), and deleting hides the problem from the source owner.
- What to do instead: staging keeps all rows. A `unique` test makes it visible (choose `warn` or `error`). The intermediate layer applies the agreed rule. Tell the source owner so it is fixed at the source.
- Nulls where a link should exist (found: 9 customers without `workspace_id`): staging does not invent values. It keeps the null, a `not_null` test with `warn` reports the count, and downstream models decide (left join keeps them for revenue, active-workspace metric ignores them).
- Staging is a faithful, cleaned copy of the source that makes problems visible.
