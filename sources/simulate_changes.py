"""Makes live changes in app_db, the way a running business would, so pipelines have something to catch.

    .venv/bin/python sources/simulate_changes.py plan-changes --count 5     upgrades, with events
    .venv/bin/python sources/simulate_changes.py double-change              two plan changes between two loads
    .venv/bin/python sources/simulate_changes.py late-messages --count 40   messages sent days ago, arriving now
    .venv/bin/python sources/simulate_changes.py quiet-update               a change that does not move updated_at
    .venv/bin/python sources/simulate_changes.py late-commit --minutes 30   a row stamped just before the loader cursor
    .venv/bin/python sources/simulate_changes.py rename-column              a breaking schema change in the product database
    .venv/bin/python sources/simulate_changes.py undo-rename-column         put the column name back
"""

import argparse
import os
import random

import psycopg

DSN = os.environ.get("APP_DB_DSN", "postgresql://goldmine:goldmine@localhost:5433/app_db")
UPGRADE_FROM = "plan_id < 4 and status = 'active'"


def change_plan(cur, subscription_id, new_plan_id):
    """Change a plan the way Chargebee does: overwrite the row and append an event."""
    price = cur.execute("select monthly_price_cents from chargebee.plan where id = %s", (new_plan_id,)).fetchone()[0]
    cur.execute(
        "update chargebee.subscription set plan_id = %s, plan_amount_cents = %s, updated_at = clock_timestamp() "
        "where id = %s returning quantity, status",
        (new_plan_id, price, subscription_id),
    )
    quantity, status = cur.fetchone()
    cur.execute(
        "insert into chargebee.subscription_event (id, subscription_id, event_type, occurred_at, plan_id, "
        "plan_amount_cents, quantity, status, created_at, updated_at) "
        "select coalesce(max(id), 0) + 1, %s, 'subscription_changed', clock_timestamp(), %s, %s, %s, %s, "
        "clock_timestamp(), clock_timestamp() from chargebee.subscription_event",
        (subscription_id, new_plan_id, price, quantity, status),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=[
        "plan-changes", "double-change", "late-messages", "quiet-update", "late-commit",
        "rename-column", "undo-rename-column",
    ])
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    with psycopg.connect(DSN) as conn, conn.cursor() as cur:
        if args.action == "plan-changes":
            rows = cur.execute(f"select id, plan_id from chargebee.subscription where {UPGRADE_FROM} order by id").fetchall()
            for subscription_id, plan_id in rng.sample(rows, min(args.count, len(rows))):
                change_plan(cur, subscription_id, plan_id + 1)
                print(f"subscription {subscription_id}: plan {plan_id} -> {plan_id + 1}")

        elif args.action == "double-change":
            rows = cur.execute(f"select id, plan_id from chargebee.subscription where {UPGRADE_FROM} order by id").fetchall()
            subscription_id, plan_id = rng.choice(rows)
            change_plan(cur, subscription_id, plan_id + 1)
            change_plan(cur, subscription_id, plan_id)
            print(f"subscription {subscription_id}: plan {plan_id} -> {plan_id + 1} -> {plan_id} (net change: none)")

        elif args.action == "late-messages":
            workspaces = [r[0] for r in cur.execute(
                "select distinct workspace_id from product.messages where sent_at > now() - interval '10 days' "
                "and workspace_id < 9000").fetchall()]
            next_id = cur.execute("select max(id) + 1 from product.messages").fetchone()[0]
            for offset in range(args.count):
                days_late = rng.randint(2, 6)
                cur.execute(
                    "insert into product.messages (id, workspace_id, user_id, channel, direction, sent_at, created_at, updated_at) "
                    "values (%s, %s, null, 'whatsapp', 'inbound', now() - make_interval(days => %s), clock_timestamp(), clock_timestamp())",
                    (next_id + offset, rng.choice(workspaces), days_late),
                )
            print(f"inserted {args.count} messages that were sent days ago and arrive now")

        elif args.action == "quiet-update":
            row = cur.execute(
                "select id, quantity, updated_at from chargebee.subscription "
                "where status = 'active' and updated_at < now() - interval '30 days' order by id limit 1"
            ).fetchone()
            cur.execute("update chargebee.subscription set quantity = quantity + 5 where id = %s", (row[0],))
            print(f"subscription {row[0]}: quantity {row[1]} -> {row[1] + 5}, updated_at left at {row[2]}")

        elif args.action == "late-commit":
            cursor_time = cur.execute("select max(updated_at) from product.workspaces").fetchone()[0]
            workspace_id = cur.execute("select max(id) + 1 from product.workspaces where id < 9000").fetchone()[0]
            cur.execute(
                "insert into product.workspaces (id, name, created_at, updated_at) "
                "values (%s, 'Late Commit Workspace', %s - make_interval(mins => %s), %s - make_interval(mins => %s))",
                (workspace_id, cursor_time, args.minutes, cursor_time, args.minutes),
            )
            print(f"workspace {workspace_id} inserted with updated_at {args.minutes} minutes before the newest row")

        elif args.action == "rename-column":
            cur.execute("alter table product.users rename column email to email_address")
            print("product.users.email renamed to email_address")

        elif args.action == "undo-rename-column":
            cur.execute("alter table product.users rename column email_address to email")
            print("product.users.email_address renamed back to email")


if __name__ == "__main__":
    main()
