#!/usr/bin/env python3
"""
Official GoI compliance feed generator.

Fetches OFFICIAL Government of India press releases (PIB Allrel.aspx), filters to
GST + Income-Tax items, tags them, and emits a signed announcements.json.

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
import urllib.request
from datetime import datetime, timezone

from cryptography.hazmat.primitives.serialization import load_pem_private_key

PIB_ALLREL_URL = "https://www.pib.gov.in/Allrel.aspx"
ENTRY_RE = re.compile(
    r"<a[^>]*title=['\"](?P<title>[^'\"]+)['\"][^>]*href=['\"]/(?P<href>PressReleasePage\.aspx\?PRID=(?P<prid>\d+))['\"][^>]*>",
    re.IGNORECASE,
)

# Keyword tagging (English + Hindi). Official PIB releases are often bilingual.
GST_KEYWORDS = ["gst", "jeesetee", "cbic", "customs", "indirect tax"]
# (Hindi "जीएसटी" is matched via its latin transliteration fallback below)
INCOME_TAX_KEYWORDS = ["income tax", "cbdt", "itr", "direct tax", "26as", "tds", "advance tax"]
GST_HINDI = "जीएसटी"
IT_HINDI = ["आयकर", "सीबीडीटी"]


def categorize(text: str) -> str:
    t = text.lower()
    if GST_HINDI in text or any(k in t for k in GST_KEYWORDS):
        return "GST"
    if any(h in text for h in IT_HINDI) or any(k in t for k in INCOME_TAX_KEYWORDS):
        return "INCOME_TAX"
    return "GENERAL"


def fetch_html(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "GoI-Compliance-Feed/1.0 (+official PIB monitor)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_entries(html: str):
    seen = set()
    for m in ENTRY_RE.finditer(html):
        prid = m.group("prid")
        if prid in seen:
            continue
        seen.add(prid)
        title = m.group("title").strip()
        yield {
            "id": f"pib-{prid}",
            "title": title,
            "sourceUrl": f"https://pib.gov.in/PressReleasePage.aspx?PRID={prid}",
            "category": categorize(title),
            "summary": "",
            "ministry": "PIB",
        }


def main():
    pem = os.environ.get("FEED_SIGNING_KEY")
    if not pem:
        print("FEED_SIGNING_KEY secret missing", file=sys.stderr)
        sys.exit(1)

    html = fetch_html(PIB_ALLREL_URL)
    now = datetime.now(timezone.utc).isoformat()

    # Keep only GST + Income-Tax items (the app's scope); drop GENERAL noise for now.
    items = [e for e in parse_entries(html) if e["category"] in ("GST", "INCOME_TAX")]
    for e in items:
        e["publishedAt"] = now  # TODO: extract real publish date from PIB detail page.

    feed = {
        "generatedAt": now,
        "source": "PIB Allrel.aspx (official)",
        "announcements": items,
    }

    out_dir = os.path.dirname(os.path.abspath(__file__)) + "/.."
    json_path = os.path.join(out_dir, "announcements.json")
    sig_path = os.path.join(out_dir, "announcements.json.sig")

    # Deterministic formatting so bytes are stable.
    payload = json.dumps(feed, ensure_ascii=False, indent=2).encode("utf-8")
    with open(json_path, "wb") as f:
        f.write(payload)

    priv = load_pem_private_key(pem.encode("utf-8"), password=None)
    signature = priv.sign(payload)
    with open(sig_path, "w") as f:
        f.write(base64.b64encode(signature).decode("ascii"))

    print(f"wrote {len(items)} announcements (GST/Income-Tax) -> {json_path}")


if __name__ == "__main__":
    main()
