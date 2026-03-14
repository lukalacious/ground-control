#!/usr/bin/env python3
"""
Ground Control — Morning New Listing Report
==========================================
Finds listings first_seen in the last 24 hours and sends a Telegram report with map.

Usage:
    python morning_report.py                 # Run and send report
    python morning_report.py --dry-run      # Print without sending
    python morning_report.py --hours 48     # Look back 48h instead of 24h
"""

import argparse
import json
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
import sys

DB_PATH = Path(__file__).parent / "ground_control.db"

# Postcode area centroids (approximate)
POSTCODE_COORDS = {
    "1011": (52.3676, 4.9000), "1012": (52.3720, 4.8940), "1013": (52.3780, 4.8900),
    "1014": (52.3860, 4.8850), "1015": (52.3580, 4.8800), "1016": (52.3650, 4.8960),
    "1017": (52.3600, 4.9020), "1018": (52.3540, 4.9120), "1019": (52.3620, 4.9200),
    "1021": (52.3840, 4.9150), "1022": (52.3900, 4.9100), "1023": (52.3950, 4.9050),
    "1024": (52.4000, 4.9200), "1025": (52.4050, 4.9100), "1031": (52.3800, 4.9050),
    "1032": (52.3850, 4.9100), "1033": (52.3900, 4.8950), "1034": (52.4000, 4.9050),
    "1041": (52.3550, 4.8700), "1042": (52.3600, 4.8650), "1043": (52.3650, 4.8600),
    "1051": (52.3450, 4.8850), "1052": (52.3420, 4.8900), "1053": (52.3400, 4.8950),
    "1054": (52.3380, 4.9000), "1055": (52.3350, 4.8850), "1056": (52.3300, 4.8900),
    "1057": (52.3250, 4.8950), "1058": (52.3200, 4.9000), "1059": (52.3150, 4.9050),
    "1061": (52.3100, 4.8800), "1062": (52.3050, 4.8750), "1063": (52.3000, 4.8900),
    "1064": (52.2950, 4.8950), "1065": (52.2900, 4.9000), "1066": (52.2850, 4.9050),
    "1067": (52.2800, 4.9100), "1068": (52.2750, 4.9150), "1069": (52.2700, 4.9200),
    "1071": (52.3500, 4.9050), "1072": (52.3450, 4.9100), "1073": (52.3400, 4.9150),
    "1074": (52.3350, 4.9200), "1075": (52.3300, 4.9250), "1076": (52.3250, 4.9300),
    "1077": (52.3200, 4.9350), "1078": (52.3150, 4.9400), "1079": (52.3100, 4.9450),
    "1081": (52.3050, 4.9500), "1082": (52.3000, 4.9550), "1083": (52.2950, 4.9600),
    "1091": (52.2950, 4.9350), "1092": (52.2900, 4.9400), "1093": (52.2850, 4.9450),
    "1094": (52.2800, 4.9500), "1095": (52.2750, 4.9550), "1096": (52.2700, 4.9600),
    "1097": (52.2650, 4.9650), "1098": (52.2600, 4.9700),
    "1101": (52.3100, 4.9550), "1102": (52.3050, 4.9600), "1103": (52.3000, 4.9650),
}


