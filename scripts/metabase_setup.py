"""Sets up Metabase through its API: admin user, the warehouse connection and one SaaS metrics dashboard.

Safe to run again: it reuses what exists. Local development only, the default password is not a secret.

    .venv/bin/python scripts/metabase_setup.py        then open http://localhost:3030
"""

import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("METABASE_URL", "http://localhost:3030")
EMAIL = os.environ.get("MB_ADMIN_EMAIL", "admin@example.com")
PASSWORD = os.environ.get("MB_ADMIN_PASSWORD", "goldmine-local-1")

# Inside the compose network the warehouse is reachable by its service name.
WAREHOUSE = {"host": "postgres", "port": 5432, "dbname": "warehouse", "user": "goldmine", "password": "goldmine", "ssl": False}

CARDS = [
    # (name, display, sql, grid position: row, col, width, height)
    ("Current MRR (EUR)", "scalar",
     "select closing_mrr_cents / 100.0 as mrr from gold.fct_saas_metrics_monthly order by month_start desc limit 1",
     0, 0, 6, 3),
    ("Active customers", "scalar",
     "select closing_customers from gold.fct_saas_metrics_monthly order by month_start desc limit 1",
     0, 6, 6, 3),
    ("Net revenue retention (latest full month)", "scalar",
     "select round(net_revenue_retention, 3) from gold.fct_saas_metrics_monthly "
     "where month_start < date_trunc('month', current_date) order by month_start desc limit 1",
     0, 12, 6, 3),
    ("MRR by month (EUR)", "line",
     "select month_start, closing_mrr_cents / 100.0 as mrr from gold.fct_saas_metrics_monthly order by 1",
     3, 0, 12, 6),
    ("MRR movements by month (EUR)", "bar",
     "select month_start, new_mrr_cents / 100.0 as new, expansion_mrr_cents / 100.0 as expansion, "
     "reactivated_mrr_cents / 100.0 as reactivated, resumed_mrr_cents / 100.0 as resumed, "
     "-contraction_mrr_cents / 100.0 as contraction, -churned_mrr_cents / 100.0 as churned, "
     "-paused_mrr_cents / 100.0 as paused from gold.fct_saas_metrics_monthly order by 1",
     3, 12, 12, 6),
    ("Logo churn rate", "line",
     "select month_start, logo_churn_rate from gold.fct_saas_metrics_monthly where opening_customers > 0 order by 1",
     9, 0, 12, 6),
    ("Net and gross revenue retention", "line",
     "select month_start, net_revenue_retention, gross_revenue_retention from gold.fct_saas_metrics_monthly "
     "where opening_mrr_cents > 0 order by 1",
     9, 12, 12, 6),
    ("Active workspaces by month", "bar",
     "select month_start, active_workspaces from gold.fct_active_workspaces_monthly order by 1",
     15, 0, 12, 6),
    ("Paying customers by plan", "bar",
     "select current_plan, count(*) as customers from gold.dim_customers "
     "where current_status in ('active', 'non_renewing') and not is_test_account group by 1 order by 2 desc",
     15, 12, 12, 6),
]


class Client:
    def __init__(self):
        self.session = None

    def call(self, method, path, body=None):
        headers = {"Content-Type": "application/json"}
        if self.session:
            headers["X-Metabase-Session"] = self.session
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                text = response.read().decode()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as error:
            raise SystemExit(f"{method} {path} failed with {error.code}: {error.read().decode()[:500]}")


def wait_until_ready(client):
    for _ in range(60):
        try:
            if client.call("GET", "/api/health").get("status") == "ok":
                return
        except (urllib.error.URLError, SystemExit, ConnectionError):
            pass
        time.sleep(3)
    raise SystemExit("Metabase did not become ready")


def main():
    client = Client()
    wait_until_ready(client)
    token = client.call("GET", "/api/session/properties").get("setup-token")
    if token:
        print("first run: creating the admin user and connecting the warehouse")
        result = client.call("POST", "/api/setup", {
            "token": token,
            "user": {"first_name": "Goldmine", "last_name": "Admin", "email": EMAIL, "password": PASSWORD, "site_name": "Goldmine"},
            "database": {"engine": "postgres", "name": "Warehouse", "details": WAREHOUSE, "is_full_sync": True},
            "prefs": {"site_name": "Goldmine", "allow_tracking": False},
        })
        client.session = result["id"]
    else:
        client.session = client.call("POST", "/api/session", {"username": EMAIL, "password": PASSWORD})["id"]

    databases = client.call("GET", "/api/database")
    databases = databases["data"] if isinstance(databases, dict) else databases
    existing = [db for db in databases if db["name"] == "Warehouse"]
    if existing:
        database_id = existing[0]["id"]
    else:
        print("connecting the warehouse")
        database_id = client.call("POST", "/api/database", {
            "engine": "postgres", "name": "Warehouse", "details": WAREHOUSE, "is_full_sync": True, "auto_run_queries": True,
        })["id"]
    client.call("POST", f"/api/database/{database_id}/sync_schema")
    time.sleep(8)  # let the first metadata sync finish so the cards can run

    dashboards = client.call("GET", "/api/dashboard")
    if any(d["name"] == "SaaS metrics" for d in dashboards):
        print("dashboard already exists, nothing to do")
        return

    dashboard = client.call("POST", "/api/dashboard", {"name": "SaaS metrics", "description": "MRR, churn and active workspaces, from the gold tables."})
    dashcards = []
    for index, (name, display, sql, row, col, width, height) in enumerate(CARDS):
        card = client.call("POST", "/api/card", {
            "name": name,
            "display": display,
            "dataset_query": {"type": "native", "database": database_id, "native": {"query": sql}},
            "visualization_settings": {"stackable.stack_type": "stacked"} if name.startswith("MRR movements") else {},
        })
        dashcards.append({
            "id": -(index + 1), "card_id": card["id"], "row": row, "col": col,
            "size_x": width, "size_y": height, "parameter_mappings": [], "visualization_settings": {},
        })
    client.call("PUT", f"/api/dashboard/{dashboard['id']}", {"dashcards": dashcards})
    print(f"dashboard created: {BASE}/dashboard/{dashboard['id']}  (login {EMAIL} / {PASSWORD})")


if __name__ == "__main__":
    main()
