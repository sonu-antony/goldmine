"""Connection settings for the loader. Plumbing only."""

import os

SOURCE_DSN = os.environ.get("APP_DB_DSN", "postgresql://goldmine:goldmine@localhost:5433/app_db")
WAREHOUSE_DSN = os.environ.get("WAREHOUSE_DSN", "postgresql://goldmine:goldmine@localhost:5433/warehouse")

# source schema.table -> name of the raw table in warehouse.raw
TABLES = {
    "product.workspaces": "raw.product_workspaces",
    "product.users": "raw.product_users",
    "product.messages": "raw.product_messages",
    "chargebee.customer": "raw.chargebee_customer",
    "chargebee.plan": "raw.chargebee_plan",
    "chargebee.subscription": "raw.chargebee_subscription",
    "chargebee.invoice": "raw.chargebee_invoice",
    "chargebee.credit_note": "raw.chargebee_credit_note",
    "hubspot.companies": "raw.hubspot_companies",
    "hubspot.deals": "raw.hubspot_deals",
}


