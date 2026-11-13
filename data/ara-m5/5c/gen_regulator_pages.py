#!/usr/bin/env python3
"""S2 regulator library: plain-text copies of public-domain US regulations (eCFR) for ara-m5-pages/ (07 section 2.2).

Network step, run by the builder (not at provisioning): fetches each section from the eCFR versioner API (needs
--compressed-style gzip), keeps the section's paragraphs as plain text unchanged apart from tag removal, and writes a
page with a title line (the page's first heading; the integrity procedure checks it) and a provenance paragraph as
ara-m4-pages/ has. Usage: gen_regulator_pages.py <out-dir> [--date 2025-01-01]
"""
from __future__ import annotations

import argparse
import gzip
import pathlib
import re
import urllib.request
import xml.etree.ElementTree as ET

# slug -> (title line, [(title number, part, section), ...], what the page is for)
PAGES = {
    "fincen-sar-rule-31-cfr-1020-320": ("FinCEN, Reports by banks of suspicious transactions (31 CFR 1020.320)",
                                         [(31, 1020, "1020.320")], "when a bank must file a Suspicious Activity Report"),
    "fincen-ctr-and-structuring-31-cfr-1010-311-314": (
        "FinCEN, currency transaction reports and structured transactions (31 CFR 1010.311 and 1010.314)",
        [(31, 1010, "1010.311"), (31, 1010, "1010.314")], "the 10,000 dollar CTR duty and the ban on structuring"),
    "fincen-monetary-instruments-31-cfr-1010-415": (
        "FinCEN, purchases of bank checks and drafts, cashier's checks, money orders and traveler's checks (31 CFR 1010.415)",
        [(31, 1010, "1010.415")], "records a bank keeps for cash purchases of monetary instruments of 3,000 dollars or more"),
    "fincen-record-retention-31-cfr-1010-430": ("FinCEN, nature of records and retention period (31 CFR 1010.430)",
                                                 [(31, 1010, "1010.430")], "how long and in what form records are kept"),
    "occ-sar-rule-12-cfr-21-11": ("OCC, Suspicious Activity Report for national banks (12 CFR 21.11)",
                                   [(12, 21, "21.11")], "the national-bank SAR duty, thresholds and the 30-day filing clock"),
}


def fetch(title: int, part: int, section: str, date: str) -> list[str]:
    url = f"https://www.ecfr.gov/api/versioner/v1/full/{date}/title-{title}.xml?part={part}&section={section}"
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    raw = urllib.request.urlopen(req, timeout=40).read()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass
    root = ET.fromstring(raw)
    out = []
    for el in root.iter():
        if el.tag in ("HEAD", "P"):
            text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
            if text:
                out.append(("## " + text) if el.tag == "HEAD" else text)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--date", default="2025-01-01")
    a = ap.parse_args()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for slug, (title, secs, purpose) in PAGES.items():
        body = []
        for t, p, s in secs:
            body += fetch(t, p, s, a.date) + [f"Source: https://www.ecfr.gov/current/title-{t}/section-{s}", ""]
        head = (f"# {title}\n\nPublic-domain US government text, copied for the Cortex Bank and Trust lab (fictional bank): "
                f"{purpose}. The text below is the eCFR print of the section as of {a.date}, unchanged apart from tag removal "
                f"and line wrapping.\n\n")
        (out / f"{slug}.md").write_text(head + "\n\n".join(body).rstrip() + "\n", encoding="utf-8")
        print(slug, len((out / f"{slug}.md").read_text()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
