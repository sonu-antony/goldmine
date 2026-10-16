# Running this on Redshift

The project runs on PostgreSQL 16 locally, with the `warehouse` database standing in for Redshift. This page is the production design. **None of the Redshift or AWS material has been applied or run**: there is no AWS account behind this repository. The Terraform is validated and formatted (`tofu validate`, `tofu fmt`), the SQL in `redshift/` is reference material, and the dbt `dist` and `sort` settings are ignored on PostgreSQL.

## What changes from PostgreSQL

| Topic | PostgreSQL (here) | Redshift |
|---|---|---|
| Getting data in | `COPY` streamed between two connections | Extract to Parquet, upload to S3, `COPY ... FROM 's3://...' IAM_ROLE ... FORMAT AS PARQUET`. Row-by-row `INSERT` is very slow. |
| Replacing rows | `DELETE ... USING` then `INSERT`, `ON CONFLICT` available | No `ON CONFLICT`. `MERGE` exists (since 2023); delete plus insert in one transaction also works. |
| Keys | Primary and unique keys enforced | **Not enforced.** They are hints for the planner. Duplicates are possible, so uniqueness is tested on raw and deduplicated in staging. |
| `TRUNCATE` | Transactional | Commits immediately, cannot be rolled back. Swap a new table in with `RENAME` for a safe full refresh. |
| Strings | `TEXT` is unlimited | `TEXT` becomes `VARCHAR(256)`. Choose lengths on purpose. |
| Deleted rows | Autovacuum | Space is reclaimed by `VACUUM DELETE`; automatic vacuum and analyze run in the background. |
| Series of months | `generate_series` | Not usable with tables (leader node only). `int_months` uses a recursive query instead. |
| Window clause, `FILTER` | available | Not portable, so the models use inline window definitions and `sum(case when ...)`. |
| Views | Independent of table drops | A view binds to its tables. dbt-redshift can create late-binding views. |

The models already avoid the non-portable constructs. The cross-database dbt macros (`dbt.dateadd`, `dbt.date_trunc`) take care of the date functions.

## Distribution and sort keys

Redshift stores each table across nodes (distribution) and in sorted blocks (sort key). The right choice depends on how the table is joined and filtered. These settings are in the model `config()` and take effect with `dbt-redshift`.

| Table | Distribution | Sort key | Reason |
|---|---|---|---|
| `raw.product_messages` | `KEY (workspace_id)` | `created_at` | The biggest table. Per-workspace aggregates then need no data movement, and the incremental model filters on arrival time so old blocks are skipped. |
| `fct_workspace_activity_daily` | `KEY (workspace_id)` | `activity_date` | Same key as its source, so the daily aggregation and joins to workspaces stay on one node. Range filters on date. |
| `fct_mrr_monthly` | `KEY (customer_id)` | `month_start` | The movements model uses `lag` over customer, which needs each customer's rows together. |
| `fct_mrr_movements` | `KEY (customer_id)` | `month_start` | Same key as `fct_mrr_monthly`, so the join between them does not move data. |
| `fct_saas_metrics_monthly`, `fct_active_workspaces_monthly` | `ALL` | `month_start` | Tiny. A full copy on every node. |
| `dim_customers`, `dim_workspaces`, `hubspot_company_health` | `ALL` | their key | Small dimensions joined to large facts. With a copy on every node the join never moves data. |
| `raw.chargebee_subscription_event` | `KEY (subscription_id)` | `(subscription_id, occurred_at)` | Always read per subscription in time order. |

Rules of thumb behind them: distribute large tables on the column they are most often joined or grouped by, as long as it is spread evenly (check `skew_rows`); use `ALL` for small tables joined to big ones; use `AUTO` when unsure and let Redshift adapt; sort on the column that range filters and joins use, most selective first.

Check a table's design with `svv_table_info` (see `redshift/maintenance_and_monitoring.sql`): `skew_rows` far above 1 means a poor distribution key, a high `unsorted` percentage means the sort order has decayed.

## Cost

- **RA3 nodes** separate compute from managed storage. You pay for compute by the hour and for the storage you use, and can resize compute alone.
- **Pause** a development cluster outside working hours (`pause_outside_business_hours` in the Terraform). Do not pause production.
- **Concurrency scaling** is billed per second beyond free credits. A usage limit in the Terraform caps it each month.
- **Query guard rails:** `statement_timeout` for dashboard users stops runaway queries.
- **Spend most effort on the design of the big tables.** A good distribution and sort key reduces the data every query reads, which is the main cost lever.
- Serverless is the alternative: no cluster to size, billed on compute used. It suits spiky workloads. A steady daily pipeline plus dashboards often costs less on a provisioned RA3 cluster, so compare both on real usage.

## Access management

Roles, not individual grants, in `redshift/access_management.sql`:

| Role | Used by | Can |
|---|---|---|
| `etl_loader` | Airbyte, the loader | write `raw` |
| `dbt_transformer` | dbt | read `raw`, build `staging`, `intermediate`, `gold`, `snapshots` |
| `analyst_readonly` | Metabase, analysts | read `gold` only |

Machine users have `PASSWORD DISABLE` and sign in with temporary IAM credentials, so there are no passwords to leak. The cluster master password is managed by AWS in Secrets Manager (`manage_master_password`), so it never enters Terraform state. The cluster is encrypted, not publicly accessible, requires SSL, and only the networks in `allowed_cidr_blocks` can reach it.

## Infrastructure

`terraform/redshift/`: cluster, subnet group, security group, parameter group, the S3 staging bucket (encrypted, private, files expire after 14 days), the IAM role Redshift uses for `COPY`, a usage limit and optional pause and resume schedules.

```
cd terraform/redshift
cp terraform.tfvars.example terraform.tfvars   # fill in the VPC and networks
terraform init && terraform plan
```

## Running dbt against Redshift

```
pip install -r requirements-redshift.txt
export REDSHIFT_HOST=... REDSHIFT_USER=dbt_user REDSHIFT_PASSWORD=...
cd goldmine_dbt && dbt build --target redshift
```
