"""
Sends a daily email digest of new tender + signal items from data/feed.json.

Authentication is via SMTP env vars (set as GitHub Action secrets):
    SMTP_HOST       e.g. smtp.gmail.com
    SMTP_PORT       e.g. 587
    SMTP_USER       sending email address
    SMTP_PASSWORD   app password (for Gmail: create an App Password, not your login)
    SMTP_FROM       (optional) From: address, defaults to SMTP_USER
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED_PATH = ROOT / "data" / "feed.json"
CONFIG_PATH = ROOT / "data" / "config.json"


def fmt_cr(v):
    if not v:
        return "—"
    return f"₹{v:,.1f} Cr" if v < 10 else f"₹{v:,.0f} Cr"


def render_html(new_items, all_items, since_iso):
    tenders = [i for i in new_items if i.get("kind") == "tender"]
    signals = [i for i in new_items if i.get("kind") == "signal"]
    closing_soon = [
        i for i in all_items
        if i.get("kind") == "tender" and i.get("deadline")
        and 0 <= (datetime.strptime(i["deadline"], "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days <= 7
    ]
    closing_soon.sort(key=lambda i: i["deadline"])

    def row(i):
        link = i.get("source_url") or "#"
        meta_parts = []
        if i.get("capacity"):
            meta_parts.append(f"{i['capacity']} MWp")
        if i.get("value"):
            meta_parts.append(fmt_cr(i["value"]))
        if i.get("deadline"):
            meta_parts.append(f"deadline {i['deadline']}")
        meta = " · ".join(meta_parts) or "—"
        return (
            f'<tr style="border-bottom:1px solid #e5e7eb">'
            f'<td style="padding:10px 12px;vertical-align:top">'
            f'<div style="font-weight:600;color:#13294B"><a href="{link}" style="color:#13294B;text-decoration:none">{i.get("title","")}</a></div>'
            f'<div style="color:#5B6878;font-size:12px;margin-top:2px">{i.get("org","")} · {i.get("source","")} · {i.get("state","")}</div>'
            f'<div style="color:#8A94A6;font-size:12px;margin-top:2px">{meta}</div>'
            f"</td>"
            f'<td style="padding:10px 12px;vertical-align:top;text-align:right;font-family:monospace;color:#13294B">{i.get("priority","")}</td>'
            f"</tr>"
        )

    sections = []
    if tenders:
        sections.append(
            f'<h3 style="color:#13294B;margin:18px 0 8px">{len(tenders)} new tender(s)</h3>'
            f'<table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px">{"".join(row(i) for i in tenders)}</table>'
        )
    if signals:
        sections.append(
            f'<h3 style="color:#176B33;margin:18px 0 8px">{len(signals)} new market signal(s)</h3>'
            f'<table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px">{"".join(row(i) for i in signals)}</table>'
        )
    if closing_soon:
        sections.append(
            f'<h3 style="color:#D64545;margin:18px 0 8px">{len(closing_soon)} tender(s) closing within 7 days</h3>'
            f'<table style="width:100%;border-collapse:collapse;border:1px solid #e5e7eb;border-radius:8px">{"".join(row(i) for i in closing_soon)}</table>'
        )
    if not sections:
        sections.append('<p style="color:#5B6878">No new items since the last digest. Watching feeds.</p>')

    return f"""
    <html><body style="font-family:Calibri,Segoe UI,sans-serif;color:#16202E;background:#EEF1F5;padding:18px">
      <div style="max-width:720px;margin:0 auto;background:#fff;border-radius:10px;padding:22px;border:1px solid #DCE2EA">
        <div style="border-bottom:1px solid #DCE2EA;padding-bottom:12px;margin-bottom:8px">
          <div style="font-size:18px;font-weight:700;color:#13294B">B. U. Bhandari Energy — Opportunity Brief</div>
          <div style="font-size:12px;color:#8A94A6;letter-spacing:.08em;text-transform:uppercase">{datetime.now().strftime("%A, %d %b %Y")}</div>
        </div>
        {"".join(sections)}
        <p style="font-size:11px;color:#8A94A6;margin-top:22px">
          Sent since {since_iso}. Full dashboard: open <code>index.html</code>.
        </p>
      </div>
    </body></html>
    """


def main() -> int:
    if not FEED_PATH.exists():
        print("No feed.json found — nothing to digest.")
        return 0
    feed = json.loads(FEED_PATH.read_text(encoding="utf-8"))
    items = feed.get("items", [])

    since = datetime.now(timezone.utc) - timedelta(hours=26)
    new_items = [
        i for i in items
        if i.get("first_seen") and datetime.fromisoformat(i["first_seen"]).replace(tzinfo=timezone.utc) >= since
    ]

    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    recipients = config.get("email", {}).get("recipients", [])
    if not recipients:
        print("No recipients configured in data/config.json email.recipients")
        return 0

    if config.get("email", {}).get("send_only_if_new_items", True) and not new_items:
        # Still send if there are tenders closing in 7 days
        closing_soon = [
            i for i in items
            if i.get("kind") == "tender" and i.get("deadline")
            and 0 <= (datetime.strptime(i["deadline"], "%Y-%m-%d").date() - datetime.now(timezone.utc).date()).days <= 7
        ]
        if not closing_soon:
            print("No new items and nothing closing soon — skipping email.")
            return 0

    host = os.environ.get("SMTP_HOST")
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    pwd = os.environ.get("SMTP_PASSWORD")
    sender = os.environ.get("SMTP_FROM", user)

    if not all([host, user, pwd]):
        print("SMTP credentials not set — set SMTP_HOST, SMTP_USER, SMTP_PASSWORD as GitHub secrets.")
        return 1

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"BUB Energy — {len(new_items)} new opportunities ({datetime.now().strftime('%d %b')})"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)

    html = render_html(new_items, items, since.isoformat(timespec="minutes"))
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as server:
        server.starttls(context=ctx)
        server.login(user, pwd)
        server.sendmail(sender, recipients, msg.as_string())

    print(f"Sent digest to {len(recipients)} recipient(s) — {len(new_items)} new items.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
