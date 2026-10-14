"""Corpus freshness check (DESIGN #7). Opens a review; never edits a rule.

Two signals against the eCFR versions API for 8 CFR 214.2:
  1. an amendment newer than the newest date we pinned (a rule source_url /on/<date>/), and
  2. a rule quote (or contested quote) no longer found in the latest text.
Exit 1 if either fires, so the scheduled CI run fails and the owner reviews (human gate).
SEVP announcements (where injunctions show up) have no API; they stay a manual check.

Usage: python evals/freshness.py
"""
import gzip
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))
from optwise.rules import load_rules  # noqa: E402

API = "https://www.ecfr.gov/api/versioner/v1"
RULES = load_rules(Path(__file__).parents[1] / "data" / "rules.toml")


def get(url: str) -> bytes:
    # The full-text endpoint refuses uncompressed responses (406).
    req = urllib.request.Request(url, headers={"User-Agent": "optwise-freshness-check", "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        return gzip.decompress(body) if r.headers.get("Content-Encoding") == "gzip" else body


def norm(text: str) -> str:
    # Tags become spaces, so "(C)(<I>2</I>)" would read "(C)( 2 )": close up spaces inside parentheses.
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text)))
    return re.sub(r"\(\s+", "(", re.sub(r"\s+\)", ")", t)).strip()


def main() -> int:
    meta = json.loads(get(f"{API}/versions/title-8.json?part=214&section=214.2"))["meta"]
    latest = meta["latest_amendment_date"]
    urls = [r.source_url for r in RULES.values()] + [r.contested.source_url for r in RULES.values() if r.contested]
    pinned = max(re.search(r"/on/(\d{4}-\d{2}-\d{2})/", u).group(1) for u in urls)
    text = norm(get(f"{API}/full/{latest}/title-8.xml?part=214&section=214.2").decode())

    # A change already reviewed: the codified sentence was replaced by a contested value we recorded, while
    # the pinned text stays in force (e.g. the 60 -> 30 day change blocked by a court order).
    reviewed = {norm(r.quote) for r in RULES.values() if r.contested and norm(r.contested.quote) in text}
    problems, notes = [], []
    if latest > pinned:
        problems.append(f"8 CFR 214.2 amended on {latest}, after the newest pinned version ({pinned}): review the diff at "
                        f"https://www.ecfr.gov/compare/{latest}/to/{pinned}/title-8/section-214.2")
    for r in RULES.values():
        for label, quote in [(r.id, r.quote)] + ([(f"{r.id} (contested)", r.contested.quote)] if r.contested else []):
            if norm(quote) in text:
                continue
            if norm(quote) in reviewed:
                notes.append(f"{label}: codified text changed; already reviewed as a contested rule, pinned text in force")
            else:
                problems.append(f"{label}: quote not found in the {latest} text")
    print(f"latest amendment {latest}, newest pinned {pinned}, {len(RULES)} rules checked")
    for n in notes:
        print(f"  NOTE    {n}")
    for p in problems:
        print(f"  REVIEW  {p}")
    if not problems:
        print("  OK  no unreviewed amendment; every quote is in the latest text or recorded as contested")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
