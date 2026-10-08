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
