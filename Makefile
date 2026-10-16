# Day-to-day commands. Run from the repository root. Assumes the virtual environment in .venv.
PY := .venv/bin/python
DBT := cd goldmine_dbt && ../.venv/bin/dbt

.PHONY: up down schema generate load reconcile build test freshness snapshot docs dagster pytest reset

up:            ## start PostgreSQL (and Metabase) in containers
	podman-compose up -d

down:          ## stop the containers (data is kept in a volume)
	podman-compose down

schema:        ## create the source tables in app_db
	@for f in product chargebee hubspot; do podman exec -i goldmine-postgres psql -U goldmine -d app_db -v ON_ERROR_STOP=1 < sources/$${f}_schema.sql; done

generate:      ## refill app_db with fresh fake history (truncates the source tables)
	$(PY) sources/generate.py

load:          ## source -> warehouse.raw (incremental after the first run)
	$(PY) -m ingestion.load

reconcile:     ## compare each source table with its raw copy
	$(PY) -m ingestion.reconcile

build:         ## dbt models, snapshot and tests
	$(DBT) build

test:          ## dbt tests only
	$(DBT) test

freshness:     ## dbt source freshness (reads raw._load_log)
	$(DBT) source freshness

docs:          ## generate and serve dbt documentation with the lineage graph
	$(DBT) docs generate && $(DBT) docs serve

dagster:       ## open the Dagster UI at http://localhost:3001 
	DAGSTER_HOME=$(PWD)/.dagster_home .venv/bin/dagster dev -m orchestration -p 3001

pytest:        ## Python tests for the orchestration code
	$(PY) -m pytest -q tests_python

reset: schema generate  ## start over: new source data, then run `make load build`
