"""
Tender Pricing Data Generator  (v2)
-----------------------------------
Creates FICTIONAL tender data for MEP projects (HVAC, plumbing, fire fighting),
modelled on a real tender-pricing workflow:

  1. Receive tender documents            -> tenders.csv (one row per tender)
  2. Quantity take-off per item          -> boq_items.csv (bill of quantities)
  3. Request 2-3 quotes per item         -> supplier_quotes.csv
     (some suppliers quote incl. 14 % VAT, some without)
  4. Choose the cheapest quote (net of VAT)
  5. Dry unit cost = material + add-ons (fittings, supports, paint)
                     + labour & installation
  6. Rate = dry cost + overhead % + profit %  (both as % of dry cost)
  7. Submit the bid
  8. Result: won or lost (+ winning bid, if known)

Prices follow the USD/EGP exchange rate (fx_rates.csv). Imported items react
more strongly (factor 0.75) than locally assembled items (factor 0.65) -
the same factors used in a typical price-escalation clause:

      Increment = W x factor x (X2 - X1) / X1
      W  = BOQ item value, X1 = USD rate at tender, X2 = new USD rate

The data is deliberately "messy" (different spellings, units, date formats,
VAT bases, prices as text, missing values, duplicates), so it can be cleaned
with Power Query - just like real data typed by different people.

All names and numbers are invented. No real company data is used.

Usage:
    python3 generate_data.py
"""

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path


random.seed(42)  # same "random" data every time -> reproducible results
OUT = Path("data_raw")
OUT.mkdir(exist_ok=True)

VAT = 0.14

# ---------- 1. Master data ----------
PROJECT_TYPES = {
    # type: (share of tenders, profit % range, project size factor)
    "Office":         (0.30, (8, 18),  1.0),
    "Shopping Mall":  (0.25, (8, 16),  2.0),
    "Food Factory":   (0.25, (10, 20), 1.5),
    "Pharma Factory": (0.20, (14, 25), 1.8),  # stricter specs -> higher risk & profit
}
CITIES = ["Alexandria", "Cairo", "Giza", "Borg El Arab", "10th of Ramadan", "6th of October"]
CLIENTS = {  # fictional clients per project type
    "Office":         ["Nile Development Co.", "Lotus Offices", "Delta Real Estate"],
    "Shopping Mall":  ["Horizon Malls", "Delta Real Estate", "Nile Development Co."],
    "Food Factory":   ["Pyramid Foods", "Sphinx Industrial", "Golden Grain Foods"],
    "Pharma Factory": ["Mediterranean Pharma", "Crescent Healthcare", "Sphinx Industrial"],
}
# each supplier is a bit cheaper or more expensive than the market
SUPPLIERS = {"Supplier A": 0.95, "Supplier B": 1.00, "Supplier C": 1.05,
             "Supplier D": 0.92, "Supplier E": 1.10}

# item: (system, unit, origin, base material price in EGP (Jan 2013, net of VAT), qty range)
ITEMS = {
    "Air Handling Unit":  ("HVAC", "No.", "Local",    180_000, (2, 12)),
    "Chiller":            ("HVAC", "No.", "Imported", 900_000, (1, 4)),
    "Fan Coil Unit":      ("HVAC", "No.", "Imported", 9_000,   (20, 200)),
    "Ductwork":           ("HVAC", "m2",  "Local",    450,     (800, 9000)),
    "Chilled Water Pipe": ("HVAC", "m",   "Local",    650,     (300, 3000)),
    "Water Supply Pipe":  ("Plumbing", "m",   "Local",    180,   (300, 2500)),
    "Drainage Pipe":      ("Plumbing", "m",   "Local",    220,   (200, 2000)),
    "Sanitary Fixture":   ("Plumbing", "No.", "Imported", 3_500, (20, 300)),
    "Fire Pump Set":      ("Fire Fighting", "No.", "Imported", 350_000, (1, 2)),
    "Sprinkler Head":     ("Fire Fighting", "No.", "Imported", 120,     (300, 4000)),
    "Fire Hose Cabinet":  ("Fire Fighting", "No.", "Local",    6_500,   (5, 60)),
}
FX_FACTOR = {"Imported": 0.75, "Local": 0.65}   # share of the price that follows USD

