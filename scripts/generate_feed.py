#!/usr/bin/env python3
"""
Official GoI compliance feed generator.

Fetches OFFICIAL Government of India press releases (PIB, English listing), filters to
GST + Income-Tax items, enriches each with its real publish date (from the detail page),
and emits a signed announcements.json.

Signing: Ed25519 detached signature over the exact UTF-8 bytes of announcements.json,
base64-encoded into announcements.json.sig. The private key never leaves the GitHub
Action secret; only the public key (ed25519_pub.pem) is public. A consuming client
embeds the public key and refuses any feed whose signature does not verify.

No third-party content, no LLM, no server we run.
"""
import base64
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone

from cryptography.hazmat.primitives.serialization import load_pem_private_key

# English PIB listing (Lang=1). Confirmed to return English titles incl. Finance/GST releases.
PIB_ALLREL_URL = "https://www.pib.gov.in/Allrel.aspx?Reg=3&Lang=1"
ENTRY_RE = re.compile(
    r"<a[^>]*title=['\"](?P<title>[^'\"]+)['\"][^>]*"
    r"href=['\"]/(?P<href>PressReleasePage\.aspx\?PRID=(?P<prid>\d+))['\"][^>]*>",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"(\d{1,2})\s+([A-Z]{3})\s+(\d{4})")
MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

GST_KEYWORDS = [
    "gst", "cbic", "customs", "indirect tax", "e-invoice", "e-way",
    "goods and services tax", "input tax credit", "itc",
]
INCOME_TAX_KEYWORDS = [
    "income tax", "income-tax", "cbdt", " itr", "direct tax", "26as", " tds ",
    "advance tax", "ais ", " face ", "income declaration", "tax deducted",
]


def categorize(text: str) -> str:
    t = " " + text.lower() + " "
    if any(k in t for k in GST_KEYWORDS):
        return "GST"
    if any(k in t for k in INCOME_TAX_KEYWORDS):
        return "INCOME_TAX"
    return "GENERAL"


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "GoI-Compliance-Feed/1.0 (+official PIB monitor)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_date(html: str, fallback: str) -> str:
    m = DATE_RE.search(html)
    if m and m.group(2) in MONTHS:
        try:
            return datetime(int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)), tzinfo=timezone.utc).isoformat()
        except Exception:
            return fallback
    return fallback


def main():
    pem = os.environ.get("FEED_SIGNING_KEY")
    if not pem:
        print("FEED_SIGNING_KEY secret missing", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc).isoformat()
    html = fetch_text(PIB_ALLREL_URL)

    seen = set()
    items = []
    for m in ENTRY_RE.finditer(html):
        prid = m.group("prid")
        if prid in seen:
            continue
        seen.add(prid)
        title = m.group("title").strip()
        category = categorize(title)
        if category not in ("GST", "INCOME_TAX"):
            continue  # app scope: GST + Income Tax only

        detail_html = fetch_text(f"https://pib.gov.in/PressReleasePage.aspx?PRID={prid}")
        items.append({
            "id": f"pib-{prid}",
            "title": title,
            "sourceUrl": f"https://pib.gov.in/PressReleasePage.aspx?PRID={prid}",
            "category": category,
            "summary": "",
            "ministry": "PIB",
            "publishedAt": parse_date(detail_html, now),
        })
        time.sleep(1)  # be polite to PIB between detail fetches

    feed = {
        "generatedAt": now,
        "source": "PIB Allrel.aspx (official, English)",
        "announcements": items,
    }

    out_dir = os.path.dirname(os.path.abspath(__file__)) + "/.."
    json_path = os.path.join(out_dir, "announcements.json")
    sig_path = os.path.join(out_dir, "announcements.json.sig")

    payload = json.dumps(feed, ensure_ascii=False, indent=2).encode("utf-8")
    with open(json_path, "wb") as f:
        f.write(payload)

    priv = load_pem_private_key(pem.encode("utf-8"), password=None)
    with open(sig_path, "w") as f:
        f.write(base64.b64encode(priv.sign(payload)).decode("ascii"))

    print(f"wrote {len(items)} announcements (GST/Income-Tax) -> {json_path}")


if __name__ == "__main__":
    main()
