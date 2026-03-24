"""
Ground Control — Telegram Notifications
========================================
Sends new listing alerts and daily digest summaries via Telegram.

Uses macOS Keychain for credentials (like morning_report.py) with
environment variable fallback.

Usage:
    python notifier.py --test     # Send a test message
    python notifier.py --digest   # Send daily digest
"""

import argparse
import logging
import os
import subprocess
from datetime import datetime, timezone

import requests

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("notifier")

APP_BASE_URL = "https://ground-control.vercel.app"


# ──────────────────────────────────────────────────────────────────────
# Credentials
# ──────────────────────────────────────────────────────────────────────

def _get_keychain_password(label: str) -> str | None:
    """Read password from macOS Keychain."""
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-l", label, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def _get_telegram_creds() -> tuple[str | None, str | None]:
    """Get Telegram bot token and chat ID from env or Keychain."""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN") or _get_keychain_password("telegram-bot-token")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or _get_keychain_password("telegram-chat-id")
    return bot_token, chat_id


# ──────────────────────────────────────────────────────────────────────
# Telegram sender
# ──────────────────────────────────────────────────────────────────────

def _send_message(text: str) -> bool:
    """Send a message via Telegram bot API."""
    bot_token, chat_id = _get_telegram_creds()
    if not bot_token or not chat_id:
        log.error("Telegram credentials not found (check TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID env or Keychain)")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        resp = requests.post(url, json=data, timeout=10)
        if resp.status_code == 200:
            log.info("Message sent to chat %s", chat_id)
            return True
        else:
            log.error("Telegram API error: %d — %s", resp.status_code, resp.text)
            return False
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return False


# ──────────────────────────────────────────────────────────────────────
# Notification functions
# ──────────────────────────────────────────────────────────────────────

def notify_new_listings(listings: list[dict]) -> int:
    """
    Send Telegram notification for each new listing.
    Returns number of messages successfully sent.
    """
    if not listings:
        return 0

    sent = 0
    for listing in listings:
        address = listing.get("address", "Unknown")
        neighbourhood = listing.get("neighbourhood", "")
        price = listing.get("price", "")
        price_numeric = listing.get("price_numeric", 0)
        living_area = listing.get("living_area", 0)
        bedrooms = listing.get("bedrooms", "?")
        erfpacht_status = listing.get("erfpacht_status", "unknown")
        score = listing.get("score", "?")
        global_id = listing.get("global_id", "")

        # Compute price/m2
        price_m2 = ""
        if price_numeric and living_area and living_area > 0:
            price_m2 = f"{price_numeric / living_area:,.0f}"

        # Build app URL
        app_url = f"{APP_BASE_URL}/listing/{global_id}" if global_id else APP_BASE_URL

        location = address
        if neighbourhood:
            location = f"{address}, {neighbourhood}"

        message = (
            f"\U0001f3e0 New Listing\n"
            f"\U0001f4cd {location}\n"
            f"\U0001f4b0 {price} ({price_m2} \u20ac/m\u00b2)\n"
            f"\U0001f4d0 {living_area}m\u00b2 \u00b7 {bedrooms} bed\n"
            f"\U0001f3f7\ufe0f Erfpacht: {erfpacht_status}\n"
            f"\U0001f4ca Score: {score}/100\n"
            f"\U0001f517 {app_url}"
        )

        if _send_message(message):
            sent += 1

    log.info("Sent %d/%d new listing notifications", sent, len(listings))
    return sent


def send_daily_digest(stats: dict) -> bool:
    """
    Send a daily summary of scraping activity.

    Expected stats dict keys:
        new_listings, total_active, avg_price, avg_price_m2,
        enriched_today, translated_today, scrape_cycles
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")

    new = stats.get("new_listings", 0)
    total = stats.get("total_active", 0)
    avg_price = stats.get("avg_price", 0)
    avg_m2 = stats.get("avg_price_m2", 0)
    enriched = stats.get("enriched_today", 0)
    translated = stats.get("translated_today", 0)
    cycles = stats.get("scrape_cycles", 0)

    message = (
        f"\U0001f4cb *Ground Control Daily Digest*\n"
        f"\U0001f4c5 {date_str}\n\n"
        f"\U0001f195 New listings: *{new}*\n"
        f"\U0001f3e0 Total active: *{total}*\n"
        f"\U0001f4b0 Avg price: \u20ac{avg_price:,.0f}\n"
        f"\U0001f4cf Avg \u20ac/m\u00b2: {avg_m2:,.0f}\n\n"
        f"\u2699\ufe0f Cycles: {cycles}\n"
        f"\U0001f50d Enriched: {enriched}\n"
        f"\U0001f310 Translated: {translated}\n\n"
        f"_{now.strftime('%H:%M UTC')}_"
    )

    return _send_message(message)


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground Control — Telegram Notifier")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    parser.add_argument("--digest", action="store_true", help="Send daily digest with sample data")
    args = parser.parse_args()

    if args.test:
        success = _send_message(
            "\U0001f6f0\ufe0f *Ground Control* — Test notification\n\n"
            "If you see this, Telegram integration is working."
        )
        if success:
            print("Test message sent successfully")
        else:
            print("Failed to send test message")

    elif args.digest:
        send_daily_digest({
            "new_listings": 12,
            "total_active": 345,
            "avg_price": 485000,
            "avg_price_m2": 6250,
            "enriched_today": 8,
            "translated_today": 5,
            "scrape_cycles": 6,
        })

    else:
        parser.print_help()