# Messy spellings, like when several engineers type data by hand
MESSY_NAMES = {
    "Air Handling Unit": ["Air Handling Unit", "AHU", "ahu ", "Air handling unit"],
    "Fan Coil Unit": ["Fan Coil Unit", "FCU", "Fan coil unit"],
    "Chilled Water Pipe": ["Chilled Water Pipe", "CHW Pipe", "chilled water pipe"],
    "Sprinkler Head": ["Sprinkler Head", "Sprinkler", "sprinkler head"],
}
MESSY_UNITS = {"m": ["m", "M", "meter"], "m2": ["m2", "M2", "sqm"], "No.": ["No.", "nr", "pcs"]}
MESSY_VAT = {"excl": ["excl. VAT", "Excl VAT", "without VAT", "net"],
             "incl": ["incl. VAT 14%", "Incl VAT", "with VAT"]}


# ---------- 2. Exchange rate (fictional, roughly shaped like USD/EGP) ----------
def usd_rate(d: date) -> float:
    """Slow drift before Nov 2016, a jump at the devaluation, then a slow decline."""
    if d < date(2016, 11, 3):
        years = (d - date(2013, 1, 1)).days / 365
        return 6.4 + 0.65 * years                    # ~6.4 -> ~8.9
    months = (d.year - 2016) * 12 + d.month - 11
    return max(15.5, 18.0 - 0.05 * max(0, months - 3))   # ~18 -> ~16

USD_2013 = usd_rate(date(2013, 1, 1))


def price_index(d: date, origin: str) -> float:
    """Local inflation (~8 %/yr) on the non-USD part, exchange rate on the USD part."""
    years = (d - date(2013, 1, 1)).days / 365
    k = FX_FACTOR[origin]
    return (1 - k) * 1.08 ** years + k * usd_rate(d) / USD_2013


def messy_date(d: date) -> str:
    """Return the date in one of several text formats."""
    return random.choice([d.isoformat(), d.strftime("%d/%m/%Y"), d.strftime("%d.%m.%Y")])


def messy(value: str, options: dict) -> str:
    return random.choice(options[value]) if value in options else value


start, end = date(2013, 1, 1), date(2019, 12, 31)

# monthly exchange-rate table (clean - it is "official" reference data)
fx_rates = []
m = start
while m <= end:
    fx_rates.append({"Month": m.isoformat(), "USD_EGP": round(usd_rate(m), 2)})
    m = date(m.year + (m.month == 12), m.month % 12 + 1, 1)

# ---------- 3. Tenders, supplier quotes and BOQ ----------
tenders, boq, quotes = [], [], []
types, weights = zip(*[(t, v[0]) for t, v in PROJECT_TYPES.items()])
quote_no = 0
won_projects = []  # used in part 5 (cost controlling)

for i in range(1, 81):
    tender_id = f"T-{i:03d}"
    ptype = random.choices(types, weights)[0]
    _, (pr_min, pr_max), size = PROJECT_TYPES[ptype]
    d = start + timedelta(days=random.randint(0, (end - start).days))

    overhead_pct = round(random.uniform(28, 38), 1)   # % of dry cost
    profit_pct = round(random.uniform(pr_min, pr_max), 1)

    dry_total = 0
    system_cost = {}  # dry cost per system, used for the project budget
    items = random.sample(list(ITEMS), k=random.randint(6, len(ITEMS)))
    for n, item in enumerate(items, start=1):
        system, unit, origin, base, (qmin, qmax) = ITEMS[item]
        qty = round(random.randint(qmin, qmax) * size)
        market = base * price_index(d, origin)

        # step 3: 2-3 suppliers quote this item a few days/weeks before submission
        net_prices = []
        for sup in random.sample(list(SUPPLIERS), k=random.randint(2, 3)):
            net = market * SUPPLIERS[sup] * random.uniform(0.93, 1.07)
            net_prices.append(net)
            incl_vat = random.random() < 0.35
            shown = net * (1 + VAT) if incl_vat else net
            quote_no += 1
            quotes.append({
                "QuoteID": f"Q-{quote_no:04d}",
                "TenderID": tender_id,
                "QuoteDate": messy_date(d - timedelta(days=random.randint(5, 40))),
                "Supplier": sup,
                "ItemCategory": messy(item, MESSY_NAMES),
                "UnitPrice_EGP": f"{shown:,.0f}",                # text with thousands separator
                "PriceBasis": random.choice(MESSY_VAT["incl" if incl_vat else "excl"]),
                "ValidityDays": random.choice([30, 60, 90, ""]),  # some missing values
            })

        # step 4-5: cheapest net quote + add-ons + labour/installation = dry unit cost
        material = min(net_prices)
        addons_labour = material * random.uniform(0.15, 0.45)
        dry_unit = material + addons_labour
        dry_total += qty * dry_unit
        system_cost[system] = system_cost.get(system, 0) + qty * dry_unit

        boq.append({
            "TenderID": tender_id,
            "ItemNo": n,
            "System": system,
            "ItemCategory": messy(item, MESSY_NAMES),
            "Origin": origin,
            "Quantity": qty if random.random() > 0.02 else "",   # a few missing quantities
            "Unit": messy(unit, MESSY_UNITS),
            "MaterialUnit_EGP": round(material),
            "AddonsLabourUnit_EGP": round(addons_labour),
        })

    # step 6: rate = dry + overhead + profit (both as % of dry cost)
    bid = dry_total * (1 + overhead_pct / 100 + profit_pct / 100)

    # step 8: the higher the profit %, the lower the chance to win
    competitors = random.randint(2, 7)
    win_probability = max(0.05, 0.75 - 0.025 * profit_pct - 0.03 * competitors)
    won = random.random() < win_probability
    winning_bid = bid if won else bid * random.uniform(0.82, 0.98)
    if won:
        won_projects.append((tender_id, ptype, d, system_cost, overhead_pct))

    tenders.append({
        "TenderID": tender_id,
        "ProjectType": ptype,
        "Client": random.choice(CLIENTS[ptype]),
        "City": random.choice(CITIES),
        "SubmissionDate": messy_date(d),
        "OverheadPct": overhead_pct,
        "ProfitPct": profit_pct,
        "BidPrice_EGP": round(bid),
        "WinningBid_EGP": round(winning_bid) if random.random() > 0.08 else "",  # sometimes unknown
        "Result": random.choice(["Won", "won", "WON"]) if won else random.choice(["Lost", "lost"]),
        "Competitors": competitors,
    })

