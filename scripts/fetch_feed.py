"""
Fetches solar EPC tender + LinkedIn/industrial signals from multiple sources
and writes them to data/feed.json, which the dashboard reads.

Each source is wrapped in try/except — one failing source will not kill the run.
Schema mirrors the original hardcoded DATA array in index.html.

Run locally:
    pip install -r scripts/requirements.txt
    python scripts/fetch_feed.py

In CI: see .github/workflows/fetch-feed.yml
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import feedparser
import requests
from bs4 import BeautifulSoup

# Windows consoles default to cp1252 and choke on characters like "→" in our
# log messages. Force UTF-8 so logging can never crash the run. (No-op on Linux/CI.)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
FEED_PATH = DATA_DIR / "feed.json"
CONFIG_PATH = DATA_DIR / "config.json"

UA = (
    "Mozilla/5.0 (compatible; BUBEnergyLeadBot/1.0; "
    "+https://github.com/ghorpadeomm/lead-generation-tracker)"
)
HEADERS = {"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"}
TIMEOUT = 25

STATE_KEYWORDS = {
    "Maharashtra": ["maharashtra", "mumbai", "pune", "nagpur", "msedcl", "mahagenco"],
    "Gujarat": ["gujarat", "ahmedabad", "surat", "guvnl", "geda", "gsecl"],
    "Tamil Nadu": ["tamil nadu", "chennai", "tangedco", "coimbatore"],
    "Karnataka": ["karnataka", "bangalore", "bengaluru", "bescom", "kptcl"],
    "Rajasthan": ["rajasthan", "jaipur", "jodhpur", "rrvunl", "rvunl"],
    "Madhya Pradesh": ["madhya pradesh", "bhopal", "indore", "mppmcl"],
    "Andhra Pradesh": ["andhra pradesh", "vizag", "apgenco", "apspdcl"],
    "Telangana": ["telangana", "hyderabad", "tssouthern", "tsgenco"],
    "Uttar Pradesh": ["uttar pradesh", "lucknow", "upneda", "upcl"],
    "Punjab": ["punjab", "pseb", "pspcl"],
    "Haryana": ["haryana", "gurgaon", "gurugram", "hpgcl"],
    "Kerala": ["kerala", "kochi", "kseb"],
    "Odisha": ["odisha", "orissa", "bhubaneswar", "gridco"],
    "West Bengal": ["west bengal", "kolkata", "wbsedcl"],
    "Chhattisgarh": ["chhattisgarh", "raipur", "cspdcl"],
    "Himachal Pradesh": ["himachal", "shimla", "hpseb"],
    "Jharkhand": ["jharkhand", "ranchi", "jbvnl"],
    "Bihar": ["bihar", "patna", "bsphcl"],
    "Assam": ["assam", "guwahati", "apdcl"],
    "Goa": ["goa", "panaji"],
}

SIGNAL_TYPE_KEYWORDS = {
    "Data Center": ["data center", "data centre", "datacenter"],
    "Semiconductor": ["semiconductor", "fab", "chip"],
    "New Plant": ["new plant", "greenfield", "new facility", "new factory"],
    "Capacity Expansion": ["expansion", "capacity addition", "ramp up"],
    "Warehouse / Logistics": ["warehouse", "fulfilment", "fulfillment", "logistics park"],
    "Renewable Commitment": ["renewable commitment", "rE100", "carbon neutral", "net zero"],
    "EPC Requirement": ["epc requirement", "looking for epc", "epc partner", "epc contractor"],
}


# --------------------------- utilities ---------------------------

def log(msg: str) -> None:
    print(f"[fetch_feed] {msg}", flush=True)


def fetch(url: str) -> requests.Response | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code >= 400:
            log(f"  HTTP {r.status_code} from {url}")
            return None
        return r
    except Exception as e:
        log(f"  request failed for {url}: {e}")
        return None


def sha8(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:8]


def detect_state(text: str) -> str:
    t = text.lower()
    for state, kws in STATE_KEYWORDS.items():
        if any(k in t for k in kws):
            return state
    return "Pan-India"


def detect_sigtype(text: str) -> str:
    t = text.lower()
    for label, kws in SIGNAL_TYPE_KEYWORDS.items():
        if any(k in t for k in kws):
            return label
    return "Market Signal"


def parse_capacity_mw(text: str) -> float | None:
    """Extract a MW/MWp/kWp capacity figure from free text."""
    m = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(mw|mwp|kw|kwp)\b", text, re.IGNORECASE)
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower()
    if unit.startswith("kw"):
        val /= 1000.0
    return round(val, 2) if val > 0 else None


def parse_value_cr(text: str) -> float | None:
    """Extract a value in crores. Handles '₹100 crore', 'Rs 50 Cr', '$100 million' (→ ~830 Cr)."""
    t = text.replace(",", " ")
    m = re.search(r"(?:₹|rs\.?|inr)\s*([\d.]+)\s*(crore|cr|lakh|lakhs)", t, re.IGNORECASE)
    if m:
        v = float(m.group(1))
        return v / 100.0 if "lakh" in m.group(2).lower() else v
    m = re.search(r"\$\s*([\d.]+)\s*(million|mn|billion|bn)", t, re.IGNORECASE)
    if m:
        v = float(m.group(1))
        usd = v * 1000 if m.group(2).lower().startswith("b") else v
        return round(usd * 0.83, 1)  # USD→INR ~83, million → crore
    return None


def parse_deadline(text: str) -> str | None:
    """Return the LATEST plausible date in the text as YYYY-MM-DD.

    Tender rows usually carry an issue date AND a (later) submission/closing date,
    e.g. "29/05/2026 | 10/07/2026". We want the closing date — the latest one —
    while ignoring absurd far-future dates (e.g. 25-year PPA terms)."""
    patterns = [
        (r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b", "%d-%m-%Y"),
        (r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s+(20\d{2})\b", "%d-%b-%Y"),
        (r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", "%Y-%m-%d"),
    ]
    today = datetime.now(timezone.utc).date()
    lo = today.replace(year=today.year - 1)
    hi = today.replace(year=today.year + 2)
    found = []
    for pat, fmt in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            try:
                d = datetime.strptime("-".join(m.groups()).title(), fmt).date()
            except ValueError:
                continue
            if lo <= d <= hi:
                found.append(d)
    return max(found).strftime("%Y-%m-%d") if found else None


def best_title(cells: list[str]) -> str:
    """Pick the most descriptive cell from a tender row.

    Tender tables put a short reference number first and the real project
    description in a longer cell. Prefer the longest cell that mentions the
    project scope; fall back to the longest cell overall.
    """
    candidates = [c for c in cells if len(c) > 15]
    if not candidates:
        return (cells[0] if cells else "Untitled tender")[:140]
    scoped = [c for c in candidates if re.search(r"\b(solar|rooftop|mw|mwp|epc|pv|bess)\b", c, re.IGNORECASE)]
    return max(scoped or candidates, key=len)[:140]


# --------------------------- scoring ---------------------------

def score_item(item: dict[str, Any], rules: dict[str, Any]) -> int:
    if item["kind"] == "tender":
        score = rules.get("tender_base", 50)
        if item.get("capacity"):
            score += item["capacity"] * rules.get("tender_capacity_bonus_per_mw", 0.05)
        if item.get("deadline"):
            days = (datetime.strptime(item["deadline"], "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days
            if 0 <= days <= 7:
                score += rules.get("tender_deadline_under_7d_bonus", 25)
            elif days <= 15:
                score += rules.get("tender_deadline_under_15d_bonus", 12)
    else:
        score = rules.get("signal_base", 60)
        text = (item.get("title", "") + " " + item.get("note", "")).lower()
        for kw, bonus in rules.get("signal_keyword_bonuses", {}).items():
            if kw.lower() in text:
                score += bonus
    return max(0, min(100, int(round(score))))


# --------------------------- sources ---------------------------

def from_rss(feed: dict[str, Any]) -> list[dict[str, Any]]:
    """Generic RSS reader. Works for Google Alerts, tender-aggregator feeds, and
    email-to-RSS bridges (e.g. Kill-the-Newsletter for BidAssist / TenderTiger alerts).
    The displayed source comes from the feed's optional 'source_label'."""
    url = feed.get("url", "")
    if not url or "PASTE" in url:
        log(f"  skipping '{feed['name']}' — no RSS URL configured")
        return []
    log(f"  RSS: {feed['name']}")
    parsed = feedparser.parse(url)
    items = []
    for entry in parsed.entries[:60]:
        raw_title = re.sub(r"<[^>]+>", "", entry.get("title", "")).strip()
        summary = re.sub(r"<[^>]+>", "", entry.get("summary", "")).strip()
        link = entry.get("link", "")
        if not raw_title:
            continue
        published = entry.get("published_parsed") or entry.get("updated_parsed")
        detected = (
            datetime(*published[:6]).strftime("%Y-%m-%d")
            if published
            else datetime.now(timezone.utc).strftime("%Y-%m-%d")
        )
        text = raw_title + " " + summary
        if "linkedin.com" in link:
            src = "LinkedIn"
        else:
            src = feed.get("source_label") or "Google Alerts"
        item = {
            "id": f"RSS-{sha8(link or raw_title)}",
            "kind": feed.get("kind", "signal"),
            "title": raw_title[:140],
            "org": _guess_org(raw_title, summary),
            "source": src,
            "source_url": link,
            "state": detect_state(text),
            "value": parse_value_cr(text),
            "capacity": parse_capacity_mw(text),
            "deadline": parse_deadline(text) if feed.get("kind") == "tender" else None,
            "detected": detected,
            "owner": "Unassigned",
            "note": summary[:280] or raw_title,
        }
        if feed.get("kind") == "signal":
            item["sigtype"] = detect_sigtype(text)
        items.append(item)
    log(f"    → {len(items)} items")
    return items


