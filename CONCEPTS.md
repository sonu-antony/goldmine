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
