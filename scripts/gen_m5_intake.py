#!/usr/bin/env python3
"""Generate the 5.2 intake set (25 section 3 start state, "The intake set for B3"; section 8.2).

    python3 scripts/gen_m5_intake.py [--check]

Writes data/ara-m5/intake/cortex-intake.ndjson: 40 complaint and dispute records from Cortex's web intake,
each with intake_id, received_at, channel, customer_name, customer_tin, account_number and message, and
data/ara-m5/intake/planted.json, which lists every identifier a customer typed into a message, in the exact
form typed, with its record, kind (tin or account) and format. Graders and the README read planted.json.

- customer_tin: SSN-shaped AAA-GG-SSSS, area 900 to 999 (never issued), unique, and used nowhere in the
  M5 corpus (cortex-cases, cortex-sar-narratives).
- account_number: the M3 format NN-NNNNN-N, unused anywhere in the M5 corpus. Three customers wrote twice,
  so three account numbers have two records.
- channel: web_form, mobile_app or identity_theft_form (the web form's identity-theft report page).
- message: free text. 14 messages hold the customer's own TIN and 11 the customer's account number, typed in the
  formats customers use: with dashes, with spaces, as bare digits, after a label ("SSN:", "acct #"). Two
  messages name a second account of the same customer that is in no structured field. A redact pattern
  written only for the dashed forms misses the others (25 section 3, acceptance item 1).
- No other run of eight or more digits appears in any message, so a scan for planted values cannot hit a
  date, an amount or a phone number.

--check exits 1 when the committed files differ from a fresh build.
"""
import json
import pathlib
import random
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ara-m5" / "intake"
SEED = 52
ACCOUNT = re.compile(r"\b\d{2}-\d{5}-\d\b")
RESERVED_ACCOUNTS = {"58-20417-3"}  # the example in cortex.intake_lookup's parameter description

FIRST = ["Maribel", "Desmond", "Priya", "Tomasz", "Lucia", "Grant", "Odette", "Kwame", "Hollis", "Renata",
         "Ibrahim", "Colette", "Duc", "Sienna", "Bartholomew", "Ngozi", "Ezra", "Fernanda", "Lachlan", "Mireille",
         "Osvaldo", "Tamsin", "Yusuf", "Annika", "Dorian", "Imelda", "Kenji", "Leonor", "Rashid", "Wilhelmina",
         "Arturo", "Bethany", "Cormac", "Delphine", "Emeka", "Gwendolyn", "Haruto"]
LAST = ["Achterberg", "Valdivia", "Okonkwo", "Lindqvist", "Ferreira", "Halvorsen", "Mbeki", "Castellano",
        "Nakashima", "Pellegrini", "Szymanski", "Thibodeaux", "Wainwright", "Abernathy", "Quiroga", "Rasmussen",
        "Delacroix", "Oyelaran", "Brennan", "Kowalczyk", "Montgomery", "Esposito", "Fairweather", "Gallardo"]

