-- How the raw layer and the incremental load look on Redshift. NOT executed in this repository.
-- Compare with ingestion/load.py, which does the same job on PostgreSQL. What changes:
--   * data arrives through S3 and COPY, never row by row
--   * every table chooses a distribution style and a sort key
--   * no enforced primary keys, so the replace-by-id step must be explicit
--   * VARCHAR needs a length, and TEXT would silently become VARCHAR(256)

-- A large table: distribute on the key it is joined and aggregated by, sort on the column that range filters use.
CREATE TABLE raw.product_messages (
    id           BIGINT,
    workspace_id BIGINT,
    user_id      BIGINT,
    channel      VARCHAR(32),
    direction    VARCHAR(16),
    sent_at      TIMESTAMPTZ,
    created_at   TIMESTAMPTZ,
    updated_at   TIMESTAMPTZ,
    _loaded_at   TIMESTAMPTZ DEFAULT GETDATE()
)
DISTKEY (workspace_id)   -- one workspace's messages live on one node, so per-workspace aggregates need no data movement
SORTKEY (created_at);    -- the incremental model filters on arrival time, so old blocks are skipped

-- A small table that is joined to everything: a full copy on every node, no data movement at all.
CREATE TABLE raw.chargebee_plan (
    id                  BIGINT,
    name                VARCHAR(100),
    monthly_price_cents INTEGER,
    created_at          TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ,
    _loaded_at          TIMESTAMPTZ DEFAULT GETDATE()
)
DISTSTYLE ALL;

-- The events log is always read per subscription, in time order.
CREATE TABLE raw.chargebee_subscription_event (
    id                BIGINT,
    subscription_id   BIGINT,
    event_type        VARCHAR(64),
    occurred_at       TIMESTAMPTZ,
    plan_id           BIGINT,
    plan_amount_cents INTEGER,
    quantity          INTEGER,
    status            VARCHAR(32),
    created_at        TIMESTAMPTZ,
    updated_at        TIMESTAMPTZ,
    _loaded_at        TIMESTAMPTZ DEFAULT GETDATE()
)
DISTKEY (subscription_id)
COMPOUND SORTKEY (subscription_id, occurred_at);

-- ---------------------------------------------------------------------------------------------
-- Incremental load of one table. The loader extracts the changed rows to Parquet, uploads them
-- to S3 and then runs this in a single transaction.
-- ---------------------------------------------------------------------------------------------
BEGIN;

CREATE TEMP TABLE batch (LIKE raw.chargebee_subscription);

COPY batch (id, customer_id, plan_id, status, plan_amount_cents, quantity, start_date, cancelled_date, created_at, updated_at)
FROM 's3://goldmine-warehouse-staging/chargebee_subscription/2026-10-16T05/'
IAM_ROLE 'arn:aws:iam::123456789012:role/goldmine-warehouse-copy'
FORMAT AS PARQUET;

-- Option A: MERGE (available in Redshift since 2023). Replaces by id, whether or not the row exists.
MERGE INTO raw.chargebee_subscription
USING batch ON raw.chargebee_subscription.id = batch.id
WHEN MATCHED THEN UPDATE SET
    customer_id = batch.customer_id, plan_id = batch.plan_id, status = batch.status,
    plan_amount_cents = batch.plan_amount_cents, quantity = batch.quantity, start_date = batch.start_date,
    cancelled_date = batch.cancelled_date, created_at = batch.created_at, updated_at = batch.updated_at,
    _loaded_at = GETDATE()
WHEN NOT MATCHED THEN INSERT (id, customer_id, plan_id, status, plan_amount_cents, quantity, start_date, cancelled_date, created_at, updated_at)
    VALUES (batch.id, batch.customer_id, batch.plan_id, batch.status, batch.plan_amount_cents, batch.quantity,
            batch.start_date, batch.cancelled_date, batch.created_at, batch.updated_at);

-- Option B: delete, then insert. The classic pattern, same result. Use one of the two, not both.
-- DELETE FROM raw.chargebee_subscription USING batch WHERE raw.chargebee_subscription.id = batch.id;
-- INSERT INTO raw.chargebee_subscription (id, customer_id, ...) SELECT id, customer_id, ... FROM batch;

-- The run log row goes in the same transaction, so a failed load leaves no log row behind.
INSERT INTO raw._load_log (table_name, mode, rows_pulled, rows_total)
SELECT 'chargebee_subscription', 'incremental', (SELECT COUNT(*) FROM batch), (SELECT COUNT(*) FROM raw.chargebee_subscription);

COMMIT;

-- A safe full refresh. TRUNCATE commits immediately in Redshift and cannot be rolled back, so load a new
-- table and swap it in instead:
--   BEGIN;
--   CREATE TABLE raw.chargebee_subscription_new (LIKE raw.chargebee_subscription);
--   COPY raw.chargebee_subscription_new ... ;
--   ALTER TABLE raw.chargebee_subscription RENAME TO chargebee_subscription_old;
--   ALTER TABLE raw.chargebee_subscription_new RENAME TO chargebee_subscription;
--   DROP TABLE raw.chargebee_subscription_old;
--   COMMIT;
