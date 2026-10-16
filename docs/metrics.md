# Metric definitions

One definition each, modelled once in dbt, used by every dashboard. If a number disagrees with another tool, start here.

## Monthly recurring revenue (MRR)

MRR of a subscription = `plan_amount_cents * quantity` (price per seat times seats), counted **only while the status is `active` or `non_renewing`**.

| Status | Counts as revenue? | Why |
|---|---|---|
| `active` | yes | paying |
| `non_renewing` | yes | cancellation is scheduled but the paid period has not ended |
| `paused` | no | no billing and no access, but not churn |
| `in_trial`, `future` | no | not paying yet |
| `cancelled` | no | ended |

A subscription keeps the price it signed at. When the list price changes, existing customers do not change, so MRR is never computed by joining to today's plan price.

MRR of a customer in a month is the sum over their subscriptions, **measured at the end of the month** (the current month is measured up to now). Monthly state is rebuilt from the Chargebee events log, taking the last event before the end of each month.

Test accounts are excluded.

## MRR movements

Each customer-month is classified by comparing MRR with the previous month:

| Movement | Meaning |
|---|---|
| `new` | first month ever with revenue |
| `expansion` | more revenue than last month (upgrade or more seats) |
| `contraction` | less revenue, still a customer |
| `churned` | revenue fell to zero because the subscription was cancelled |
| `paused` | revenue fell to zero because the subscription was paused. **Not churn.** |
| `resumed` | revenue returned after a pause |
| `reactivated` | revenue returned after a cancellation |
| `unchanged` | same revenue |

The bridge always balances, and a test enforces it:

`closing = opening + new + expansion - contraction - churned + reactivated - paused + resumed`

## Churn and retention

| Metric | Formula |
|---|---|
| Logo churn rate | customers lost in the month / customers paying at the start of the month |
| Gross revenue churn rate | (churned MRR + contraction MRR) / opening MRR |
| Net revenue retention (NRR) | (opening + expansion - contraction - churned - paused) / opening MRR. Revenue at month end from the customers who were paying at month start. New, reactivated and resumed customers are excluded. |
| Gross revenue retention (GRR) | the same without expansion. Cannot exceed 100 percent. |

Customers who pause count against retention in the month they pause, because their revenue left, but they are not counted as lost logos.

## Active workspace

A workspace is **active in a month** if it sent at least `active_workspace_min_outbound_messages` outbound messages in that calendar month (default 10, a variable in `dbt_project.yml`). Inbound messages do not count, because a customer writing in does not mean the workspace uses the product. Internal test workspaces are excluded. The current month is month to date. `dim_workspaces.is_active_last_28_days` applies the same threshold to the last 28 days.

A message is only counted if it was not sent after it arrived. Rows that break this come from a server with a wrong clock.

## Customer resolution

Chargebee can hold two customer records for one workspace. The kept record is the one with subscriptions, then the oldest. Customers with no workspace are each kept. `dim_customers.duplicate_records_discarded` shows how many were dropped.

## Known limits

- One currency (euro). Multi-currency and annual plans are not modelled; everything is a monthly price.
- Discounts and coupons are not modelled. Prices are per-seat amounts as stored on the subscription.
- A customer with several subscriptions is classified on the sum of their revenue. The generated data has one subscription per customer.
- Credit notes are loaded and tested but do not change MRR. They are money returned, not a change to the recurring price.
