# BUB Energy — Opportunity Intelligence Command Center

A single-page dashboard that merges B. U. Bhandari Energy's **tender pipeline** and **market-signal intelligence** (LinkedIn EPC requirements, industrial expansions, data centers, warehouses, renewable-energy announcements) into one priority-ranked feed.

The dashboard itself is a **zero-dependency HTML file**. It reads its data from `data/feed.json`, which a small Python scraper refreshes **automatically every hour** via GitHub Actions.

## Live demo

After deploying (see below): `https://<your-username>.github.io/<repo-name>/`

## What's inside

- A unified, filterable feed of **tenders + market signals**, ranked together by a single 0–100 priority score
- **Auto-refresh** — the dashboard re-reads `data/feed.json` on load and every 30 minutes while open
- **NEW badges** on items first seen in the last 48 hours (or since your last visit)
- **Browser notifications** (opt-in) for new opportunities while the tab is open
- **"Add LinkedIn lead"** button — paste a post URL + notes for any opportunity you spot yourself; saved in your browser
- Live deadline countdowns with traffic-light urgency for tenders; detection recency for signals
- KPI readouts — open tenders, bids closing within 7 days, active signals, high-priority count, addressable pipeline (₹ Cr)
- Right-rail analytics (signal mix, top states, tender urgency) that recompute as you filter
- An auto-generated **daily brief**, plus an optional **daily email digest**

## How it works

```
                 ┌──────────────────────────────┐
  Hourly (cron)  │  GitHub Action: fetch-feed   │
  ───────────▶   │  runs scripts/fetch_feed.py  │
                 └──────────────┬───────────────┘
                                │ writes + commits
                                ▼
   SECI / NTPC / CPPP   ┌──────────────────┐      ┌───────────────────┐
   tender portals  ───▶ │  data/feed.json  │ ◀─── │  Google Alerts RSS │
                        └────────┬─────────┘      │  (incl. LinkedIn)  │
                                 │ fetch()         └───────────────────┘
                                 ▼
                          index.html (dashboard)
```

- **Tenders** come from scraping SECI, NTPC and the central CPPP portal, plus any tender-flagged Google Alerts feeds.
- **LinkedIn / market signals** come from Google Alerts RSS feeds (LinkedIn blocks direct scraping, so we use Google's index of public posts) and from leads you add manually.
- Everything is normalized, scored, and written to `data/feed.json`. The dashboard just reads that file.

## One-time setup

### 1. Create the Google Alerts feeds (5 min, this is what powers the auto-monitoring)

1. Go to [google.com/alerts](https://www.google.com/alerts) (signed in with any Google account).
2. Create these alerts. For each, click **Show options → Deliver to → RSS feed**:
   - `solar EPC tender India OR "turnkey solar" India`
   - `site:linkedin.com ("solar EPC" OR "EPC contractor" OR "turnkey solar") India`
   - `India ("new plant" OR "capacity expansion" OR "greenfield" OR "data center") investment crore`
3. After creating each, click the **RSS** icon next to it and copy the feed URL.
4. Paste each URL into the matching slot in [`data/config.json`](data/config.json) (replace `PASTE_GOOGLE_ALERTS_RSS_URL_HERE`). Commit the change.

> Until you add real RSS URLs, those feeds are skipped — the tender-portal scrapers still run.

### 2. Turn on the hourly scraper

The workflow in `.github/workflows/fetch-feed.yml` runs automatically once pushed. To confirm:

1. Push this repo to GitHub.
2. Open the **Actions** tab → enable workflows if prompted.
3. Open **Fetch tender + signal feed** → **Run workflow** to trigger the first run immediately (otherwise it runs at the top of the next hour).
4. It commits an updated `data/feed.json`. The dashboard picks it up on next load.

### 3. (Optional) Daily email digest

1. In your repo: **Settings → Secrets and variables → Actions → New repository secret**. Add:
   | Secret | Value |
   |---|---|
   | `SMTP_HOST` | e.g. `smtp.gmail.com` |
   | `SMTP_PORT` | `587` |
   | `SMTP_USER` | your sending email |
   | `SMTP_PASSWORD` | an **App Password** (Gmail: Account → Security → App Passwords — *not* your login password) |
2. Edit `data/config.json → email.recipients` with who should receive it.
3. `daily-email.yml` sends a summary every morning (08:30 IST). Trigger a test run from the **Actions** tab.

## Deploy the dashboard to GitHub Pages

1. **Settings → Pages**, set **Source** to *Deploy from a branch*, choose **main / (root)**, **Save**.
2. Wait ~1 minute — your dashboard is live at the URL at the top.

> **Private repos:** GitHub Pages on a private repo needs a paid plan (Pro/Team). If you're on the free plan, either make the repo public or just run it locally (below).

## Run it locally

Because the dashboard fetches `data/feed.json`, open it through a tiny web server, not by double-clicking the file:

```bash
# from the project folder
py -m http.server 4178        # Windows (py launcher)
# or:  python3 -m http.server 4178
```

Then open <http://localhost:4178>. (Opening `index.html` directly still works — it falls back to bundled sample data.)

## Run the scraper by hand

```bash
py -m pip install -r scripts/requirements.txt
py scripts/fetch_feed.py        # rewrites data/feed.json
```

## Tuning

Everything tunable lives in [`data/config.json`](data/config.json):
- `google_alerts_feeds` — your RSS URLs and whether each is a tender or signal
- `tender_scrapers` — enable/disable SECI, NTPC, CPPP and change their URLs
- `priority_rules` — how items are scored (deadline urgency, capacity, keyword bonuses)
- `email.recipients` — digest recipients

## Honest limitations

- **LinkedIn can't be scraped directly** — it blocks bots and bans accounts. We rely on Google's index of *public* LinkedIn posts via Alerts, plus manual entry. Private/connection-only posts won't appear.
- **Scrapers are fragile** — when a tender portal changes its HTML, that source may return nothing until the selector in `scripts/fetch_feed.py` is updated. Each source is isolated in try/except so one breaking won't stop the others.
- **Browser notifications** fire only while the dashboard tab is open. True background push needs a push service (future enhancement).

## Tech

Dashboard: vanilla HTML/CSS/JS, inline SVG charts, no dependencies. Scraper: Python (`requests`, `beautifulsoup4`, `feedparser`). Automation: GitHub Actions.

---

Part of the BUB Energy Growth Operating System — combines Tender Alert and LinkedIn Opportunity Intelligence into one interface.
