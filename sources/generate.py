"""Fills app_db with about 18 months of fake history for a SaaS company.

app_db plays the source systems: a product database, Chargebee billing and HubSpot CRM.
The data is deliberately messy, like real sources. Treat this file as a black box and find
the mess with profiling, tests and reconciliation. Run it from the repository root:

    .venv/bin/python sources/generate.py            (truncates the source tables and refills them)
    .venv/bin/python sources/generate.py --workspaces 60 --message-scale 0.1     (small, for CI)
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

PLANS = [(1, "Starter", 4900), (2, "Growth", 14900), (3, "Pro", 39900), (4, "Enterprise", 99900)]
PLAN_WEIGHTS = [55, 30, 12, 3]
LIST_PRICE = {plan_id: price for plan_id, _, price in PLANS}
GROWTH_OLD_PRICE = 12900
PRICE_RISE = date(2026, 3, 1)
MESSAGE_RATE = {1: 3, 2: 12, 3: 40, 4: 120}
CHANNELS = ["whatsapp", "instagram", "facebook", "telegram", "sms", "email"]
CHANNEL_WEIGHTS = [50, 20, 12, 6, 7, 5]
SEATS = {1: 2, 2: 4, 3: 8, 4: 20}
TRIAL_DAYS = 14

TABLES = [
    "product.messages", "product.users", "product.workspaces",
    "chargebee.subscription_event", "chargebee.credit_note", "chargebee.invoice",
    "chargebee.subscription", "chargebee.customer", "chargebee.plan",
    "hubspot.deals", "hubspot.companies",
]


def price_on(plan_id, day):
    if plan_id == 2 and day < PRICE_RISE:
        return GROWTH_OLD_PRICE
    return LIST_PRICE[plan_id]


def at(rng, day, lo=6, hi=22):
    moment = datetime.combine(
        day, time(rng.randint(lo, hi - 1), rng.randint(0, 59), rng.randint(0, 59)), tzinfo=timezone.utc
    )
    return min(moment, NOW)


def add_month(day):
    return date(day.year + day.month // 12, day.month % 12 + 1, min(day.day, 28))


class Subscription:
    """Simulates one subscription over time. Records every change as an event, like Chargebee does."""

    def __init__(self, rng, start, plan, quantity, trial):
        self.rng, self.start = rng, start
        self.plan, self.quantity, self.price = plan, quantity, price_on(plan, start)
        self.status = "in_trial" if trial else "active"
        self.cancelled_on = None
        self.events, self.invoices, self.credit_notes, self.periods = [], [], [], []
        self.period_start = start
        self.updated = at(rng, start)
        self.record("subscription_created", start)

    def record(self, event_type, day):
        when = at(self.rng, day)
        self.updated = when
        self.events.append((when, event_type, self.plan, self.price, self.quantity, self.status))

    def bill(self, day, amount):
        self.invoices.append((at(self.rng, day), amount))

    def credit(self, day, amount, reason="order_change"):
        self.credit_notes.append((at(self.rng, day), amount, reason))

    def run(self, forced_double_change):
        rng = self.rng
        current = self.start
        if self.status == "in_trial":
            trial_end = self.start + timedelta(days=TRIAL_DAYS)
            if trial_end > TODAY:
                self.periods.append((self.start, TODAY))
                return self
            self.status = "active"
            self.record("subscription_activated", trial_end)
            current = trial_end
        cycle = 0
        while current <= TODAY:
            if self.status == "active":
                self.bill(current, self.price * self.quantity)
            following = add_month(current)
            event_day = current + timedelta(days=rng.randint(3, 26))
            if event_day <= TODAY:
                if self.status == "active":
                    if forced_double_change and cycle == 2 and self.plan < 4 and current + timedelta(days=18) <= TODAY:
                        self.double_change(current)
                    else:
                        self.random_change(event_day, following)
                elif self.status == "paused" and rng.random() < 0.35:
                    self.status = "active"
                    self.record("subscription_resumed", event_day)
                    self.period_start = event_day
                elif self.status == "cancelled" and rng.random() < 0.18:
                    self.status, self.cancelled_on = "active", None
                    self.record("subscription_reactivated", event_day)
                    self.period_start = event_day
            if self.status == "non_renewing":
                break
            current, cycle = following, cycle + 1
        if self.status in ("active", "non_renewing"):
            self.periods.append((self.period_start, TODAY))
        return self

    def double_change(self, current):
        """Upgrade and then downgrade back inside one month."""
        first, second = current + timedelta(days=5), current + timedelta(days=18)
        upgraded = price_on(self.plan + 1, first)
        self.bill(first, round((upgraded - self.price) * self.quantity * 0.8))
        self.plan += 1
        self.price = upgraded
        self.record("subscription_changed", first)
        back = price_on(self.plan - 1, second)
        self.credit(second, round((self.price - back) * self.quantity * 0.4))
        self.plan -= 1
        self.price = back
        self.record("subscription_changed", second)

    def random_change(self, event_day, following):
        rng = self.rng
        remaining = (following - event_day).days / 30
        roll = rng.random()
        if roll < 0.025:
            if following > TODAY and rng.random() < 0.5:
                self.status, self.cancelled_on = "non_renewing", following
                self.record("subscription_cancellation_scheduled", event_day)
            else:
                self.periods.append((self.period_start, event_day))
                self.status, self.cancelled_on = "cancelled", event_day
                self.record("subscription_cancelled", event_day)
        elif roll < 0.037:
            self.status = "paused"
            self.periods.append((self.period_start, event_day))
            self.record("subscription_paused", event_day)
        elif roll < 0.077 and self.plan < 4:
            upgraded = price_on(self.plan + 1, event_day)
            self.bill(event_day, round((upgraded - self.price) * self.quantity * remaining))
            self.plan, self.price = self.plan + 1, upgraded
            self.record("subscription_changed", event_day)
        elif roll < 0.097 and self.plan > 1:
            lower = price_on(self.plan - 1, event_day)
            self.credit(event_day, round((self.price - lower) * self.quantity * remaining))
            self.plan, self.price = self.plan - 1, lower
            self.record("subscription_changed", event_day)
        elif roll < 0.117:
            added = rng.randint(1, 3)
            self.bill(event_day, round(self.price * added * remaining))
            self.quantity += added
            self.record("subscription_changed", event_day)
        elif roll < 0.127 and self.quantity > 1:
            self.credit(event_day, round(self.price * remaining))
            self.quantity -= 1
            self.record("subscription_changed", event_day)


def message_rows(rng, activity, users_by_workspace, scale):
    message_id = 1
    for workspace_id, plan, periods, rate_override in activity:
        users = users_by_workspace[workspace_id]
        base_rate = (rate_override or MESSAGE_RATE[plan]) * scale
        for first_day, last_day in periods:
            day = first_day
            while day <= last_day:
                rate = base_rate * (0.3 if day.weekday() >= 5 else 1)
                for _ in range(int(rng.expovariate(1 / rate))):
                    sent_at = at(rng, day)
                    if sent_at >= NOW:
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
    # a few messages stamped in the future by a server with a wrong clock
    for workspace_id in rng.sample(sorted(users_by_workspace), min(25, len(users_by_workspace))):
        sent_at = NOW + timedelta(days=1, minutes=rng.randint(0, 600))
        yield (message_id, workspace_id, None, "whatsapp", "inbound", sent_at, NOW, NOW)
        message_id += 1


def copy_rows(cursor, table, columns, rows):
    with cursor.copy(f"COPY {table} ({', '.join(columns)}) FROM STDIN") as copy:
        count = 0
        for row in rows:
            copy.write_row(row)
            count += 1
    print(f"{table:<30}{count:>9} rows")


def build(rng, fake, workspace_count):
    workspaces, users, customers, subscriptions = [], [], [], []
    invoices, credit_notes, events = [], [], []
    activity, users_by_workspace = [], {}
    consultants = [fake.email() for _ in range(15)]
    forced = set(rng.sample(range(1, workspace_count + 1), min(6, workspace_count)))
    span = (TODAY - timedelta(days=3) - START).days

    for ws_id in range(1, workspace_count + 1):
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

        quantity = max(1, int(rng.expovariate(1 / SEATS[plan])))
        trial = rng.random() < 0.25
        sub = Subscription(rng, start, plan, quantity, trial).run(ws_id in forced)
        customer_id, subscription_id = 1000 + ws_id, 5000 + ws_id
        customer_name = name + rng.choice(["", "", "", " GmbH", " Ltd"])
        customers.append(
            [customer_id, customer_name, ws_id, created, min(created + timedelta(days=rng.randint(0, 200)), NOW)]
        )
        subscriptions.append([
            subscription_id, customer_id, sub.plan, sub.status, sub.price, sub.quantity,
            start, sub.cancelled_on, created, min(sub.updated, NOW),
        ])
        for when, amount in sub.invoices:
            recent = when > NOW - timedelta(days=30)
            state = "payment_due" if recent and rng.random() < 0.15 else ("voided" if rng.random() < 0.01 else "paid")
            invoices.append([subscription_id, amount, state, when, when + timedelta(days=rng.randint(0, 6))])
            if state == "paid" and rng.random() < 0.012:
                credit_notes.append([subscription_id, amount // 2, "service_unsatisfactory", "refunded", when, when])
        for when, amount, reason in sub.credit_notes:
            status = "refunded" if rng.random() < 0.3 else "adjusted"
            credit_notes.append([subscription_id, amount, reason, status, when, when])
        for when, event_type, event_plan, price, event_quantity, status in sub.events:
            events.append([subscription_id, event_type, when, event_plan, price, event_quantity, status])
        activity.append((ws_id, sub.plan, sub.periods, None))

    return {
        "workspaces": workspaces, "users": users, "customers": customers, "subscriptions": subscriptions,
        "invoices": invoices, "credit_notes": credit_notes, "events": events,
        "activity": activity, "users_by_workspace": users_by_workspace,
    }


def add_mess(rng, fake, data):
    workspaces, users, customers = data["workspaces"], data["users"], data["customers"]
    subscriptions, invoices = data["subscriptions"], data["invoices"]
    activity, users_by_workspace = data["activity"], data["users_by_workspace"]

    # internal and test accounts
    for offset, test_name in enumerate(["Acme QA Sandbox", "zz_loadtest_do_not_use"]):
        ws_id = 9001 + offset
        workspaces.append((ws_id, test_name, at(rng, START), NOW))
        users.append((ws_id * 100, ws_id, f"qa{offset}@example.com", "owner", at(rng, START), at(rng, START)))
        users_by_workspace[ws_id] = [ws_id * 100]
        activity.append((ws_id, 4, [(TODAY - timedelta(days=120), TODAY)], 600 if offset else 25))
    customers.append([1999, "TEST ACCOUNT (do not use)", 9001, at(rng, START), NOW])
    subscriptions.append([5999, 1999, 4, "active", 0, 1, START, None, at(rng, START), NOW])
    data["events"].append([5999, "subscription_created", at(rng, START), 4, 0, 1, "active"])

    # broken cross-system links, missing links, repeated customers
    real_customers = customers[:-1]
    for customer in rng.sample(real_customers, min(2, len(real_customers))):
        customer[2] = 90000 + customer[0]
    for customer in rng.sample(real_customers, min(9, len(real_customers))):
        customer[2] = None
    for customer in rng.sample(real_customers, min(4, len(real_customers))):
        created = min(customer[3] + timedelta(days=rng.randint(1, 20)), NOW)
        customers.append([customer[0] + 1000, customer[1], customer[2], created, created])

    # subscriptions and invoices with inconsistent values
    cancelled = [s for s in subscriptions if s[3] == "cancelled"]
    for sub in rng.sample(cancelled, min(3, len(cancelled))):
        sub[7] = None
    for invoice in rng.sample(invoices, min(3, len(invoices))):
        invoice[4] = invoice[3] - timedelta(days=rng.randint(1, 3))
    for invoice in rng.sample(invoices, min(2, len(invoices))):
        invoice[1] = -abs(invoice[1])

    # hubspot
    companies, deals = [], []
    company_id = deal_id = 1
    for customer in [c for c in customers if c[0] < 1999]:
        if rng.random() > 0.85:
            continue
        domain = fake.domain_name()
        domain = rng.choice([domain, domain, domain, "https://www." + domain, domain.upper()])
        created = customer[3] - timedelta(days=rng.randint(10, 60))
        link = None if rng.random() < 0.15 else customer[0]
        companies.append([company_id, customer[1], domain, link, created, min(created + timedelta(days=90), NOW)])
        amount = rng.choice([49, 149, 399]) * 1200
        deals.append([deal_id, company_id, "closed_won", amount, customer[3].date(), created, created + timedelta(days=20)])
        company_id, deal_id = company_id + 1, deal_id + 1
    for _ in range(40):
        created = at(rng, START + timedelta(days=rng.randint(0, 520)))
        companies.append([company_id, fake.company(), fake.domain_name(), None, created, created])
        stage = rng.choice(["appointment_scheduled", "qualified_to_buy", "contract_sent", "closed_lost"])
        close = created.date() + timedelta(days=30) if stage == "closed_lost" else None
        deals.append([deal_id, company_id, stage, rng.choice([49, 149, 399]) * 1200, close, created, created])
        company_id, deal_id = company_id + 1, deal_id + 1
    for company in rng.sample(companies, min(6, len(companies))):
        created = min(company[4] + timedelta(days=rng.randint(5, 40)), NOW)
        companies.append([company_id, company[1], company[2], None, created, created])
        company_id += 1
    linked_companies = [c for c in companies if c[3]]
    for company in rng.sample(linked_companies, min(3, len(linked_companies))):
        company[3] = 777000 + company[0]
    won = [d for d in deals if d[2] == "closed_won"]
    for deal in rng.sample(won, min(4, len(won))):
        deal[4] = None
    dated = [d for d in deals if d[4]]
    for deal in rng.sample(dated, min(3, len(dated))):
        deal[4] = deal[5].date() - timedelta(days=rng.randint(3, 15))
    data["companies"], data["deals"] = companies, deals


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--workspaces", type=int, default=300)
    parser.add_argument("--message-scale", type=float, default=1.0, help="multiplies message volume")
    args = parser.parse_args()
    rng, fake = random.Random(args.seed), Faker("de_DE")
    Faker.seed(args.seed)

    data = build(rng, fake, args.workspaces)
    add_mess(rng, fake, data)

    invoice_rows = [(i + 1, *inv) for i, inv in enumerate(data["invoices"])]
    credit_note_rows = [(i + 1, *note) for i, note in enumerate(data["credit_notes"])]
    event_rows = [(i + 1, *event, event[2], event[2]) for i, event in enumerate(sorted(data["events"], key=lambda e: e[2]))]
    plan_rows = [
        (p, n, price, START, datetime.combine(PRICE_RISE, time(9), tzinfo=timezone.utc) if p == 2 else START)
        for p, n, price in PLANS
    ]

    with psycopg.connect(DSN) as conn, conn.cursor() as cursor:
        cursor.execute(f"TRUNCATE {', '.join(TABLES)} CASCADE")
        ts = ("created_at", "updated_at")
        copy_rows(cursor, "product.workspaces", ("id", "name", *ts), data["workspaces"])
        copy_rows(cursor, "product.users", ("id", "workspace_id", "email", "role", *ts), data["users"])
        copy_rows(cursor, "chargebee.plan", ("id", "name", "monthly_price_cents", *ts), plan_rows)
        copy_rows(cursor, "chargebee.customer", ("id", "name", "workspace_id", *ts), data["customers"])
        copy_rows(
            cursor, "chargebee.subscription",
            ("id", "customer_id", "plan_id", "status", "plan_amount_cents", "quantity",
             "start_date", "cancelled_date", *ts),
            data["subscriptions"],
        )
        copy_rows(
            cursor, "chargebee.subscription_event",
            ("id", "subscription_id", "event_type", "occurred_at", "plan_id", "plan_amount_cents",
             "quantity", "status", *ts),
            event_rows,
        )
        copy_rows(cursor, "chargebee.invoice", ("id", "subscription_id", "amount_cents", "status", *ts), invoice_rows)
        copy_rows(
            cursor, "chargebee.credit_note",
            ("id", "subscription_id", "amount_cents", "reason", "status", *ts), credit_note_rows,
        )
        copy_rows(cursor, "hubspot.companies", ("id", "name", "domain", "chargebee_customer_id", *ts), data["companies"])
        copy_rows(
            cursor, "hubspot.deals",
            ("id", "company_id", "stage", "amount_cents", "close_date", *ts), data["deals"],
        )
        copy_rows(
            cursor, "product.messages",
            ("id", "workspace_id", "user_id", "channel", "direction", "sent_at", *ts),
            message_rows(rng, data["activity"], data["users_by_workspace"], args.message_scale),
        )


if __name__ == "__main__":
    main()