def get_new_listings(db_path: str, hours: int = 24) -> list[dict]:
    """Get listings first_seen in the last N hours."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(f"""
        SELECT global_id, address, postcode, neighbourhood, price, price_numeric,
               living_area, bedrooms, detail_url, image_url, energy_label,
               year_built, has_balcony, floor_level, construction_type,
               num_rooms, num_bathrooms, vve_contribution, erfpacht,
               first_seen
        FROM listings
        WHERE is_active = 1
          AND first_seen >= datetime('now', '-{hours} hours')
        ORDER BY price_numeric ASC, first_seen DESC
    """).fetchall()

    conn.close()
    return [dict(r) for r in rows]


def generate_map_svg(listings: list[dict]) -> str:
    """Generate SVG map of listings."""
    WIDTH, HEIGHT = 600, 450
    MIN_LAT, MAX_LAT = 52.26, 52.42
    MIN_LON, MAX_LON = 4.85, 5.00

    def latlon_to_xy(lat, lon):
        x = (lon - MIN_LON) / (MAX_LON - MIN_LON) * WIDTH
        y = (MAX_LAT - lat) / (MAX_LAT - MIN_LAT) * HEIGHT
        return x, y

    circles = []
    for l in listings:
        pc = (l.get('postcode') or '').replace(' ', '')[:4]
        if pc in POSTCODE_COORDS:
            lat, lon = POSTCODE_COORDS[pc]
            x, y = latlon_to_xy(lat, lon)
            x += random.uniform(-12, 12)
            y += random.uniform(-12, 12)
            
            price = l.get('price_numeric')
            if price and price < 400000:
                color = '#22c55e'
            elif price and price < 600000:
                color = '#f97316'
            elif price:
                color = '#ef4444'
            else:
                color = '#9ca3af'
            
            circles.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="6" fill="{color}" opacity="0.75"/>')

    return f'''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {WIDTH} {HEIGHT}" width="{WIDTH}" height="{HEIGHT}">
    <rect width="100%" height="100%" fill="#f8fafc"/>
    <text x="15" y="25" font-family="Arial" font-size="14" font-weight="bold" fill="#1e293b">📍 Amsterdam — {len(listings)} new</text>
    {''.join(circles)}
    <rect x="15" y="{HEIGHT-45}" width="120" height="35" fill="white" rx="4" opacity="0.9"/>
    <circle cx="25" cy="{HEIGHT-28}" r="5" fill="#22c55e"/><text x="35" y="{HEIGHT-24}" font-family="Arial" font-size="9" fill="#374151">&lt;€400k</text>
    <circle cx="80" cy="{HEIGHT-28}" r="5" fill="#f97316"/><text x="90" y="{HEIGHT-24}" font-family="Arial" font-size="9" fill="#374151">€400-600k</text>
    <circle cx="135" cy="{HEIGHT-28}" r="5" fill="#ef4444"/><text x="145" y="{HEIGHT-24}" font-family="Arial" font-size="9" fill="#374151">&gt;€600k</text>
</svg>'''


def format_report(listings: list[dict], include_map: bool = True) -> tuple[str, str | None]:
    """Format listings as Telegram message. Returns (text, map_svg)."""
    if not listings:
        return "🏠 *Ground Control*\n\n_No new listings in the last 24 hours._", None

    # Generate map
    map_svg = generate_map_svg(listings) if include_map else None

    # Summary
    total_value = sum(l.get('price_numeric', 0) or 0 for l in listings)
    avg_price = total_value // len(listings) if listings and total_value > 0 else 0
    with_balcony = sum(1 for l in listings if l.get('has_balcony'))
    
    lines = [
        f"🏠 *Ground Control — New Listings ({len(listings)})*",
        f"\n📊 _avg €{avg_price:,} | {with_balcony} balcony_"
    ]

    # Show top 8 listings
    for i, l in enumerate(listings[:8], 1):
        if not l.get('price_numeric'):
            continue
            
        price = f"€{l['price_numeric']:,.0f}"
        addr = l.get('address', '')[:35] or l.get('postcode', 'Unknown') or '?'
        
        parts = []
        if l.get('living_area'):
            parts.append(f"{l['living_area']}m²")
        if l.get('num_rooms'):
            parts.append(f"{l['num_rooms']}k")
        
        tags = []
        if l.get('has_balcony'):
            tags.append("🌿")
        if l.get('energy_label'):
            tags.append(f"⚡{l['energy_label']}")
        
        details = " • ".join(parts) if parts else ""
        tag_str = " ".join(tags) if tags else ""
        
        lines.append(f"\n{i}. *{price}* — {addr}")
        if details or tag_str:
            lines.append(f"   {details} {tag_str}".strip())

    if len(listings) > 8:
        lines.append(f"\n_...and {len(listings) - 8} more_")

    lines.append(f"\n_{datetime.now().strftime('%H:%M')}_")
    
    return "\n".join(lines), map_svg


def get_keychain_password(label: str) -> str | None:
    """Read password from macOS Keychain."""
    import subprocess
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-l", label, "-w"],
            capture_output=True, text=True, timeout=5
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except Exception:
        return None


def send_telegram(message: str, map_svg: str | None = None, dry_run: bool = False) -> bool:
    """Send message via Telegram bot."""
    bot_token = get_keychain_password("telegram-bot-token")
    chat_id = get_keychain_password("telegram-chat-id")
    
    if not bot_token or not chat_id:
        print("ERROR: Telegram credentials not found")
        return False
    
    if dry_run:
        print("[DRY RUN]")
        print(message)
        if map_svg:
            print("[MAP SVG generated]")
        return True
    
    import requests
    
    # Send text first
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=data, timeout=10)
    
    # Send map as photo if we have one
    if map_svg and resp.status_code == 200:
        # Save SVG to temp file
        svg_path = "/tmp/ground_control_map.svg"
        with open(svg_path, "w") as f:
            f.write(map_svg)
        
        # Upload as photo
        url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
        with open(svg_path, "rb") as f:
            files = {"photo": ("map.svg", f, "image/svg+xml")}
            data = {"chat_id": chat_id, "caption": "📍 New listings map"}
            resp2 = requests.post(url, files=files, data=data, timeout=30)
            if resp2.status_code == 200:
                print(f"✓ Map sent")
            else:
                print(f"Map send error: {resp2.status_code}")
    
    if resp.status_code == 200:
        print(f"✓ Report sent to {chat_id}")
        return True
    else:
        print(f"ERROR: {resp.status_code} - {resp.text}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=24)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-map", action="store_true")
    parser.add_argument("--db", default=str(DB_PATH))
    args = parser.parse_args()

    print(f"=== Morning Report: {datetime.now().strftime('%Y-%m-%d %H:%M')} ===")
    
    listings = get_new_listings(args.db, hours=args.hours)
    print(f"Found {len(listings)} new listing(s)")
    
    message, map_svg = format_report(listings, include_map=not args.no_map)
    send_telegram(message, map_svg, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
