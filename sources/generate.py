"""Fills app_db with about 18 months of fake history.

Treat this file as a black box, like a real source system. Run it with:
    .venv/bin/python sources/generate.py            (reset and refill everything)
"""

import argparse
import os
import random
from datetime import date, datetime, time, timedelta, timezone

import psycopg
from faker import Faker

DSN = os.environ.get("APP_DB_DSN", "postgresql://goldmine:goldmine@localhost:5433/app_db")
NOW = datetime.now(timezone.utc).replace(microsecond=0)
TODAY = NOW.date()
START = TODAY - timedelta(days=548)
WORKSPACES = 300

PLANS = [(1, "Starter", 4900), (2, "Growth", 14900), (3, "Pro", 39900), (4, "Enterprise", 99900)]
PLAN_WEIGHTS = [55, 30, 12, 3]
LIST_PRICE = {plan_id: price for plan_id, _, price in PLANS}
GROWTH_OLD_PRICE = 12900
PRICE_RISE = date(2026, 3, 1)
MESSAGE_RATE = {1: 3, 2: 12, 3: 40, 4: 120}
CHANNELS = ["whatsapp", "instagram", "facebook", "telegram", "sms", "email"]
CHANNEL_WEIGHTS = [50, 20, 12, 6, 7, 5]
SEATS = {1: 2, 2: 4, 3: 8, 4: 20}

TABLES = [
    "product.messages", "product.users", "product.workspaces",
    "chargebee.credit_note", "chargebee.invoice", "chargebee.subscription", "chargebee.customer", "chargebee.plan",
    "hubspot.deals", "hubspot.companies",
]


def price_on(plan_id, day):
    if plan_id == 2 and day < PRICE_RISE:
        return GROWTH_OLD_PRICE
    return LIST_PRICE[plan_id]


def at(rng, day, lo=6, hi=22):
    return datetime.combine(
        day, time(rng.randint(lo, hi - 1), rng.randint(0, 59), rng.randint(0, 59)), tzinfo=timezone.utc
    )