# One row per record, in intake_id order: (channel, message template, account group). {TIN} and {ACCT}
# are the record's own values; {ACCT2} is a second account of the same customer. The format of each
# typed value is named by the placeholder suffix: _d dashes, _s spaces, _p bare digits.
ROWS = [
    ("web_form", "I was charged a $35.00 overdraft fee on 10/02 even though my paycheck posted that morning. Please refund it.", 1),
    ("web_form", "Card ending 4417 was declined at a pharmacy on 10/04 for $62.18 although I had funds. My account is {ACCT_d}.", 2),
    ("mobile_app", "The app shows a pending transfer of $1,250.00 to a payee I do not recognise. Please stop it. SSN: {TIN_d} if you need to verify me.", 3),
    ("web_form", "Disputing a charge of $489.99 from an online electronics store on 09/28. I never received the order.", 4),
    ("identity_theft_form", "Someone opened a credit line in my name last week. My social is {TIN_s}. I did not apply for anything.", 5),
    ("web_form", "Your branch on Lamar Blvd closed my safe deposit box without notice. Account {ACCT_s}.", 6),
    ("web_form", "Two ATM withdrawals of $400.00 each on 10/07 at 2 a.m. were not me. Please call me at 512-555-0142.", 7),
    ("mobile_app", "I keep getting texts asking me to confirm a login I did not make. To prove it is me: {TIN_p}.", 8),
    ("web_form", "The interest on my savings was not paid for September. Please check account {ACCT_p}.", 9),
    ("web_form", "I was told my wire of $8,700.00 to my landlord would arrive in a day. It has been five days.", 10),
    ("identity_theft_form", "My mail was stolen and a replacement debit card was requested without my knowledge. SSN {TIN_d}, acct {ACCT_d}.", 11),
    ("web_form", "Please remove the monthly maintenance fee. I have kept the minimum balance since June.", 12),
    ("web_form", "A merchant charged me twice, $74.30 on 10/01 and again on 10/02. My SSN is {TIN_s} and my account {ACCT_s}.", 13),
    ("mobile_app", "Mobile deposit of a $910.00 check was rejected twice with no reason given.", 14),
    ("web_form", "I want to dispute a $19.99 subscription renewal I cancelled in August. Card ending 0263.", 2),
    ("web_form", "Your agent asked for my full SSN on the phone and I refused. Is that your policy? It is {TIN_d}, but I would rather not say it aloud.", 15),
    ("identity_theft_form", "A loan was taken out using my identity at another bank and it lists my Cortex account {ACCT_p} for payments. Tax ID {TIN_p}.", 16),
    ("web_form", "I was charged a foreign transaction fee on a purchase made in Austin. $3.12 on 09/30.", 17),
    ("web_form", "My checking account {ACCT_d} was frozen and nobody can tell me why. I also hold {ACCT2_d} and that one works.", 18),
    ("mobile_app", "The app logged me out and now says my profile is locked. Last four of my SSN are on file; full number {TIN_s}.", 19),
    ("web_form", "I would like to complain about the wait time at the Round Rock branch, over an hour on 10/05.", 20),
    ("web_form", "Please reverse the $25.00 returned item fee from 09/26. The payee bounced it by mistake.", 6),
    ("identity_theft_form", "Somebody changed the email on my online banking and moved $2,300.00 out. SSN: {TIN_s}.", 21),
    ("web_form", "My debit card was swallowed by the ATM at 6th and Congress on 10/08. Please send a new one to my home address.", 22),
    ("web_form", "I dispute the late fee on my credit card. The payment left account {ACCT_s} two days before the due date.", 23),
    ("mobile_app", "Zelle payment of $150.00 went to the wrong person. Please help me recover it. My social: {TIN_p}.", 24),
    ("web_form", "A check I deposited on 09/22 is still on hold. The hold notice says ten business days.", 25),
    ("web_form", "I never agreed to overdraft protection on account {ACCT_p}. Please remove it and refund the fees.", 26),
    ("identity_theft_form", "I got a letter about a new account I never opened. My TIN is {TIN_d}. I have filed a police report.", 27),
    ("web_form", "Please close my joint account; my former partner still has a card. My own account is {ACCT_d}, keep that one. Joint one is {ACCT2_s}.", 28),
    ("web_form", "The branch notary refused to notarise my document on 10/03 even though I am a customer.", 29),
    ("mobile_app", "Cash back of $40.00 from a store on 10/06 never came out but was charged. SSN#{TIN_d}.", 30),
    ("web_form", "I am disputing a $1,020.00 charge from a travel site. The trip was cancelled and they promised a refund.", 31),
    ("web_form", "Your letter says my address changed, but I did not change it. Social security number {TIN_s}.", 32),
    ("identity_theft_form", "My phone number was ported to another carrier without my consent and someone reset my password.", 33),
    ("web_form", "I was charged $12.00 for paper statements. I switched to e-statements in July.", 34),
    ("web_form", "Please explain the $4,500.00 hold on my account after a large deposit. It is my bonus. Acct #{ACCT_p}.", 35),
    ("mobile_app", "The app shows a balance of $0.00 though I had $3,118.40 this morning.", 20),
    ("web_form", "I want to complain that my dispute from 09/15 was closed without a reply. My SSN is {TIN_p}.", 36),
    ("web_form", "A recurring charge of $9.99 from a streaming service continues after I cancelled. Card ending 7781.", 37),
]


