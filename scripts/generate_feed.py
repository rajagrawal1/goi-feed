#!/usr/bin/env python3
"""
Income Tax Department compliance feed generator.

Fetches the OFFICIAL Income Tax Department "Latest News" RSS feed
(incometax.gov.in), which is income-tax-only by definition (CBDT notifications,
ITR-utility rollouts, TDS/exemption notices, e-filing updates). Each run appends
new items to the immutable archive by stable id and emits a signed
announcements.json.

Signing: Ed25519 detached signature over the exact UTF-8 bytes of announcements.json,
base64-encoded into announcements.json.sig. The private key never leaves the GitHub
Action secret; only the public key (ed25519_pub.pem) is public. A consuming client
embeds the public key and refuses any feed whose signature does not verify.

No third-party content, no LLM, no server we run.
"""
import base64
import html as _html
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from cryptography.hazmat.primitives.serialization import load_pem_private_key

RSS_URL = "https://www.incometax.gov.in/iec/foportal/rss.xml"

_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
_DESC_RE = re.compile(r"field--name-field-news-description[^>]*>(.*?)</div>", re.S)
_LINK_RE = re.compile(r'<a\s+href="([^"]+)"', re.S)
_TAG = re.compile(r"<[^>]+>")


def _pick(pattern, text, flags=0):
    m = re.search(pattern, text, flags)
    return m.group(1) if m else None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_text(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "GoI-Compliance-Feed/1.0 (+official Income Tax Department monitor)"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_feed(rss_text: str) -> list:
    out = []
    seen = set()
    for m in _ITEM_RE.finditer(rss_text):
        b = m.group(1)
        link = _pick(r"<link>(.*?)</link>", b) or ""
        nid = link.rstrip("/").rsplit("/", 1)[-1]
        if not nid or nid in seen:
            continue
        seen.add(nid)

        pub = _pick(r"<pubDate>(.*?)</pubDate>", b)
        try:
            published = parsedate_to_datetime(pub).astimezone(timezone.utc).isoformat()
        except Exception:
            published = _now()

        desc = _html.unescape(_pick(r"<description>(.*?)</description>", b, re.S) or "")
        dm = _DESC_RE.search(desc)
        if not dm:
            continue  # only published news (drops internal CMS nodes / bare form refs)
        text = re.sub(r"\s+", " ", _html.unescape(_TAG.sub("", dm.group(1)))).strip()
        if not text:
            continue

        pdf = None
        lm = _LINK_RE.search(dm.group(1))
        if lm:
            pdf = _html.unescape(lm.group(1))

        out.append({
            "id": f"itd-{nid}",
            "title": text,
            "sourceUrl": pdf or link,
            "category": "INCOME_TAX",
            "summary": text,
            "ministry": "Income Tax Department",
            "publishedAt": published,
        })
    return out


def load_existing(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return {it["id"]: it for it in json.load(f).get("announcements", [])}
    except Exception:
        return {}


def merge(existing: dict, new_items: list) -> dict:
    for it in new_items:
        old = existing.get(it["id"])
        if old:
            it["publishedAt"] = old.get("publishedAt") or it.get("publishedAt")
            it["summary"] = old.get("summary") or it.get("summary", "") or ""
        existing[it["id"]] = it
    return existing


def main():
    pem = os.environ.get("FEED_SIGNING_KEY")
    if not pem:
        print("FEED_SIGNING_KEY secret missing", file=sys.stderr)
        sys.exit(1)

    now = _now()
    items = parse_feed(fetch_text(RSS_URL))

    out_dir = os.path.dirname(os.path.abspath(__file__)) + "/.."
    json_path = os.path.join(out_dir, "announcements.json")
    sig_path = os.path.join(out_dir, "announcements.json.sig")

    merged = merge(load_existing(json_path), items)
    ordered = sorted(merged.values(), key=lambda x: x.get("publishedAt", ""), reverse=True)

    feed = {
        "generatedAt": now,
        "source": "Income Tax Department (incometax.gov.in/rss.xml)",
        "announcements": ordered,
    }

    payload = json.dumps(feed, ensure_ascii=False, indent=2).encode("utf-8")
    with open(json_path, "wb") as f:
        f.write(payload)

    priv = load_pem_private_key(pem.encode("utf-8"), password=None)
    with open(sig_path, "w") as f:
        f.write(base64.b64encode(priv.sign(payload)).decode("ascii"))

    print(f"feed now holds {len(ordered)} announcements ({len(items)} new this run) -> {json_path}")


if __name__ == "__main__":
    main()
