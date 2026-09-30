#!/usr/bin/env python3
"""Daily Morning News Brief for Ajay (10:00 AM IST).
Fetches headlines from verified Indian RSS feeds and dispatches a clean
digest directly to Telegram.
"""
import os
import sys
import html
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# IST Timezone (UTC + 5:30)
IST = timezone(timedelta(hours=5, minutes=30))

FEEDS = {
    "🇮🇳 Top Headlines": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
    "📍 Uttar Pradesh": "https://news.google.com/rss/search?q=Uttar+Pradesh&hl=en-IN&gl=IN&ceid=IN:en",
    "🌾 Punjab": "https://news.google.com/rss/search?q=Punjab+India&hl=en-IN&gl=IN&ceid=IN:en",
    "📈 Markets & Economy": "https://www.moneycontrol.com/rss/latestnews.xml"
}


def fetch_feed(url, max_items=3):
    try:
        import feedparser
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            feed = feedparser.parse(resp.read())
            items = []
            for entry in feed.entries[:max_items]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if title:
                    items.append({"title": title, "link": link})
            return items
    except Exception as e:
        print(f"Warning: Failed to fetch {url}: {e}", file=sys.stderr)
        return []


def generate_digest():
    now_ist = datetime.now(IST)
    date_str = now_ist.strftime("%d %b %Y")
    
    lines = [
        f"📰 <b>Daily India News Brief — {date_str}</b>",
        f"<i>Good morning Ajay! Here are your top updates for 10:00 AM IST:</i>\n"
    ]
    
    total_found = 0
    for category, url in FEEDS.items():
        items = fetch_feed(url, max_items=3)
        if items:
            total_found += len(items)
            lines.append(f"<b>{category}</b>")
            for i, item in enumerate(items, 1):
                clean_title = html.escape(item["title"])
                clean_link = item["link"]
                lines.append(f"{i}. <a href=\"{clean_link}\">{clean_title}</a>")
            lines.append("")
            
    if total_found == 0:
        lines.append("<i>Could not retrieve headlines at this moment.</i>")
        
    lines.append("🤖 <i>Sent by Hermes 24/7 Morning Dispatch</i>")
    return "\n".join(lines)


def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    allowed_users = os.environ.get("TELEGRAM_ALLOWED_USERS", "")
    chat_id = allowed_users.split(",")[0].strip() if allowed_users else None
    
    if not token or not chat_id:
        print("Error: TELEGRAM_BOT_TOKEN or TELEGRAM_ALLOWED_USERS not configured.", file=sys.stderr)
        return False
        
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode("utf-8")
    
    try:
        req = urllib.request.Request(url, data=payload)
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 200:
                print("Morning news brief successfully dispatched to Telegram.")
                return True
    except Exception as e:
        print(f"Error sending Telegram message: {e}", file=sys.stderr)
        return False


def main():
    print("Fetching morning news...")
    digest = generate_digest()
    success = send_telegram(digest)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