# a few duplicate rows, as happens when files are copied together
tenders += random.sample(tenders, 3)
boq += random.sample(boq, 10)
quotes += random.sample(quotes, 15)


# ---------- 4. Save as CSV ----------
def save(rows: list[dict], name: str) -> None:
    with open(OUT / name, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"Saved {len(rows):>5} rows -> {OUT / name}")


save(tenders, "tenders.csv")
save(boq, "boq_items.csv")
save(quotes, "supplier_quotes.csv")
save(fx_rates, "fx_rates.csv")


# ---------- 5. Cost controlling of executed projects (won tenders) ----------
# A separate random generator, so parts 1-4 stay exactly the same as before.
rng = random.Random(7)
STATUS_DATE = date(2020, 6, 30)  # "today" in the data: the reporting date
MESSY_SYSTEMS = {"HVAC": ["HVAC", "hvac", "H.V.A.C"],
                 "Plumbing": ["Plumbing", "plumbing"],
                 "Fire Fighting": ["Fire Fighting", "Fire-Fighting", "FF"]}


def add_months(d: date, n: int) -> date:
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


costs = []
for tender_id, ptype, submitted, system_cost, overhead_pct in won_projects:
    start_month = add_months(submitted, 2)          # work starts ~2 months after the bid
    duration = rng.randint(8, 20)                    # project length in months
    for system, dry in system_cost.items():
        budget = dry * (1 + overhead_pct / 100)      # budget at completion (BAC): dry cost + overhead
        overrun = rng.gauss(1.05, 0.07)              # how much more expensive the system really gets
        if ptype == "Pharma Factory":
            overrun += 0.05                          # strict specs -> more changes on site
        if system == "HVAC" and start_month <= date(2016, 11, 1) <= add_months(start_month, duration):
            overrun += 0.15                          # imported equipment hit by the devaluation
        # S-curve: little cost at the start and end, most in the middle
        weights = [math.sin(math.pi * (i + 0.5) / duration) for i in range(duration)]
        total_w = sum(weights)
        cum_planned = 0
        for i, w in enumerate(weights):
            month = add_months(start_month, i)
            planned = budget * w / total_w
            cum_planned += planned
            reported = month <= STATUS_DATE          # future months have no actuals yet
            actual = planned * overrun * rng.uniform(0.85, 1.15) if reported else None
            progress = min(100, cum_planned / budget * 100 * rng.uniform(0.9, 1.0))
            costs.append({
                "ProjectID": tender_id,
                "System": rng.choice(MESSY_SYSTEMS[system]),
                "Month": rng.choice([month.isoformat(), month.strftime("%d/%m/%Y"), month.strftime("%d.%m.%Y")]),
                "PlannedCost_EGP": round(planned),
                "ActualCost_EGP": round(actual) if actual is not None and rng.random() > 0.02 else "",
                "ProgressPct": round(progress, 1) if reported else "",
            })

save(costs, "project_costs.csv")
