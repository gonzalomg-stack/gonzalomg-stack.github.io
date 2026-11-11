#!/usr/bin/env python3
"""
DataPilot — daily aviation news aggregator.

Reads a list of public RSS/Atom feeds, cleans and classifies every item,
merges it with the existing archive and writes news.json, which the
website reads on load. Standard library only: no pip install needed.

Run locally:   python fetch_news.py
Run in CI:     see .github/workflows/update-news.yml
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha1
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_FILE = Path(__file__).resolve().parent / "news.json"

# ── Sources ────────────────────────────────────────────────────────────────
# Add or remove feeds here. A feed that fails is skipped, never fatal.
#   max       newest N items taken from that feed per run
#   google    True for Google News searches: the publisher becomes the source
#             and the title suffix " - Publisher" is removed
def gnews(query: str, lang: str = "en", region: str = "GB") -> str:
    from urllib.parse import quote
    return (f"https://news.google.com/rss/search?q={quote(query + ' when:2d')}"
            f"&hl={lang}-{region}&gl={region}&ceid={region}:{lang}")

FEEDS = [
    # Direct publisher feeds
    {"source": "AeroTime",       "url": "https://www.aerotime.aero/feed",            "lang": "en", "max": 15},
    {"source": "Simple Flying",  "url": "https://simpleflying.com/feed/",            "lang": "en", "max": 10},
    {"source": "AeroRoutes",     "url": "https://www.aeroroutes.com/eng?format=rss", "lang": "en", "max": 6},
    {"source": "Aviacionline",   "url": "https://www.aviacionline.com/feed/",        "lang": "es", "max": 8},
    {"source": "Int. Airport Review", "url": "https://www.internationalairportreview.com/feed/", "lang": "en", "max": 8},

    # Google News topic searches (fill the gaps the direct feeds leave)
    {"url": gnews('EUROCONTROL OR "air traffic control" OR airspace Europe'), "lang": "en", "max": 10, "google": True},
    {"url": gnews('EASA OR ICAO OR "aviation regulator"'),                   "lang": "en", "max": 8,  "google": True},
    {"url": gnews('aviation incident OR "emergency landing" OR NTSB OR BEA'), "lang": "en", "max": 8,  "google": True},
    {"url": gnews('"sustainable aviation fuel" OR SAF airline emissions'),    "lang": "en", "max": 6,  "google": True},
    {"url": gnews('Airbus OR Boeing deliveries OR orders'),                  "lang": "en", "max": 8,  "google": True},
    {"url": gnews('Aena aeropuerto OR aerolínea OR Iberia OR Vueling OR Enaire', "es", "ES"), "lang": "es", "max": 10, "google": True},
]

MAX_PER_FEED = 15          # default when a feed sets no "max"
KEEP_DAYS = 14             # archive window
MAX_ITEMS = 250            # hard cap on the archive
SUMMARY_CHARS = 280
TIMEOUT = 15
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# ── Classification ─────────────────────────────────────────────────────────
# First matching category wins, so order matters (most specific first).
CATEGORIES = [
    ("Safety", [
        "incident", "accident", "crash", "emergency", "diverted", "diversion", "evacuat",
        "turbulence", "bird strike", "rejected takeoff", "go-around", "runway excursion",
        "ntsb", "bea ", "ciaiac", "aaib", "investigation", "mayday", "smoke", "engine failure",
        "incidente", "accidente", "emergencia",
    ]),
    ("ATM & Airspace", [
        "eurocontrol", "air traffic control", "atc", "atfm", "airspace", "nats", "enaire",
        "dfs ", "skyguide", "dsna", "faa", "slot", "delay", "punctuality", "strike",
        "control aéreo", "controladores", "espacio aéreo", "retrasos", "huelga",
    ]),
    ("Sustainability", [
        "saf", "sustainable aviation fuel", "emission", "co2", "carbon", "net zero", "net-zero",
        "hydrogen", "electric aircraft", "evtol", "noise", "climate", "corsia", "eu ets",
        "sostenible", "emisiones", "hidrógeno",
    ]),
    ("Regulation", [
        "easa", "icao", "iata", "regulation", "regulator", "certification", "certified",
        "type certificate", "airworthiness", "directive", "ministry", "government", "tariff",
        "law", "ruling", "court", "aesa", "normativa", "certificación",
    ]),
    ("Airports", [
        "airport", "terminal", "runway", "aena", "heathrow", "barajas", "schiphol", "gatwick",
        "passenger traffic", "hub", "aeropuerto", "pasajeros",
    ]),
    ("Manufacturers", [
        "airbus", "boeing", "embraer", "comac", "atr ", "bombardier", "rolls-royce", "pratt",
        "cfm", "ge aerospace", "safran", "delivery", "deliveries", "order", "a320", "a321",
        "a350", "a330", "737", "787", "777", "e2", "backlog", "fábrica", "pedido",
    ]),
    ("Routes", [
        "route", "new service", "launch", "frequenc", "nonstop", "non-stop", "schedule",
        "seasonal", "ruta", "nueva conexión", "vuelos directos",
    ]),
    ("Airlines", [
        "airline", "airways", "air lines", "carrier", "fleet", "lcc", "low-cost", "ryanair",
        "iberia", "vueling", "lufthansa", "easyjet", "wizz", "air france", "klm", "iag",
        "earnings", "profit", "revenue", "aerolínea",
    ]),
]
DEFAULT_CATEGORY = "Industry"

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    text = html.unescape(TAG_RE.sub(" ", raw))
    text = WS_RE.sub(" ", text).strip()
    # Strip common feed boilerplate ("The post X appeared first on Y.")
    text = re.sub(r"The post .*? appeared first on .*?\.?$", "", text).strip()
    text = re.sub(r"\[(…|\.\.\.)\]$", "…", text).strip()
    return text


def truncate(text: str, limit: int = SUMMARY_CHARS) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(",.;:—-")
    return cut + "…"


def parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = parsedate_to_datetime(raw)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))  # ISO 8601 (Atom)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def classify(title: str, summary: str, source: str) -> str:
    if source == "The Aviation Herald":
        return "Safety"
    if source == "AeroRoutes":
        return "Routes"
    hay = f" {title} {summary} ".lower()
    for name, pattern in _CATEGORY_PATTERNS:
        if pattern.search(hay):
            return name
    return DEFAULT_CATEGORY


def _keyword_pattern(words: list[str]) -> re.Pattern:
    # Leading word boundary always; trailing one for short words, so "saf" never
    # matches "safety"/"safran" while "evacuat" still matches "evacuated".
    parts = []
    for w in words:
        w = w.strip()
        parts.append(r"\b" + re.escape(w) + (r"\b" if len(w) <= 4 else ""))
    return re.compile("|".join(parts))


_CATEGORY_PATTERNS = [(name, _keyword_pattern(words)) for name, words in CATEGORIES]


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.read()


def parse_feed(data: bytes, feed: dict) -> list[dict]:
    root = ET.fromstring(data)
    items = []
    limit = feed.get("max", MAX_PER_FEED)

    rss_items = root.findall(".//item")
    if rss_items:
        for it in rss_items[:limit]:
            title = clean_text(it.findtext("title"))
            link = (it.findtext("link") or "").strip()
            desc = it.findtext("description") or it.findtext("content:encoded", namespaces=NS)
            date = parse_date(it.findtext("pubDate") or it.findtext("dc:date", namespaces=NS))
            publisher = clean_text(it.findtext("source"))
            items.append((title, link, desc, date, publisher))
    else:  # Atom
        for it in root.findall("atom:entry", NS)[:limit]:
            title = clean_text(it.findtext("atom:title", namespaces=NS))
            link_el = it.find("atom:link[@rel='alternate']", NS)
            if link_el is None:  # Elements without children are falsy, so no `or`
                link_el = it.find("atom:link", NS)
            link = link_el.get("href", "").strip() if link_el is not None else ""
            desc = it.findtext("atom:summary", namespaces=NS) or it.findtext("atom:content", namespaces=NS)
            date = parse_date(it.findtext("atom:published", namespaces=NS) or it.findtext("atom:updated", namespaces=NS))
            items.append((title, link, desc, date, ""))

    out = []
    for title, link, desc, date, publisher in items:
        if not title or not link.startswith("http"):
            continue
        source = feed.get("source", "")
        if feed.get("google"):
            # Google News: "Headline - Publisher"; its description only repeats the headline.
            source = publisher or (title.rsplit(" - ", 1)[1] if " - " in title else "Google News")
            if title.endswith(" - " + source):
                title = title[: -len(" - " + source)].strip()
            summary = ""
        else:
            summary = truncate(clean_text(desc))
            if summary.lower().startswith(title.lower()[:40]):
                summary = truncate(summary[len(title):].lstrip(" :.-—"))
        out.append({
            "id": sha1(link.encode()).hexdigest()[:12],
            "title": title,
            "summary": summary,
            "url": link,
            "source": source,
            "lang": feed["lang"],
            "category": classify(title, summary, source),
            "published": (date or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return out


def label(feed: dict) -> str:
    if feed.get("google"):
        from urllib.parse import urlparse, parse_qs, unquote
        q = parse_qs(urlparse(feed["url"]).query).get("q", [""])[0]
        return "Google News: " + unquote(q).replace(" when:2d", "")[:26]
    return feed["source"]


def normalise_title(t: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñ ]", "", t.lower())[:80]


def main() -> int:
    now = datetime.now(timezone.utc)

    existing = []
    if OUT_FILE.exists():
        try:
            prev = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            # Seed items (preview placeholders) are dropped on the first real run.
            existing = [i for i in prev.get("items", []) if not prev.get("seed")]
        except (json.JSONDecodeError, OSError):
            existing = []

    fresh, report = [], []
    for feed in FEEDS:
        try:
            got = parse_feed(fetch(feed["url"]), feed)
            fresh.extend(got)
            report.append(f"  ok   {label(feed):<40} {len(got):>3} items")
        except Exception as exc:  # noqa: BLE001 — one bad feed must never break the run
            report.append(f"  FAIL {label(feed):<40} {type(exc).__name__}: {exc}"[:160])

    # Merge: fresh items win, dedupe by URL hash and by near-identical title.
    merged, seen_ids, seen_titles = [], set(), set()
    for item in sorted(fresh + existing, key=lambda i: i["published"], reverse=True):
        nt = normalise_title(item["title"])
        if item["id"] in seen_ids or nt in seen_titles:
            continue
        seen_ids.add(item["id"])
        seen_titles.add(nt)
        merged.append(item)

    cutoff = (now - timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    future = (now + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M:%SZ")
    merged = [i for i in merged if cutoff <= i["published"] <= future][:MAX_ITEMS]

    if not fresh and existing:
        print("No feed returned items; keeping the previous archive untouched.")
        print("\n".join(report))
        return 0

    payload = {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "count": len(merged),
        "sources": sorted({i["source"] for i in merged}),
        "items": merged,
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"news.json → {len(merged)} items ({len(fresh)} fetched this run)")
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
