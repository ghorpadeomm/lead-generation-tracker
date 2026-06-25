# BUB Energy — Opportunity Intelligence Command Center

A single-page dashboard that merges B. U. Bhandari Energy's **tender pipeline** and **market-signal intelligence** (industrial expansions, data centers, warehouses, renewable-energy announcements) into one priority-ranked feed.

Built as a **zero-dependency single HTML file** — no build step, no frameworks, no external requests. It runs anywhere, including offline and behind a corporate firewall.

## Live demo

After deploying (see below): `https://<your-username>.github.io/<repo-name>/`

## What's inside

- A unified, filterable feed of **tenders + market signals**, ranked together by a single 0–100 priority score
- Source spines (navy = tender, green = market signal) so provenance reads at a glance while everything sorts as one queue
- Live deadline countdowns with traffic-light urgency for tenders; detection recency for signals
- KPI readouts — open tenders, bids closing within 7 days, active signals, high-priority count, and addressable tender pipeline (₹ Cr)
- Right-rail analytics (signal mix, top states, tender urgency) that recompute as you filter
- An auto-generated **daily brief** that surfaces the most urgent bid and the hottest signal to action

## Deploy to GitHub Pages

1. Create a new **public** repository on GitHub (GitHub Pages is free on public repos; private repos need a paid plan).
2. Upload `index.html` (and this `README.md`) — use **Add file → Upload files**, drag them in, then **Commit changes**.
3. Open **Settings → Pages**, set **Source** to *Deploy from a branch*, choose **main / (root)**, and **Save**.
4. Wait about a minute. Your dashboard is live at the URL above.

## Connecting live data

The dashboard currently runs on sample data (the `DATA` array near the bottom of `index.html`). To make it live:

- Replace `DATA` with a `fetch()` to your ingestion API (`/api/ingest`), where the tender-alert scraper and the LinkedIn signal classifier write scored opportunities; **or**
- Point it at a Google Sheet (the Tender Tracker plus a signals tab) via a published CSV or Apps Script endpoint — a no-backend setup that works today.
- Swap the fixed `NOW` constant for `new Date()` so the deadline countdowns track real time.

## Tech

Vanilla HTML, CSS, and JavaScript. Inline SVG charts and brand glyph. No dependencies, no tracking, no network calls.

---

Part of the BUB Energy Growth Operating System — combines Tender Alert (Deliverable 3) and LinkedIn Opportunity Intelligence (Deliverable 4) into one interface.