def build() -> dict[str, str]:
    rng = random.Random(SEED)
    used_tins, used_accts = set(), set(RESERVED_ACCOUNTS)
    for f in ("cortex-cases.ndjson", "cortex-sar-narratives.ndjson"):
        for line in (ROOT / "data/ara-m5" / f).read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                used_tins.add(d["subject_tin"])
                used_accts.add(d["subject_account"])
                used_accts.update(ACCOUNT.findall(d["body"]))

    def new_tin() -> str:
        while True:
            t = f"{rng.randint(900, 999)}-{rng.randint(1, 99):02d}-{rng.randint(1, 9999):04d}"
            if t not in used_tins:
                used_tins.add(t)
                return t

    def new_account() -> str:
        while True:
            a = f"{rng.randint(10, 99)}-{rng.randint(10000, 99999)}-{rng.randint(0, 9)}"
            if a not in used_accts:
                used_accts.add(a)
                return a

    groups: dict[int, dict] = {}
    names = set()
    records, planted = [], []
    for i, (channel, template, group) in enumerate(ROWS, 1):
        if group not in groups:
            while True:
                name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
                if name not in names:
                    names.add(name)
                    break
            groups[group] = {"name": name, "tin": new_tin(), "acct": new_account(), "acct2": None}
        g = groups[group]
        if "{ACCT2" in template and not g["acct2"]:
            g["acct2"] = new_account()
        iid = f"intake-{i:03d}"
        day = 1 + (i * 7) % 30
        received = f"2026-10-{day:02d}T{8 + (i * 5) % 10:02d}:{(i * 13) % 60:02d}:00Z" if i % 3 else \
                   f"2026-09-{day:02d}T{9 + (i * 3) % 9:02d}:{(i * 17) % 60:02d}:00Z"
        message = template
        for ph in re.findall(r"\{(TIN|ACCT2|ACCT)_([dsp])\}", template):
            kind, fmt = ph
            value = g["tin"] if kind == "TIN" else g["acct2"] if kind == "ACCT2" else g["acct"]
            typed = value if fmt == "d" else value.replace("-", " ") if fmt == "s" else value.replace("-", "")
            message = message.replace("{" + f"{kind}_{fmt}" + "}", typed, 1)
            planted.append({"intake_id": iid, "kind": "tin" if kind == "TIN" else "account", "value": value,
                            "typed": typed, "format": {"d": "dashes", "s": "spaces", "p": "digits"}[fmt],
                            "structured": kind != "ACCT2", "channel": channel})
        assert "{" not in message, message
        records.append({"intake_id": iid, "received_at": received, "channel": channel, "customer_name": g["name"],
                        "customer_tin": g["tin"], "account_number": g["acct"], "message": message})
    # Nothing else in a message holds a planted value's digits: the planted-value scan can only hit what was
    # planted (a phone number such as 512-555-0142 is a digit run, but holds no planted value).
    digits = {re.sub(r"\D", "", x) for g in groups.values() for x in (g["tin"], g["acct"], g["acct2"]) if x}
    for r in records:
        rest = r["message"]
        for p in planted:
            if p["intake_id"] == r["intake_id"]:
                rest = rest.replace(p["typed"], " ")
        runs = [re.sub(r"\D", "", m) for m in re.findall(r"\d(?:[\s.\-]?\d)*", rest)]
        assert not any(d in run for d in digits for run in runs), (r["intake_id"], rest)
    dump = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records)
    meta = {"_doc": "Every identifier a customer typed into an intake message (scripts/gen_m5_intake.py). value: the "
                    "identifier as stored (customer_tin or account_number format); typed: exactly as it appears in the "
                    "message; structured: false for a second account that is in no structured field.",
            "planted": planted}
    return {"cortex-intake.ndjson": dump, "planted.json": json.dumps(meta, indent=1) + "\n"}


def main() -> int:
    files = build()
    if "--check" in sys.argv[1:]:
        stale = [n for n, text in files.items() if not (OUT / n).exists() or (OUT / n).read_text() != text]
        print("data/ara-m5/intake: " + (f"STALE {stale}" if stale else "current"))
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for n, text in files.items():
        (OUT / n).write_text(text)
    planted = json.loads(files["planted.json"])["planted"]
    print(f"wrote data/ara-m5/intake: {files['cortex-intake.ndjson'].count(chr(10))} records, {len(planted)} typed "
          f"identifiers ({sum(p['kind'] == 'tin' for p in planted)} TINs, {sum(p['kind'] == 'account' for p in planted)} accounts)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
