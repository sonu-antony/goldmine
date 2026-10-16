-- Redshift access management. NOT executed in this repository: it needs a real Redshift cluster.
-- Run once as the admin user after `terraform apply`. The model is: people and tools get ROLES, never grants
-- of their own, and each role can do only what its job needs.
--
--   etl_loader        Airbyte and the Python loader. Writes raw, nothing else.
--   dbt_transformer   dbt. Reads raw, builds staging, intermediate, gold and snapshots.
--   analyst_readonly  Metabase and analysts. Reads gold only.

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS intermediate;
CREATE SCHEMA IF NOT EXISTS gold;
CREATE SCHEMA IF NOT EXISTS snapshots;

CREATE ROLE etl_loader;
CREATE ROLE dbt_transformer;
CREATE ROLE analyst_readonly;

-- raw: the loader owns it
GRANT USAGE, CREATE ON SCHEMA raw TO ROLE etl_loader;
GRANT ALL ON ALL TABLES IN SCHEMA raw TO ROLE etl_loader;

-- dbt reads raw, including tables the loader creates later
GRANT USAGE ON SCHEMA raw TO ROLE dbt_transformer;
GRANT SELECT ON ALL TABLES IN SCHEMA raw TO ROLE dbt_transformer;
ALTER DEFAULT PRIVILEGES IN SCHEMA raw GRANT SELECT ON TABLES TO ROLE dbt_transformer;

-- dbt builds everything downstream of raw
GRANT USAGE, CREATE ON SCHEMA staging, intermediate, gold, snapshots TO ROLE dbt_transformer;

-- analysts and Metabase see gold only. Raw and staging hold personal data (emails) that dashboards do not need.
GRANT USAGE ON SCHEMA gold TO ROLE analyst_readonly;
GRANT SELECT ON ALL TABLES IN SCHEMA gold TO ROLE analyst_readonly;

-- Machine users. PASSWORD DISABLE means they sign in with short-lived IAM credentials, so there is no
-- password to leak or rotate.
CREATE USER airbyte_loader PASSWORD DISABLE;
CREATE USER dbt_user PASSWORD DISABLE;
CREATE USER metabase_reader PASSWORD DISABLE;

-- tables that dbt creates in gold from now on are readable automatically
ALTER DEFAULT PRIVILEGES FOR USER dbt_user IN SCHEMA gold GRANT SELECT ON TABLES TO ROLE analyst_readonly;

GRANT ROLE etl_loader TO airbyte_loader;
GRANT ROLE dbt_transformer TO dbt_user;
GRANT ROLE analyst_readonly TO metabase_reader;

-- Cost guard rails: a dashboard query that runs away is stopped after 60 seconds, and the dashboard user
-- cannot hold more than a few connections.
ALTER USER metabase_reader SET statement_timeout TO 60000;
ALTER USER metabase_reader CONNECTION LIMIT 10;
