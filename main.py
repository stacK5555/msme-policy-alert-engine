import os
import json
import time
import html
import requests
import feedparser
from bs4 import BeautifulSoup

# Commented out AI imports for debugging speed
# from google import genai
# from google.genai import types

SEEN_FILE = "seen_ids.json"
MAX_ENTRIES_PER_RUN = 8

# Target RSS Sources (Google Alerts RSS & Google News Search Feeds)
RSS_FEEDS = [
    "https://www.google.co.in/alerts/feeds/06169290745594020619/10383313577258338801",
    "https://www.google.co.in/alerts/feeds/06169290745594020619/989677120796858698",
    "https://www.google.co.in/alerts/feeds/06169290745594020619/6077878302474367054",
    "https://www.google.co.in/alerts/feeds/06169290745594020619/18211399035499238874",
    "https://news.google.com/rss/search?q=MSME+Uttarakhand+OR+Dehradun+handicrafts+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=NSIC+raw+material+OR+PM+Vishwakarma+metal+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
]

def load_seen_ids():
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            return set()
    return set()

def save_seen_ids(seen_ids):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen_ids)[-500:], f, indent=2)

def clean_html(raw_html):
    if not raw_html:
        return ""
    soup = BeautifulSoup(raw_html, "html.parser")
    return soup.get_text(separator=" ", strip=True)

def build_direct_card(title, summary, link):
    """
    Constructs a direct Telegram card from raw RSS data without AI processing.
    Escapes HTML entities to avoid Telegram parse errors.
    """
    safe_title = html.escape(title.strip())
    safe_link = html.escape(link.strip())
    
    # Trim summary to ~250 characters for a clean preview
    clean_text = summary.strip()
    if len(clean_text) > 250:
        clean_text = clean_text[:247] + "..."
    safe_summary = html.escape(clean_text)

    card = (
        f"📢 <b>{safe_title}</b>\n\n"
        f"📝 {safe_summary}\n\n"
        f"📍 <b>Link:</b> <a href=\"{safe_link}\">पूरी खबर पढ़ें (Read More)</a>"
    )
    return card

# def analyze_and_summarize(client, title, summary, link):
#     # Bypassed for now to debug RSS ingestion and Telegram delivery
#     pass

def send_telegram_message(bot_token, chat_id, text):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    try:
        resp = requests.post(url, json=payload, timeout=12)
        if resp.status_code != 200:
            print(f"Telegram dispatch failed: {resp.text}")
        return resp.status_code == 200
    except Exception as e:
        print(f"Network error sending to Telegram: {e}")
        return False

def main():
    # gemini_key = os.environ.get("GEMINI_API_KEY") # Bypassed temporarily
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not all([bot_token, chat_id]):
        print("Missing required environment variables (TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID). Exiting.")
        return

    seen_ids = load_seen_ids()
    new_seen_ids = set(seen_ids)
    processed_count = 0

    for feed_url in RSS_FEEDS:
        feed = feedparser.parse(
            feed_url,
            agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        for entry in feed.entries:
            entry_id = entry.get("id", entry.get("link", ""))
            if not entry_id or entry_id in seen_ids:
                continue

            title = entry.get("title", "")
            summary = clean_html(entry.get("summary", ""))
            link = entry.get("link", "")

            print(f"Processing RSS item: {title[:60]}...")
            
            # Direct formatting without AI
            card = build_direct_card(title, summary, link)

            success = send_telegram_message(bot_token, chat_id, card)
            if success:
                print(f"Posted alert for: {title[:50]}")
                new_seen_ids.add(entry_id)
            else:
                print(f"Telegram dispatch failed for: {title[:50]}. Will retry next run.")

            processed_count += 1
            time.sleep(1) # Small throttle to avoid Telegram flood limits

            if processed_count >= MAX_ENTRIES_PER_RUN:
                break

        if processed_count >= MAX_ENTRIES_PER_RUN:
            break

    save_seen_ids(new_seen_ids)
    print("Run complete. Checked feeds and updated seen_ids.")

if __name__ == "__main__":
    main()