def _guess_org(title: str, summary: str) -> str:
    # First non-trivial chunk before " - " or " | " in alerts titles is usually the source/publisher,
    # not the org. Better heuristic: look at summary's first sentence.
    first = summary.split(".")[0] if summary else title
    # Common org patterns: "Acme Industries announced...", "...by Acme Ltd"
    m = re.search(r"\b([A-Z][a-zA-Z&.\- ]{2,40}(?: Ltd| Limited| Inc| Corp| Industries| Energy| Power| Solar| Group| Pvt))\b", first)
    if m:
        return m.group(1).strip()
    return title.split(" - ")[0].split(" | ")[0][:60]


def from_seci(url: str) -> list[dict[str, Any]]:
    log(f"  SECI: {url}")
    r = fetch(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    for row in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        text = " | ".join(cells)
        if "solar" not in text.lower() and "rooftop" not in text.lower() and "epc" not in text.lower():
            continue
        title = best_title(cells)
        link_el = row.find("a", href=True)
        link = urljoin(url, link_el["href"]) if link_el else url
        items.append({
            "id": f"SECI-{sha8(link if link != url else title)}",
            "kind": "tender",
            "title": title,
            "org": "SECI",
            "source": "SECI Portal",
            "source_url": link,
            "state": detect_state(text),
            "value": parse_value_cr(text),
            "capacity": parse_capacity_mw(text),
            "deadline": parse_deadline(text),
            "detected": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "owner": "Unassigned",
            "note": text[:280],
        })
    log(f"    → {len(items)} items")
    return items


def from_ntpc(url: str) -> list[dict[str, Any]]:
    log(f"  NTPC: {url}")
    r = fetch(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    for row in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 3:
            continue
        text = " | ".join(cells)
        if "solar" not in text.lower():
            continue
        title = best_title(cells)
        link_el = row.find("a", href=True)
        link = urljoin(url, link_el["href"]) if link_el else url
        items.append({
            "id": f"NTPC-{sha8(link if link != url else title)}",
            "kind": "tender",
            "title": title,
            "org": "NTPC Ltd",
            "source": "NTPC Portal",
            "source_url": link,
            "state": detect_state(text),
            "value": parse_value_cr(text),
            "capacity": parse_capacity_mw(text),
            "deadline": parse_deadline(text),
            "detected": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "owner": "Unassigned",
            "note": text[:280],
        })
    log(f"    → {len(items)} items")
    return items


def from_cppp(url: str) -> list[dict[str, Any]]:
    """CPPP eProcure has anti-bot protections; this is a best-effort fetch."""
    log(f"  CPPP: {url}")
    r = fetch(url)
    if not r:
        return []
    soup = BeautifulSoup(r.text, "lxml")
    items = []
    for row in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 4:
            continue
        text = " | ".join(cells)
        if "solar" not in text.lower():
            continue
        title = best_title(cells)
        link_el = row.find("a", href=True)
        link = urljoin(url, link_el["href"]) if link_el else url
        items.append({
            "id": f"CPPP-{sha8(link if link != url else title)}",
            "kind": "tender",
            "title": title,
            "org": "Central Govt (CPPP)",
            "source": "CPPP / eProcure",
            "source_url": link,
            "state": detect_state(text),
            "value": parse_value_cr(text),
            "capacity": parse_capacity_mw(text),
            "deadline": parse_deadline(text),
            "detected": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "owner": "Unassigned",
            "note": text[:280],
        })
    log(f"    → {len(items)} items")
    return items


# --------------------------- merge ---------------------------

def merge_with_existing(new_items: list[dict[str, Any]]) -> dict[str, Any]:
    """Preserve first_seen, owner, and any manual edits on items that still exist."""
    existing: dict[str, dict[str, Any]] = {}
    manual_items: list[dict[str, Any]] = []
    if FEED_PATH.exists():
        try:
            prior = json.loads(FEED_PATH.read_text(encoding="utf-8"))
            for it in prior.get("items", []):
                existing[it["id"]] = it
                if it.get("source") == "Manual / LinkedIn":
                    manual_items.append(it)
        except Exception as e:
            log(f"  could not parse existing feed.json: {e}")

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    merged_by_id: dict[str, dict[str, Any]] = {}

    for it in new_items:
        prior = existing.get(it["id"])
        if prior:
            it["first_seen"] = prior.get("first_seen", now_iso)
            # preserve human edits
            for field in ("owner", "note", "value", "capacity", "deadline", "state"):
                if prior.get(f"_pin_{field}"):
                    it[field] = prior[field]
                    it[f"_pin_{field}"] = True
        else:
            it["first_seen"] = now_iso
        merged_by_id[it["id"]] = it

    # keep manual items that the scraper would not produce
    for m in manual_items:
        if m["id"] not in merged_by_id:
            merged_by_id[m["id"]] = m

    return {"updated_at": now_iso, "items": list(merged_by_id.values())}


# --------------------------- main ---------------------------

def main() -> int:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    rules = config.get("priority_rules", {})

    collected: list[dict[str, Any]] = []

    rss_feeds = config.get("rss_feeds", config.get("google_alerts_feeds", []))
    for feed in rss_feeds:
        try:
            collected.extend(from_rss(feed))
        except Exception:
            log(f"  RSS source '{feed.get('name')}' failed:\n{traceback.format_exc()}")

    scrapers = config.get("tender_scrapers", {})
    if scrapers.get("seci", {}).get("enabled"):
        try:
            collected.extend(from_seci(scrapers["seci"]["url"]))
        except Exception:
            log(f"  SECI scraper failed:\n{traceback.format_exc()}")
    if scrapers.get("ntpc", {}).get("enabled"):
        try:
            collected.extend(from_ntpc(scrapers["ntpc"]["url"]))
        except Exception:
            log(f"  NTPC scraper failed:\n{traceback.format_exc()}")
    if scrapers.get("cppp", {}).get("enabled"):
        try:
            collected.extend(from_cppp(scrapers["cppp"]["url"]))
        except Exception:
            log(f"  CPPP scraper failed:\n{traceback.format_exc()}")

    for it in collected:
        it["priority"] = score_item(it, rules)

    feed = merge_with_existing(collected)
    feed["items"].sort(key=lambda x: (x.get("priority", 0)), reverse=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FEED_PATH.write_text(json.dumps(feed, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Wrote {len(feed['items'])} items to {FEED_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
