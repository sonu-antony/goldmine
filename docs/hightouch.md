# Reverse ETL with Hightouch (design)

**Not run.** Hightouch is a hosted service and needs an account, a warehouse connection and a HubSpot connection. This page is the design of the sync, and the table it reads is built, tested and running in this repository.

## The problem

Sales works in HubSpot. They do not see what a customer pays or whether the workspace is still using the product, because that lives in the warehouse. Reverse ETL copies modelled data back into the tool where people work.

## The model

`gold.hubspot_company_health` (dbt model `hubspot_company_health`): one row per HubSpot company linked to a paying customer.

| Column | HubSpot company property | Type |
|---|---|---|
| `hubspot_company_id` | the record to update (primary key of the sync) | |
| `goldmine_plan` | `goldmine_plan` | single-line text |
| `goldmine_mrr_eur` | `goldmine_mrr_eur` | number |
| `goldmine_subscription_status` | `goldmine_subscription_status` | dropdown |
| `goldmine_customer_since` | `goldmine_customer_since` | date |
| `goldmine_active_last_28_days` | `goldmine_active_last_28_days` | boolean |
| `goldmine_messages_last_28_days` | `goldmine_messages_last_28_days` | number |

The custom properties must exist in HubSpot first. Prefixing them keeps them clearly separate from properties people edit.

Hightouch's own model is `hightouch/company_health.sql`, a plain `select *` from the dbt table. The logic stays in dbt, where it is tested and in the lineage graph.

## The sync

| Setting | Value |
|---|---|
| Source | the warehouse, model above |
| Destination | HubSpot, object **Company** |
| Mode | **Update** only. Never create or delete companies from the warehouse. |
| Match on | HubSpot company id |
| Schedule | after the daily dbt run, triggered by Dagster, not on a separate clock |
| On failure | alert through the same Dagster failure sensor |

## Safeguards

- **Unique key.** The dbt test `unique` on `hubspot_company_id` fails the build before a duplicate could update one company twice.
- **Test accounts excluded.** They are filtered out in the model.
- **Only linked companies.** Companies with no `chargebee_customer_id`, or a broken one, are not in the table. How many are unlinked is visible in `dim_customers.hubspot_company_id`, so a drop in coverage can be monitored.
- **Do not overwrite with empties.** Configure the sync not to clear a property when the warehouse value is null.
- **Rate limits.** HubSpot's API limits writes. Hightouch sends only the rows that changed since the last sync, so a daily run touches few records.
- **Order.** The sync runs after dbt has finished and tests have passed, so wrong numbers are never pushed.

## What can go wrong

- The column was renamed in the model: the sync's mapping breaks. Treat a gold column rename as a breaking change and update Hightouch in the same change.
- A HubSpot property was deleted or its type changed: rows fail one by one. Hightouch reports rejected rows per sync.
- The warehouse is stale: the sync pushes old numbers. The sync is downstream of the freshness and reconciliation checks for this reason.
