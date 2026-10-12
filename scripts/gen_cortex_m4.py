#!/usr/bin/env python3
"""gen_cortex_m4.py - build-time generator for the Module 4 Cortex fraud data.

Run once, output committed, reviewed as content. Never run at track setup (22 section 8.2):
provision.sh loads the committed snapshot with lib/ara_m4_data.py and rebases every timestamp
by one offset, so the newest event lands at load time minus one day.

    python3 scripts/gen_cortex_m4.py            # writes data/ara-m4-fraud/
    python3 scripts/gen_cortex_m4.py --check    # regenerate in memory, exit 1 if the files differ

Seeded and deterministic: the same seed writes byte-identical files. The planted entities match
the source workshop (research/16 section 2.4) so every id in 22 section 8.2 holds; the schema is
flat and Cortex-native, and every name (banks, brokers' firms, merchants) is fictional, so no
brand scrubbing is needed (departure D-16).

Timeline. All timestamps sit in a 9-day window ending at SNAPSHOT_NOW. The loader shifts them so
the newest event lands at load time minus one day. Planted structuring deposits are placed so the
in-window ones stay inside a 7-day lookback for at least 18 hours after load.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import io
import json
import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ara-m4-fraud"
SEED = 4401
UTC = dt.timezone.utc
SNAPSHOT_NOW = dt.datetime(2026, 10, 1, 5, 0, 0, tzinfo=UTC)   # midnight in Austin (UTC-5, CDT)
AUSTIN = dt.timedelta(hours=-5)
NOISE = {"cortex-wire-transfers": 20000, "cortex-cash-movements": 20000,
         "cortex-atm-events": 20000, "cortex-brokerage-trades": 10000}

FIRST = ["Ana", "Ben", "Carla", "Dmitri", "Elena", "Farid", "Grace", "Hiro", "Ines", "Jonah", "Kemal",
         "Lucia", "Mateo", "Nadia", "Omar", "Priya", "Quinn", "Rosa", "Samir", "Tara", "Umar", "Vera",
         "Wen", "Ximena", "Yusuf", "Zara", "Aylin", "Bruno", "Chloe", "Diego", "Emre", "Fatima", "Gil",
         "Hana", "Ivan", "Jae", "Kofi", "Lena", "Malik", "Noor"]
LAST = ["Abbott", "Barros", "Celik", "Dogan", "Eriksen", "Fischer", "Garza", "Haddad", "Ito", "Jensen",
        "Kaya", "Lindqvist", "Moreau", "Nakamura", "Okafor", "Petrov", "Quintero", "Rahman", "Silva",
        "Tanaka", "Umarov", "Varga", "Weber", "Xu", "Yilmaz", "Zhou", "Arslan", "Brandt", "Costa", "Duarte"]

# Planted entities (research/16 section 2.4; 22 section 8.2). Holder names are generated person names.
HOLDERS = {
    "1981": "Christine Lefevre", "476": "Wei Zeng",
    "1234": "Ali Dogan", "5678": "Murat Celik", "9012": "Chang Demir", "3456": "Ismail Yamazaki",
    "32687": "Sandrine Yang", "16384": "Han Yildiz", "8192": "Nathalie Simon", "4096": "Young Cho", "2048": "Josef Yamada",
    "1594": "Christopher Martinez", "21162": "Brian Kozlov", "1874": "Hulya Sidorov",
    "2718": "Cheng Ma", "3141": "Vopiscus Moeller", "1618": "Dong Lu", "1414": "Deng Tian",
}
STRUCTURING = ["1981", "476"]
DECOYS = ["1234", "5678", "9012", "3456"]
CHAIN = ["32687", "16384", "8192", "4096", "2048"]
SMURF_ACCOUNTS = [str(i) for i in range(2, 21, 2)]
SMURF_ATMS = [6, 7, 16, 18, 37, 49, 60, 61, 64, 68, 74, 78, 87, 91, 94, 100, 103, 106, 107, 111, 113, 116, 123, 124, 126]
LAYERING = ["1594", "21162", "1874"]
WASH = ["2718", "3141", "1618", "1414"]
FLAGGED_BROKERS = {3: "Christine Lefevre", 7: "Wei Zeng", 12: "Rania Haddad", 19: "Lin Cao", 23: "Pavel Varga"}
PROTECTED = set(HOLDERS)   # planted accounts get no random noise that could look like a pattern

BANKS = ["Colorado River Savings", "Barton Creek Bank", "Lady Bird Federal", "Pecan Street Trust",
         "Hill Country Credit Union", "Congress Avenue Bank", "Mueller Community Bank", "Zilker Savings",
         "Bluebonnet National", "Riverside Federal", "Capitol Ridge Bank", "Shoal Creek Trust",
         "Live Oak Savings", "Balcones Bank", "Onion Creek Federal", "Lamar Street Credit Union",
         "Cypress Valley Bank", "Brushy Creek Savings", "Red River Trust", "Walnut Creek Bank",
         "Bull Creek Federal", "Mopac Commerce Bank", "Tarrytown Savings", "Hyde Park Trust",
         "Clarksville Bank", "Travis Heights Federal", "Montopolis Credit Union", "Pflugerville Savings",
         "Round Rock Commerce", "Manor Road Bank"]
INTL = [("Shenzhen Harbour Bank", "China"), ("Minsk Union Bank", "Belarus"), ("Panama Isthmus Bank", "Panama"),
        ("Lagos Marina Bank", "Nigeria"), ("Victoria Peak Bank", "Hong Kong"), ("Baltic Amber Bank", "Latvia"),
        ("Bosporus Trade Bank", "Turkey"), ("Andes Pacific Bank", "Peru"), ("Danube Merchant Bank", "Hungary"),
        ("Gulf Pearl Bank", "United Arab Emirates")]
FIRMS = ["Cortex Securities", "Lonestar Brokerage", "Pecan Capital Markets", "Riverside Investments",
         "Hill Country Securities", "Capitol Wealth Partners", "Bluebonnet Brokerage", "Mopac Trading"]
SYMBOLS = ["ACRX", "BRVL", "CDNT", "DLTA", "ENVR", "FRMX", "GLDN", "HRZN", "INVT", "JNTR", "KSTL", "LMNA",
           "MRDN", "NOVA", "OPTX", "PRSM", "QRTZ", "RDGE", "SLVR", "TRNT"]
THIN = "QNTM"   # the wash-trading symbol: appears nowhere else


def iso(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def local(day_back: int, hour: int, minute: int = 0, second: int = 0) -> dt.datetime:
    """Austin wall-clock time `day_back` days before SNAPSHOT_NOW's local date."""
    d = (SNAPSHOT_NOW + AUSTIN).date() - dt.timedelta(days=day_back)
    return dt.datetime(d.year, d.month, d.day, hour, minute, second, tzinfo=UTC) - AUSTIN


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.seq = {}
        self.accounts: set[str] = set()

    def eid(self, prefix: str) -> str:
        self.seq[prefix] = self.seq.get(prefix, 0) + 1
        return f"{prefix}-{self.seq[prefix]:06d}"

    def noise_time(self, max_back: int = 9) -> dt.datetime:
        hour = self.r.choices(range(24), weights=[1, 1, 1, 1, 1, 2, 3, 5, 8, 10, 11, 12, 13, 12, 11, 10, 9, 8, 6, 4, 3, 2, 1, 1])[0]
        t = local(self.r.randint(1, max_back), hour, self.r.randint(0, 59), self.r.randint(0, 59))
        return t

    def money(self, lo: float, hi: float) -> float:
        return round(self.r.uniform(lo, hi), 2)

    def noise_account(self, hi: int = 8000) -> str:
        while True:
            a = str(self.r.randint(1, hi))
            if a not in PROTECTED:
                return a

    # ── wire transfers (account activity; structuring lives here) ──────────────
    def wire_transfers(self):
        r, docs, planted = self.r, [], {"structuring_deposits": {}, "structuring_out_of_window": {},
                                         "coordinated_wires": [], "decoy_events": {}}
        def ev(acct, t, event, etype, amount, **kw):
            self.accounts.add(acct)
            d = {"@timestamp": iso(t), "event_id": self.eid("wt"), "account_id": acct, "account_holder": None,
                 "account_type": kw.pop("account_type", "checking"), "account_event": event, "event_type": etype,
                 "amount": amount, "currency": "USD"}
            d.update(kw)
            docs.append(d)
            return d
        # Planted structuring: cash deposits of 9,250.00 to 9,500.00 at 4 PM Austin time.
        skip = {"1981": set(), "476": {3}}           # 476 misses one day: 5 deposits in window
        total = 0.0
        for acct in STRUCTURING:
            planted["structuring_deposits"][acct] = []
            for k in range(1, 7):
                if k in skip[acct]:
                    continue
                d = ev(acct, local(k, 16, r.randint(0, 14), r.randint(0, 59)), "deposit", "credit", self.money(9250, 9500),
                       deposit_type="cash", branch_id=str(r.randint(1, 30)))
                planted["structuring_deposits"][acct].append(d["event_id"])
                total += d["amount"]
            # One older deposit in the same band, outside a 7-day lookback: tests the window parameter.
            d = ev(acct, local(8, 16, 5), "deposit", "credit", self.money(9250, 9500), deposit_type="cash", branch_id="12")
            planted["structuring_out_of_window"][acct] = [d["event_id"]]
        # Coordinated outbound wires on day 1 at 16:59:5x, about 98 percent of the deposits, to one bank in China.
        remaining, n, sec = total * 0.98, 0, 59
        while remaining > 7500 and n < 10:
            amt = round(min(remaining, self.money(7500, 9999.99)), 2)
            acct = STRUCTURING[n % 2]
            d = ev(acct, local(1, 16, 59, sec), "wire", "debit", amt, wire_direction="outbound",
                   counterparty_bank=INTL[0][0], counterparty_country=INTL[0][1])
            planted["coordinated_wires"].append(d["event_id"])
            remaining -= amt; n += 1; sec -= 1
        # Decoys: large deposits and wires, never in the band, never at 4 PM; one in-band CHECK deposit on 1234.
        for acct in DECOYS:
            planted["decoy_events"][acct] = []
            for _ in range(r.randint(3, 4)):
                hour = r.choice([8, 9, 10, 11, 13, 14, 17, 18, 19])
                if r.random() < 0.6:
                    d = ev(acct, local(r.randint(1, 7), hour, r.randint(0, 59)), "deposit", "credit", self.money(10000.01, 25000), deposit_type="cash")
                else:
                    b = r.choice(INTL[1:])
                    d = ev(acct, local(r.randint(1, 7), hour, r.randint(0, 59)), "wire", "debit", self.money(10000.01, 25000),
                           wire_direction="outbound", counterparty_bank=b[0], counterparty_country=b[1])
                planted["decoy_events"][acct].append(d["event_id"])
        d = ev("1234", local(2, 10, 12), "deposit", "credit", 9610.00, deposit_type="check")
        planted["decoy_events"]["1234"].append(d["event_id"])
        # Ordinary activity on the planted accounts, none of it a cash deposit in the band.
        for acct in STRUCTURING + DECOYS:
            for _ in range(6):
                kind = r.choice(["purchase", "fee", "withdrawal", "deposit_small"])
                t = self.noise_time(8)
                if kind == "deposit_small":
                    ev(acct, t, "deposit", "credit", self.money(150, 4800), deposit_type="cash")
                elif kind == "purchase":
                    ev(acct, t, "purchase", "debit", self.money(5, 900), merchant_id=str(r.randint(1, 200)))
                elif kind == "fee":
                    ev(acct, t, "fee", "debit", self.money(2, 45))
                else:
                    ev(acct, t, "withdrawal", "debit", self.money(20, 800))
        # Noise.
        for _ in range(NOISE["cortex-wire-transfers"]):
            acct, t, x = self.noise_account(), self.noise_time(), r.random()
            if x < 0.05:
                dtp = r.choices(["cash", "check", "money_order"], [90, 8, 2])[0]
                amt = self.money(20, 8900) if dtp == "cash" else self.money(20, 15000)
                ev(acct, t, "deposit", "credit", amt, deposit_type=dtp, branch_id=str(r.randint(1, 30)))
            elif x < 0.15:
                ev(acct, t, "fee", "debit", self.money(1, 60))
            elif x < 0.35:
                if r.random() < 0.1:
                    b = r.choice(INTL[1:])
                    ev(acct, t, "wire", "debit", self.money(100, 30000), wire_direction="outbound",
                       counterparty_bank=b[0], counterparty_country=b[1])
                else:
                    ev(acct, t, "wire", r.choice(["debit", "credit"]), self.money(100, 30000),
                       wire_direction=r.choice(["outbound", "inbound"]), counterparty_bank=r.choice(BANKS),
                       counterparty_country="United States")
            elif x < 0.60:
                ev(acct, t, "withdrawal", "debit", self.money(20, 1500), account_type=r.choice(["checking", "savings"]))
            else:
                ev(acct, t, "purchase", "debit", self.money(2, 2500), merchant_id=str(r.randint(1, 200)))
        return docs, planted

    # ── cash movements (layering chain) ────────────────────────────────────────
    def cash_movements(self):
        r, docs, planted = self.r, [], {"layering_chain": CHAIN, "chain_events": []}
        def ev(acct, t, event, amount, **kw):
            self.accounts.add(acct)
            d = {"@timestamp": iso(t), "event_id": self.eid("cm"), "account_id": acct, "account_event": event,
                 "amount": amount, "currency": "USD"}
            d.update(kw)
            docs.append(d)
            return d
        amt = 25000.00
        planted["chain_events"].append(ev(CHAIN[0], local(8, 10, 5), "deposit", amt, deposit_type="cash")["event_id"])
        for hop in range(4):
            src, dst = CHAIN[hop], CHAIN[hop + 1]
            t = local(7 - hop, 11, r.randint(0, 50))
            planted["chain_events"].append(ev(src, t, "wire", amt, wire_direction="outgoing_domestic", to_account=dst)["event_id"])
            planted["chain_events"].append(ev(src, t + dt.timedelta(minutes=1), "fee", 15.00)["event_id"])
            amt = round(amt - 15.00, 2)
            planted["chain_events"].append(ev(dst, t + dt.timedelta(minutes=r.randint(5, 15)), "wire", amt,
                                              wire_direction="incoming_domestic", from_account=src)["event_id"])
        b = INTL[0]
        planted["chain_events"].append(ev(CHAIN[-1], local(2, 15, 30), "wire", round(amt - 45.00, 2),
                                          wire_direction="outgoing_international", counterparty_bank=b[0],
                                          counterparty_country=b[1])["event_id"])
        planted["chain_events"].append(ev(CHAIN[-1], local(2, 15, 31), "fee", 45.00)["event_id"])
        for _ in range(NOISE["cortex-cash-movements"]):
            acct, t, x = self.noise_account(), self.noise_time(), r.random()
            if x < 0.25:
                ev(acct, t, "deposit", self.money(20, 9000), deposit_type=r.choice(["cash", "check"]))
            elif x < 0.55:
                other = self.noise_account()
                if r.random() < 0.5:
                    ev(acct, t, "wire", self.money(50, 20000), wire_direction="outgoing_domestic", to_account=other)
                else:
                    ev(acct, t, "wire", self.money(50, 20000), wire_direction="incoming_domestic", from_account=other)
            elif x < 0.6:
                b = r.choice(INTL[1:])
                ev(acct, t, "wire", self.money(500, 20000), wire_direction="outgoing_international",
                   counterparty_bank=b[0], counterparty_country=b[1])
            elif x < 0.75:
                ev(acct, t, "fee", self.money(1, 60))
            else:
                ev(acct, t, "withdrawal", self.money(20, 2000))
        return docs, planted

    # ── ATM events (smurfing) ───────────────────────────────────────────────────
    def atm_events(self):
        r, docs, planted = self.r, [], {"smurfing_accounts": SMURF_ACCOUNTS, "smurfing_atms": SMURF_ATMS, "smurf_event_count": 0}
        def ev(acct, t, event, amount, atm, camera, **kw):
            self.accounts.add(acct)
            hour = (t + AUSTIN).hour
            d = {"@timestamp": iso(t), "event_id": self.eid("atm"), "account_id": acct, "atm_id": str(atm),
                 "atm_event": event, "amount": amount, "currency": "USD", "camera_enabled": camera,
                 "business_hours": 9 <= hour < 22}
            d.update(kw)
            docs.append(d)
        i = 0
        for k in range(1, 9):
            for slot in range(26):
                hh, mm = 9 + slot // 2, 30 * (slot % 2)
                ev(SMURF_ACCOUNTS[i % 10], local(k, hh, mm), "deposit", 500.00, SMURF_ATMS[i % 25], False, deposit_type="cash")
                i += 1
        planted["smurf_event_count"] = i
        smurf = set(SMURF_ACCOUNTS)
        for _ in range(NOISE["cortex-atm-events"]):
            acct = str(r.randint(1, 5000))
            if acct in PROTECTED or acct in smurf:
                acct = str(r.randint(5001, 8000))
            t, x, atm = self.noise_time(), r.random(), r.randint(1, 128)
            cam = r.random() < 0.85
            if x < 0.58:
                ev(acct, t, "withdrawal", float(r.choice([20, 40, 60, 80, 100, 200, 300, 400])), atm, cam)
            elif x < 0.88:
                amt = self.money(20, 3000)
                if amt == 500.0:
                    amt = 505.0
                ev(acct, t, "deposit", amt, atm, cam, deposit_type=r.choice(["cash", "check"]))
            elif x < 0.98:
                ev(acct, t, "inquiry", 0.0, atm, cam)
            else:
                ev(acct, t, "status_check", 0.0, atm, cam)
        return docs, planted

    # ── brokerage trades ────────────────────────────────────────────────────────
    def brokerage(self):
        r, docs = self.r, []
        planted = {"securities_layering": {"accounts": LAYERING, "broker_id": "3", "payout_ratio": 0.93},
                   "wash_trading": {"accounts": WASH, "broker_id": "19", "symbol": THIN, "rounds": 12},
                   "unexplained_wealth": {"account": "4096", "broker_id": "7", "payout_ratio": 0.97}}
        def ev(acct, t, event, amount, broker, **kw):
            self.accounts.add(acct)
            d = {"@timestamp": iso(t), "event_id": self.eid("bt"), "account_id": acct, "broker_id": str(broker),
                 "account_event": event, "amount": amount, "currency": "USD"}
            d.update(kw)
            docs.append(d)
            return d
        for acct in LAYERING:   # inbound wire, buys, liquidation of 98 percent, outbound at 0.93 of inbound
            inbound = self.money(500000, 2000000)
            t = local(7, 10, r.randint(0, 59))
            ev(acct, t, "wire", inbound, 3, wire_direction="inbound", counterparty_bank=r.choice(BANKS))
            rem = inbound
            for j in range(r.randint(4, 8)):
                sym = r.choice(SYMBOLS); spend = round(rem * r.uniform(0.1, 0.3), 2); price = self.money(5, 200)
                ev(acct, t + dt.timedelta(hours=6 + 12 * j), "buy", spend, 3, symbol=sym, price=price, quantity=int(spend // price))
                rem -= spend
            ev(acct, local(2, 14, r.randint(0, 59)), "liquidation", round(inbound * 0.98, 2), 3)
            ev(acct, local(1, 11, r.randint(0, 59)), "wire", round(inbound * 0.93, 2), 3, wire_direction="outbound",
               counterparty_bank=INTL[4][0], counterparty_country=INTL[4][1])
        for rnd in range(12):   # wash trading: buy and matching sell 2-90 s apart sharing a trade id
            a, b = r.sample(WASH, 2)
            t = local(r.randint(1, 7), r.randint(10, 15), r.randint(0, 59), r.randint(0, 59))
            notional = self.money(50000, 400000); price = self.money(1, 4); qty = int(notional // price)
            tid = f"tr-{rnd + 1:04d}"
            ev(a, t, "buy", notional, 19, symbol=THIN, price=price, quantity=qty, trade_id=tid, counterparty_account=b)
            ev(b, t + dt.timedelta(seconds=r.randint(2, 90)), "sell", notional, 19, symbol=THIN, price=price, quantity=qty,
               trade_id=tid, counterparty_account=a)
        inbound = self.money(250000, 1500000)   # unexplained wealth on 4096
        t = local(4, 9, 15)
        ev("4096", t, "wire", inbound, 7, wire_direction="inbound", counterparty_bank=r.choice(BANKS))
        ev("4096", t + dt.timedelta(hours=1), "buy", round(inbound * 0.99, 2), 7, symbol=r.choice(SYMBOLS), price=self.money(20, 90))
        ev("4096", t + dt.timedelta(hours=25), "liquidation", round(inbound * 0.99, 2), 7)
        ev("4096", t + dt.timedelta(hours=30), "wire", round(inbound * 0.97, 2), 7, wire_direction="outbound",
           counterparty_bank=INTL[9][0], counterparty_country=INTL[9][1])
        for _ in range(NOISE["cortex-brokerage-trades"]):
            acct, t, x = self.noise_account(), self.noise_time(), r.random()
            broker = r.choice([b for b in range(1, 41) if b not in FLAGGED_BROKERS] * 9 + list(FLAGGED_BROKERS))
            sym = r.choice(SYMBOLS); price = self.money(5, 300)
            if x < 0.34:
                amt = self.money(100, 50000); ev(acct, t, "buy", amt, broker, symbol=sym, price=price, quantity=int(amt // price))
            elif x < 0.64:
                amt = self.money(100, 50000); ev(acct, t, "sell", amt, broker, symbol=sym, price=price, quantity=int(amt // price))
            elif x < 0.72:
                ev(acct, t, "dividend", self.money(5, 900), broker, symbol=sym)
            elif x < 0.80:
                ev(acct, t, "fee", self.money(1, 50), broker)
            elif x < 0.92:
                ev(acct, t, "wire", self.money(500, 60000), broker, wire_direction=r.choice(["inbound", "outbound"]),
                   counterparty_bank=r.choice(BANKS))
            else:
                ev(acct, t, "transfer", self.money(100, 20000), broker)
        return docs, planted

    # ── lookups ────────────────────────────────────────────────────────────────
    def lookups(self):
        r = self.r
        accounts = []
        for a in sorted(self.accounts, key=int):
            name = HOLDERS.get(a) or f"{r.choice(FIRST)} {r.choice(LAST)}"
            accounts.append({"account_id": a, "holder_name": name, "account_type": r.choice(["checking", "checking", "savings"]),
                             "opened_date": (dt.date(2012, 1, 1) + dt.timedelta(days=r.randint(0, 5000))).isoformat(),
                             "branch_id": str(r.randint(1, 30)), "city": "Austin", "state": "TX"})
        banks = [{"bank_id": str(i + 1), "name": n, "routing_number": f"11{r.randint(1000000, 9999999)}", "city": "Austin"}
                 for i, n in enumerate(BANKS)]
        intbanks = [{"intbank_id": str(i + 20), "name": n, "country": c} for i, (n, c) in enumerate(INTL)]
        brokers = []
        for b in range(1, 41):
            name = FLAGGED_BROKERS.get(b) or f"{r.choice(FIRST)} {r.choice(LAST)}"
            brokers.append({"broker_id": str(b), "name": name, "firm": r.choice(FIRMS), "crd": str(r.randint(1000000, 9999999)),
                            "flagged": b in FLAGGED_BROKERS})
        merchants = [{"merchant_id": str(i), "name": f"{r.choice(LAST)} {r.choice(['Grocery', 'Hardware', 'Cafe', 'Books', 'Auto', 'Pharmacy', 'Outfitters', 'Electronics'])}",
                      "city": "Austin"} for i in range(1, 201)]
        return {"cortex-ref-accounts": accounts, "cortex-ref-banks": banks, "cortex-ref-intbanks": intbanks,
                "cortex-ref-brokers": brokers, "cortex-ref-merchants": merchants}


KW = {"type": "keyword"}
MAPPINGS = {
    "cortex-wire-transfers": {"@timestamp": {"type": "date"}, "event_id": KW, "account_id": KW, "account_holder": KW,
        "account_type": KW, "account_event": KW, "event_type": KW, "deposit_type": KW, "amount": {"type": "double"},
        "currency": KW, "wire_direction": KW, "counterparty_bank": KW, "counterparty_country": KW, "branch_id": KW, "merchant_id": KW},
    "cortex-cash-movements": {"@timestamp": {"type": "date"}, "event_id": KW, "account_id": KW, "account_event": KW,
        "deposit_type": KW, "amount": {"type": "double"}, "currency": KW, "wire_direction": KW, "to_account": KW,
        "from_account": KW, "counterparty_bank": KW, "counterparty_country": KW},
    "cortex-atm-events": {"@timestamp": {"type": "date"}, "event_id": KW, "account_id": KW, "atm_id": KW, "atm_event": KW,
        "deposit_type": KW, "amount": {"type": "double"}, "currency": KW, "camera_enabled": {"type": "boolean"},
        "business_hours": {"type": "boolean"}},
    "cortex-brokerage-trades": {"@timestamp": {"type": "date"}, "event_id": KW, "account_id": KW, "broker_id": KW,
        "account_event": KW, "amount": {"type": "double"}, "currency": KW, "symbol": KW, "price": {"type": "double"},
        "quantity": {"type": "long"}, "trade_id": KW, "counterparty_account": KW, "wire_direction": KW, "counterparty_bank": KW,
        "counterparty_country": KW},
    "cortex-ref-accounts": {"account_id": KW, "holder_name": KW, "account_type": KW, "opened_date": {"type": "date"},
        "branch_id": KW, "city": KW, "state": KW},
    "cortex-ref-banks": {"bank_id": KW, "name": KW, "routing_number": KW, "city": KW},
    "cortex-ref-intbanks": {"intbank_id": KW, "name": KW, "country": KW},
    "cortex-ref-brokers": {"broker_id": KW, "name": KW, "firm": KW, "crd": KW, "flagged": {"type": "boolean"}},
    "cortex-ref-merchants": {"merchant_id": KW, "name": KW, "city": KW},
}
# Record indices the tracks write to (22 section 8.1). Created empty, with these mappings.
RECORD_MAPPINGS = {
    "cortex-fraud-cases": {"case_id": KW, "account_id": KW, "pattern": KW, "risk_rating": KW, "rationale": {"type": "text"},
        "findings": {"type": "text"}, "execution_id": KW, "created_at": {"type": "date"}, "source": KW},
    "cortex-audit": {"audit_id": KW, "account_id": KW, "action": KW, "outcome": KW, "detail": {"type": "text"},
        "execution_id": KW, "created_at": {"type": "date"}, "actor": KW},
    "cortex-escalations": {"escalation_id": KW, "account_id": KW, "reason": {"type": "text"}, "request": {"type": "text"},
        "execution_id": KW, "created_at": {"type": "date"}},
    "cortex-sar-filings": {"filing_id": KW, "account_id": KW, "status": KW, "narrative": {"type": "text"},
        "execution_id": KW, "created_at": {"type": "date"}},
}


def build() -> dict[str, bytes]:
    g = Gen(SEED)
    wt, p_wt = g.wire_transfers()
    cm, p_cm = g.cash_movements()
    atm, p_atm = g.atm_events()
    bt, p_bt = g.brokerage()
    look = g.lookups()
    holders = {a["account_id"]: a["holder_name"] for a in look["cortex-ref-accounts"]}
    for d in wt:
        d["account_holder"] = holders[d["account_id"]]
    files: dict[str, bytes] = {}
    def ndjson_gz(docs):
        docs = sorted(docs, key=lambda d: (d.get("@timestamp", ""), d.get("event_id", "") or json.dumps(d, sort_keys=True)))
        raw = "".join(json.dumps({k: v for k, v in d.items() if v is not None}, sort_keys=True) + "\n" for d in docs).encode()
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as f:
            f.write(raw)
        return buf.getvalue()
    for name, docs in (("cortex-wire-transfers", wt), ("cortex-cash-movements", cm), ("cortex-atm-events", atm),
                       ("cortex-brokerage-trades", bt), *look.items()):
        files[f"{name}.ndjson.gz"] = ndjson_gz(docs)
    files["mappings.json"] = (json.dumps({"data": MAPPINGS, "records": RECORD_MAPPINGS}, indent=2, sort_keys=True) + "\n").encode()
    newest = max(d["@timestamp"] for d in wt + cm + atm + bt)
    planted = {"_doc": "Planted entities and their event ids. Public by design: the tracks name these accounts in their questions.",
               "seed": SEED, "snapshot_now": iso(SNAPSHOT_NOW), "newest_event": newest,
               "rebase_rule": "offset = (load time - 1 day) - newest_event, applied to every @timestamp",
               "cortex-wire-transfers": p_wt, "cortex-cash-movements": p_cm, "cortex-atm-events": p_atm,
               "cortex-brokerage-trades": p_bt, "flagged_brokers": {str(k): v for k, v in FLAGGED_BROKERS.items()},
               "counts": {"cortex-wire-transfers": len(wt), "cortex-cash-movements": len(cm), "cortex-atm-events": len(atm),
                          "cortex-brokerage-trades": len(bt), **{k: len(v) for k, v in look.items()}}}
    files["planted.json"] = (json.dumps(planted, indent=2, sort_keys=True) + "\n").encode()
    return files


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    files = build()
    if a.check:
        bad = [n for n, b in files.items() if not (OUT / n).exists() or (OUT / n).read_bytes() != b]
        print("OK: snapshot matches the generator" if not bad else f"DRIFT: {bad}")
        sys.exit(1 if bad else 0)
    OUT.mkdir(parents=True, exist_ok=True)
    for n, b in files.items():
        (OUT / n).write_bytes(b)
        print(f"{n}: {len(b):,} bytes")


if __name__ == "__main__":
    main()