def add_month(day):
    return date(day.year + day.month // 12, day.month % 12 + 1, min(day.day, 28))


def simulate(rng, start, plan, forced_double_change):
    price = price_on(plan, start)
    status, cancelled_on = "active", None
    updated = at(rng, start)
    invoices, credit_notes, periods = [], [], []
    period_start = start
    current, cycle = start, 0
    while True:
        if status == "active":
            invoices.append((at(rng, current, 0, 6), price, "invoice"))
        following = add_month(current)
        if following > TODAY:
            break
        event_day = current + timedelta(days=rng.randint(3, 26))
        if status == "active" and forced_double_change and cycle == 2 and plan < 4:
            first, second = current + timedelta(days=5), current + timedelta(days=18)
            new_price = price_on(plan + 1, first)
            invoices.append((at(rng, first), round((new_price - price) * 0.8), "proration"))
            credit_notes.append((at(rng, second), round((new_price - price) * 0.4)))
            price = price_on(plan, second)
            updated = at(rng, second)
        elif status == "active":
            roll = rng.random()
            if roll < 0.025:
                status, cancelled_on, updated = "cancelled", event_day, at(rng, event_day)
                periods.append((period_start, event_day))
            elif roll < 0.037:
                status, updated = "paused", at(rng, event_day)
                periods.append((period_start, event_day))
            elif roll < 0.077 and plan < 4:
                new_price = price_on(plan + 1, event_day)
                remaining = (following - event_day).days / 30
                invoices.append((at(rng, event_day), round((new_price - price) * remaining), "proration"))
                plan, price, updated = plan + 1, new_price, at(rng, event_day)
            elif roll < 0.097 and plan > 1:
                new_price = price_on(plan - 1, event_day)
                remaining = (following - event_day).days / 30
                credit_notes.append((at(rng, event_day), round((price - new_price) * remaining)))
                plan, price, updated = plan - 1, new_price, at(rng, event_day)
        elif status == "paused":
            if rng.random() < 0.35:
                status, updated = "active", at(rng, event_day)
                period_start = event_day
        elif rng.random() < 0.18:
            status, cancelled_on, updated = "active", None, at(rng, event_day)
            period_start = event_day
        current, cycle = following, cycle + 1
    if status == "active":
        periods.append((period_start, TODAY))
    elif status == "cancelled" and cancelled_on > TODAY - timedelta(days=20) and rng.random() < 0.5:
        status = "non_renewing"
        periods.append((cancelled_on, TODAY))
    return {
        "plan": plan, "price": price, "status": status, "cancelled_on": cancelled_on,
        "updated": min(updated, NOW), "invoices": invoices, "credit_notes": credit_notes,
        "periods": periods,
    }


def message_rows(rng, activity, users_by_workspace):
    message_id = 1
    for workspace_id, plan, periods, rate_override in activity:
        users = users_by_workspace[workspace_id]
        base_rate = rate_override or MESSAGE_RATE[plan]
        for first_day, last_day in periods:
            day = first_day
            while day <= last_day:
                rate = base_rate * (0.3 if day.weekday() >= 5 else 1)
                for _ in range(int(rng.expovariate(1 / rate))):
                    sent_at = at(rng, day)
                    if sent_at > NOW:
                        continue
                    inbound = rng.random() < 0.55
                    created = sent_at + timedelta(seconds=rng.randint(0, 5))
                    if rng.random() < 0.004:
                        created = sent_at + timedelta(days=rng.randint(1, 3), hours=rng.randint(0, 5))
                    created = min(created, NOW)
                    yield (
                        message_id, workspace_id, None if inbound else rng.choice(users),
                        rng.choices(CHANNELS, CHANNEL_WEIGHTS)[0],
                        "inbound" if inbound else "outbound", sent_at, created, created,
                    )
                    message_id += 1
                day += timedelta(days=1)


def copy_rows(cursor, table, columns, rows):
    with cursor.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        count = 0
        for row in rows:
            copy.write_row(row)
            count += 1
    print(f"{table:<26}{count:>9} rows")


def build(rng, fake):
    workspaces, users, customers, subscriptions, invoices, credit_notes = [], [], [], [], [], []
    activity, users_by_workspace = [], {}
    consultants = [fake.email() for _ in range(15)]
    forced = set(rng.sample(range(1, WORKSPACES + 1), 6))
    span = (TODAY - timedelta(days=14) - START).days

    for ws_id in range(1, WORKSPACES + 1):
        start = START + timedelta(days=int(span * rng.random() ** 1.3))
        created = at(rng, start)
        name = fake.company()
        plan = rng.choices([p[0] for p in PLANS], PLAN_WEIGHTS)[0]
        paid = rng.random() < 0.9
        workspaces.append((ws_id, name, created, min(created + timedelta(days=rng.randint(0, 120)), NOW)))

        members = 1 + min(int(rng.expovariate(1 / SEATS[plan])), 60)
        ids = []
        for n in range(members):
            user_id = ws_id * 100 + n
            email = fake.email()
            if rng.random() < 0.08:
                email = rng.choice([email.upper(), email + " ", " " + email])
            role = "owner" if n == 0 else ("admin" if rng.random() < 0.2 else "agent")
            joined = min(created + timedelta(days=rng.randint(0, 30)), NOW)
            users.append((user_id, ws_id, email, role, joined, joined))
            ids.append(user_id)
        if rng.random() < 0.1:
            user_id = ws_id * 100 + members
            users.append((user_id, ws_id, rng.choice(consultants), "agent", created, created))
            ids.append(user_id)
        users_by_workspace[ws_id] = ids

        if not paid:
            activity.append((ws_id, 1, [(start, min(start + timedelta(days=60), TODAY))], None))
            continue

        result = simulate(rng, start, plan, ws_id in forced)
        customer_id, quantity = 1000 + ws_id, max(1, int(rng.expovariate(1 / SEATS[plan])))
        customer_name = name + rng.choice(["", "", "", " GmbH", " Ltd"])
        customers.append(
            [customer_id, customer_name, ws_id, created, min(created + timedelta(days=rng.randint(0, 200)), NOW)]
        )
        subscriptions.append([
            5000 + ws_id, customer_id, result["plan"], result["status"], result["price"], quantity,
            start, result["cancelled_on"], created, result["updated"],
        ])
        for when, amount, kind in result["invoices"]:
            recent = when > NOW - timedelta(days=30)
            state = "payment_due" if recent and rng.random() < 0.15 else ("voided" if rng.random() < 0.01 else "paid")
            total = amount * quantity
            invoices.append([when, total, state, when, when + timedelta(days=rng.randint(0, 6)), 5000 + ws_id])
            if state == "paid" and kind == "invoice" and rng.random() < 0.012:
                credit_notes.append([5000 + ws_id, total // 2, "service_unsatisfactory", "refunded", when, when])
        for when, amount in result["credit_notes"]:
            status = "refunded" if rng.random() < 0.3 else "adjusted"
            credit_notes.append([5000 + ws_id, amount * quantity, "order_change", status, when, when])
        activity.append((ws_id, result["plan"], result["periods"], None))

    return workspaces, users, customers, subscriptions, invoices, credit_notes, activity, users_by_workspace


def add_mess(rng, fake, workspaces, users, customers, subscriptions, invoices, activity, users_by_workspace):
    # internal and test accounts
    for offset, test_name in enumerate(["Superchat Internal Test", "zz_loadtest_do_not_use"]):
        ws_id = 9001 + offset
        workspaces.append((ws_id, test_name, at(rng, START), NOW))
        users.append((ws_id * 100, ws_id, f"qa{offset}@superchat.example", "owner", at(rng, START), at(rng, START)))
        users_by_workspace[ws_id] = [ws_id * 100]
        rate = 600 if offset else 25
        activity.append((ws_id, 4, [(TODAY - timedelta(days=120), TODAY)], rate))
    customers.append([1999, "TEST ACCOUNT (do not use)", 9001, at(rng, START), NOW])
    subscriptions.append([5999, 1999, 4, "active", 0, 1, START, None, at(rng, START), NOW])

    # broken cross-system links, missing links, repeated customers
    for customer in rng.sample(customers[:-1], 2):
        customer[2] = 90000 + customer[0]
    for customer in rng.sample(customers[:-1], 9):
        customer[2] = None
    for customer in rng.sample(customers[:-1], 4):
        created = min(customer[3] + timedelta(days=rng.randint(1, 20)), NOW)
        customers.append([customer[0] + 1000, customer[1], customer[2], created, created])

    # subscriptions and invoices with inconsistent values
    cancelled = [s for s in subscriptions if s[3] == "cancelled"]
    for sub in rng.sample(cancelled, min(3, len(cancelled))):
        sub[7] = None
    for invoice in rng.sample(invoices, 3):
        invoice[4] = invoice[3] - timedelta(days=rng.randint(1, 3))
    for invoice in rng.sample(invoices, 2):
        invoice[1] = -abs(invoice[1])

    # hubspot
    companies, deals = [], []
    company_id = deal_id = 1
    linked = [c for c in customers if c[0] < 1999]
    for customer in linked:
        if rng.random() > 0.85:
            continue
        domain = fake.domain_name()
        domain = rng.choice([domain, domain, domain, "https://www." + domain, domain.upper()])
        created = customer[3] - timedelta(days=rng.randint(10, 60))
        link = None if rng.random() < 0.15 else customer[0]
        companies.append([company_id, customer[1], domain, link, created, min(created + timedelta(days=90), NOW)])
        amount = rng.choice([49, 149, 399]) * 1200
        close = customer[3].date()
        deals.append([deal_id, company_id, "closed_won", amount, close, created, created + timedelta(days=20)])
        company_id, deal_id = company_id + 1, deal_id + 1
    for _ in range(40):
        created = at(rng, START + timedelta(days=rng.randint(0, 520)))
        companies.append([company_id, fake.company(), fake.domain_name(), None, created, created])
        stage = rng.choice(["appointment_scheduled", "qualified_to_buy", "contract_sent", "closed_lost"])
        close = created.date() + timedelta(days=30) if stage == "closed_lost" else None
        deals.append([deal_id, company_id, stage, rng.choice([49, 149, 399]) * 1200, close, created, created])
        company_id, deal_id = company_id + 1, deal_id + 1
    for company in rng.sample(companies, 6):
        created = min(company[4] + timedelta(days=rng.randint(5, 40)), NOW)
        companies.append([company_id, company[1], company[2], None, created, created])
        company_id += 1
    for company in rng.sample([c for c in companies if c[3]], 3):
        company[3] = 777000 + company[0]
    for deal in rng.sample([d for d in deals if d[2] == "closed_won"], 4):
        deal[4] = None
    for deal in rng.sample([d for d in deals if d[4]], 3):
        deal[4] = deal[5].date() - timedelta(days=rng.randint(3, 15))
    return companies, deals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    rng, fake = random.Random(args.seed), Faker("de_DE")
    Faker.seed(args.seed)

    workspaces, users, customers, subscriptions, invoices, credit_notes, activity, users_by_workspace = build(
        rng, fake
    )
    companies, deals = add_mess(
        rng, fake, workspaces, users, customers, subscriptions, invoices, activity, users_by_workspace
    )
    invoice_rows = [(i + 1, inv[5], inv[1], inv[2], inv[3], inv[4]) for i, inv in enumerate(invoices)]
    credit_note_rows = [(i + 1, *note) for i, note in enumerate(credit_notes)]
    plan_rows = [(p, n, price, START, datetime.combine(PRICE_RISE, time(9), tzinfo=timezone.utc) if p == 2 else START)
                 for p, n, price in PLANS]

    with psycopg.connect(DSN) as conn, conn.cursor() as cursor:
        cursor.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
        ts = ("created_at", "updated_at")
        copy_rows(cursor, "product.workspaces", ("id", "name", *ts), workspaces)
        copy_rows(cursor, "product.users", ("id", "workspace_id", "email", "role", *ts), users)
        copy_rows(cursor, "chargebee.plan", ("id", "name", "monthly_price_cents", *ts), plan_rows)
        copy_rows(cursor, "chargebee.customer", ("id", "name", "workspace_id", *ts), customers)
        copy_rows(
            cursor, "chargebee.subscription",
            ("id", "customer_id", "plan_id", "status", "plan_amount_cents", "quantity",
             "start_date", "cancelled_date", *ts),
            subscriptions,
        )
        copy_rows(
            cursor, "chargebee.invoice",
            ("id", "subscription_id", "amount_cents", "status", *ts), invoice_rows,
        )
        copy_rows(
            cursor, "chargebee.credit_note",
            ("id", "subscription_id", "amount_cents", "reason", "status", *ts), credit_note_rows,
        )
        copy_rows(cursor, "hubspot.companies", ("id", "name", "domain", "chargebee_customer_id", *ts), companies)
        copy_rows(
            cursor, "hubspot.deals",
            ("id", "company_id", "stage", "amount_cents", "close_date", *ts), deals,
        )
        copy_rows(
            cursor, "product.messages",
            ("id", "workspace_id", "user_id", "channel", "direction", "sent_at", *ts),
            message_rows(rng, activity, users_by_workspace),
        )


if __name__ == "__main__":
    main()
