import os
import json
import time
import html
import requests
import feedparser
from bs4 import BeautifulSoup
from google import genai
from google.genai import types

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

def analyze_and_summarize(client, title, summary, link):
    safe_link = html.escape(link)
    prompt = f"""
You are an operational intelligence assistant for micro-enterprises and local metal craft suppliers (brass, steel, blade forging, and artisan tools) in Dehradun and the Garhwal belt of Uttarakhand.

Review the following news or policy release:
Title: {title}
Summary/Content: {summary}

INSTRUCTIONS:
1. Determine if this contains actionable value for small manufacturing units, metal suppliers, raw material schemes (steel/brass subsidies, NSIC allotments), exhibitions, credit/grants, or artisan policies (e.g., PM Vishwakarma, ZED, Uttarakhand MSME Policy).
2. If it is generic politics, unrelated corporate news, or completely irrelevant, output ONLY the single word: SKIP.
3. If RELEVANT, write a clear, crisp, bilingual (Hindi + plain English) summary under 80 words using HTML formatting:

📢 <b>नई सूचना / MSME Update:</b> [Crisp title in Hindi and English]
🎯 <b>पात्रता / Eligibility:</b> [Who benefits, e.g., Metal fabricators, Udyam registered suppliers]
💰 <b>लाभ / Direct Benefit:</b> [Subsidy %, financial grant, raw material assistance, or deadline]
📍 <b>कहाँ संपर्क करें / Link:</b> <a href="{safe_link}">यहाँ क्लिक करें (Click Here)</a>
"""
    # Models to attempt with fallback
    candidate_models = ["gemini-3.8-flash", "gemini-3.5-flash-lite"]

    for model_name in candidate_models:
        for attempt in range(2):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                    )
                )
                output = response.text.strip()
                if "SKIP" in output:
                    return "SKIP"
                return output
            except Exception as e:
                err_str = str(e)
                print(f"Attempt {attempt + 1} with {model_name} failed: {err_str}")
                if "503" in err_str or "UNAVAILABLE" in err_str:
                    time.sleep(3)  # Brief wait on temporary server spikes
                    continue
                break  # If model is not found (404), fall back to next model immediately

    return None

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
    gemini_key = os.environ.get("GEMINI_API_KEY")
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not all([gemini_key, bot_token, chat_id]):
        print("Missing required environment variables. Exiting.")
        return

    client = genai.Client(api_key=gemini_key)
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

            print(f"Evaluating: {title[:60]}...")
            card = analyze_and_summarize(client, title, summary, link)

            if card == "SKIP":
                print("Irrelevant item, marked as skipped.")
                new_seen_ids.add(entry_id)
            elif card:
                success = send_telegram_message(bot_token, chat_id, card)
                if success:
                    print(f"Posted alert for: {title[:50]}")
                    new_seen_ids.add(entry_id)
                else:
                    print(f"Telegram dispatch failed for: {title[:50]}. Will retry next run.")
            else:
                print(f"API error occurred for: {title[:50]}. NOT marking as seen so it retries.")

            processed_count += 1
            time.sleep(2)

            if processed_count >= MAX_ENTRIES_PER_RUN:
                break

        if processed_count >= MAX_ENTRIES_PER_RUN:
            break

    save_seen_ids(new_seen_ids)
    print("Run complete. Checked feeds and updated seen_ids.")

if __name__ == "__main__":
    main()
