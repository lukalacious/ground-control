"""
Ground Control — Property Scraper
==================================
Uses Scrapling to scrape property search pages, detail enricher gets full data.

Usage:
    python scraper.py --city amsterdam --type buy
    python scraper.py --city amsterdam --type buy --delta
    python scraper.py --export
"""

import argparse
import csv
import json
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from scrapling.fetchers import StealthyFetcher
from lxml import html as lhtml

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

DETAIL_BASE = "https://www.funda.nl"
MIN_DELAY = 2.0
MAX_DELAY = 4.0

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("ground-control")


# ──────────────────────────────────────────────────────────────────────
# Database
# ──────────────────────────────────────────────────────────────────────

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    global_id       INTEGER PRIMARY KEY,
    address         TEXT,
    city            TEXT,
    postcode        TEXT,
    neighbourhood   TEXT,
    price           TEXT,
    price_numeric   INTEGER,
    listing_url     TEXT,
    detail_url      TEXT,
    agent_name      TEXT,
    agent_url       TEXT,
    image_url       TEXT,
    living_area     INTEGER,
    plot_area       INTEGER,
    bedrooms        INTEGER,
    energy_label    TEXT,
    object_type     TEXT,
    construction_type TEXT,
    is_project      BOOLEAN DEFAULT 0,
    labels          TEXT,
    listing_type    TEXT,
    first_seen      DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_seen       DATETIME DEFAULT CURRENT_TIMESTAMP,
    is_active       BOOLEAN DEFAULT 1,
    availability_status TEXT DEFAULT 'available',
    status_changed_at   DATETIME,
    description        TEXT,
    year_built         TEXT,
    num_rooms          INTEGER,
    num_bathrooms      INTEGER,
    bathroom_features  TEXT,
    num_floors         INTEGER,
    floor_level        TEXT,
    outdoor_area_m2    INTEGER,
    volume_m3          INTEGER,
    amenities          TEXT,
    insulation         TEXT,
    heating            TEXT,
    location_type      TEXT,
    has_balcony        BOOLEAN DEFAULT 0,
    balcony_type       TEXT,
    parking_type       TEXT,
    vve_contribution   TEXT,
    erfpacht          TEXT,
    acceptance         TEXT,
    photo_urls         TEXT,
    detail_enriched    BOOLEAN DEFAULT 0,
    detail_enriched_at DATETIME
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    city TEXT,
    search_type TEXT,
    pages_scraped INTEGER,
    listings_found INTEGER,
    new_listings INTEGER,
    updated_listings INTEGER
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    global_id INTEGER NOT NULL,
    old_price INTEGER NOT NULL,
    new_price INTEGER NOT NULL,
    recorded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (global_id) REFERENCES listings(global_id)
);

CREATE TABLE IF NOT EXISTS neighbourhood_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood TEXT NOT NULL,
    avg_price_m2 REAL,
    median_price REAL,
    listing_count INTEGER,
    calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS city_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avg_price_m2 REAL,
    median_price REAL,
    median_days_on_market REAL,
    listing_count INTEGER,
    calculated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_listings_city ON listings(city);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_listings_first_seen ON listings(first_seen);
CREATE INDEX IF NOT EXISTS idx_price_history_global_id ON price_history(global_id);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(DB_SCHEMA)
    # Migration: add status_changed_at for existing DBs
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    if "status_changed_at" not in existing:
        conn.execute("ALTER TABLE listings ADD COLUMN status_changed_at DATETIME")
        log.info("Migration: added status_changed_at column")
    conn.commit()
    log.info("Database ready: %s", db_path)
    return conn


_STATUS_RANK = {"available": 0, "negotiations": 1, "sold": 2}


def upsert_listing(conn, listing: dict, search_type: str) -> str:
    now = datetime.now(timezone.utc).isoformat()
    gid = listing["global_id"]

    existing = conn.execute(
        "SELECT price_numeric, is_active, availability_status FROM listings WHERE global_id = ?", (gid,)
    ).fetchone()

    new_status = listing.get("availability_status", "available")

    if existing is None:
        conn.execute("""INSERT INTO listings
            (global_id, address, city, postcode, neighbourhood, price, price_numeric,
             listing_url, detail_url, image_url, living_area, bedrooms,
             listing_type, first_seen, last_seen, is_active, availability_status,
             status_changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (gid, listing.get("address", ""), listing.get("city", ""),
             listing.get("postcode", ""), listing.get("neighbourhood", ""),
             listing.get("price", ""), listing.get("price_numeric"),
             listing.get("listing_url", ""), listing.get("detail_url", ""),
             listing.get("image_url", ""), listing.get("living_area"),
             listing.get("bedrooms"), search_type, now, now,
             new_status, now if new_status != "available" else None))
        return "new"
    else:
        # Forward-only status transitions: available → negotiations → sold
        old_status = existing["availability_status"] or "available"
        if _STATUS_RANK.get(new_status, 0) <= _STATUS_RANK.get(old_status, 0):
            new_status = old_status  # keep existing (higher) status
        status_changed = new_status != old_status

        conn.execute("""UPDATE listings SET price = ?, price_numeric = ?,
            last_seen = ?, is_active = 1, availability_status = ?,
            status_changed_at = CASE WHEN ? THEN ? ELSE status_changed_at END,
            image_url = ?, living_area = ?, bedrooms = ? WHERE global_id = ?""",
            (listing.get("price", ""), listing.get("price_numeric"),
             now, new_status,
             status_changed, now,
             listing.get("image_url", ""), listing.get("living_area"),
             listing.get("bedrooms"), gid))
        return "updated" if existing["price_numeric"] != listing.get("price_numeric") else "unchanged"


def mark_inactive(conn, active_ids: set, city: str, search_type: str) -> int:
    if not active_ids:
        return 0
    placeholders = ",".join("?" * len(active_ids))
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(f"""UPDATE listings SET is_active = 0, availability_status = 'sold',
        last_seen = ?, status_changed_at = ?
        WHERE city COLLATE NOCASE = ? AND listing_type = ? AND is_active = 1
        AND global_id NOT IN ({placeholders})""", (now, now, city, search_type, *active_ids))
    return cursor.rowcount


def calculate_stats(conn):
    conn.execute("DELETE FROM neighbourhood_stats")
    rows = conn.execute("""
        SELECT neighbourhood, AVG(CAST(price_numeric AS REAL) / living_area) as avg_m2,
               COUNT(*) as cnt
        FROM listings WHERE is_active = 1 AND living_area > 0 AND price_numeric > 0
        AND neighbourhood IS NOT NULL AND neighbourhood != ''
        GROUP BY neighbourhood HAVING COUNT(*) >= 3
    """).fetchall()
    
    for row in rows:
        conn.execute("""INSERT INTO neighbourhood_stats (neighbourhood, avg_price_m2, listing_count)
            VALUES (?, ?, ?)""", (row["neighbourhood"], row["avg_m2"], row["cnt"]))
    
    row = conn.execute("""
        SELECT AVG(CAST(price_numeric AS REAL) / living_area) as avg_m2, COUNT(*) as cnt
        FROM listings WHERE is_active = 1 AND living_area > 0 AND price_numeric > 0
    """).fetchone()
    
    conn.execute("""INSERT INTO city_stats (avg_price_m2, median_price, listing_count)
        VALUES (?, ?, ?)""", (row["avg_m2"] or 0, 0, row["cnt"] or 0))
    conn.commit()
    log.info("Stats calculated")


# ──────────────────────────────────────────────────────────────────────
# Scraping
# ──────────────────────────────────────────────────────────────────────

def _find_card_container(element):
    """Walk up ancestors to find the listing card container."""
    el = element
    for _ in range(10):
        parent = el.getparent()
        if parent is None:
            break
        text = parent.text_content() or ""
        if '€' in text and 'm²' in text:
            return parent
        el = parent
    return None


def _extract_card_data(card_text: str) -> dict:
    """Extract price, living area, and bedrooms from card text."""
    data = {}

    # Price: € 375.000 or € 1.595.000
    price_match = re.search(r'€\s?(\d{1,3}(?:\.\d{3})*)', card_text)
    if price_match:
        data['price_numeric'] = int(price_match.group(1).replace('.', ''))
        data['price'] = f"€ {data['price_numeric']:,}"

    # Living area: 40 m²
    area_match = re.search(r'(\d+)\s*m²', card_text)
    if area_match:
        data['living_area'] = int(area_match.group(1))

    return data


def _extract_status_from_card(card) -> str:
    """Detect availability status from card badge text (Verkocht, Onder bod, etc.)."""
    text = (card.text_content() or "").lower()
    # Check "verkocht" first — "Verkocht onder voorbehoud" contains "voorbehoud"
    if "verkocht" in text:
        return "sold"
    if "onder bod" in text or "voorbehoud" in text:
        return "negotiations"
    return "available"


def _extract_bedrooms_from_card(card) -> int | None:
    """Extract bedroom count from card list items (integer between m² and energy label)."""
    for ul in card.cssselect('ul'):
        items = [li.text_content().strip() for li in ul.cssselect('li')]
        for item in items:
            # Bedrooms are typically a standalone integer in the feature list
            if item.isdigit():
                return int(item)
    return None


def scrape_search_page(url: str) -> list[dict]:
    """Scrape a search page for listing links and card data."""
    fetcher = StealthyFetcher()
    page = fetcher.fetch(url, headless=True, network_idle=True)

    if page.status != 200:
        log.warning("  HTTP %d for %s", page.status, url)
        return []

    tree = lhtml.fromstring(page.html_content)

    listings = []
    seen = set()

    # ── Regular listing cards ──────────────────────────────────────
    address_links = tree.cssselect('a[data-testid="listingDetailsAddress"]')
    for link in address_links:
        href = link.get('href', '')
        if '/detail/koop/' not in href:
            continue

        match = re.search(r'/(\d{8,})/', href)
        if not match:
            continue
        gid = int(match.group(1))
        if gid in seen:
            continue
        seen.add(gid)

        detail_url = href if href.startswith('http') else f"{DETAIL_BASE}{href}"

        # Extract address and postcode from link's child divs
        divs = link.cssselect('div')
        address = ""
        postcode = ""
        city = ""
        if len(divs) >= 1:
            spans = divs[0].cssselect('span')
            address = spans[0].text_content().strip() if spans else divs[0].text_content().strip()
        if len(divs) >= 2:
            location_text = divs[1].text_content().strip()
            pc_match = re.search(r'(\d{4}\s?[A-Z]{2})', location_text)
            if pc_match:
                postcode = pc_match.group(1)
            # City is typically after the postcode
            city_match = re.search(r'\d{4}\s?[A-Z]{2}\s+(.*)', location_text)
            if city_match:
                city = city_match.group(1).strip()

        # Find the card container and extract data
        card = _find_card_container(link)
        card_data = {}
        bedrooms = None
        if card is not None:
            card_text = card.text_content() or ""
            card_data = _extract_card_data(card_text)
            bedrooms = _extract_bedrooms_from_card(card)

        status = _extract_status_from_card(card) if card is not None else "available"

        listings.append({
            "global_id": gid,
            "detail_url": detail_url,
            "listing_url": href,
            "address": address,
            "city": city,
            "postcode": postcode,
            "neighbourhood": "",
            "price": card_data.get("price", ""),
            "price_numeric": card_data.get("price_numeric"),
            "image_url": "",
            "living_area": card_data.get("living_area"),
            "bedrooms": bedrooms,
            "availability_status": status,
        })

    # ── Top-position listings ──────────────────────────────────────
    top_cards = tree.cssselect('[data-testid="top-position-listing"]')
    for top in top_cards:
        links_in_top = top.cssselect('a[href*="/detail/koop/"]')
        for a in links_in_top:
            href = a.get('href', '')
            match = re.search(r'/(\d{8,})/', href)
            if not match:
                continue
            gid = int(match.group(1))
            if gid in seen:
                continue
            seen.add(gid)

            detail_url = href if href.startswith('http') else f"{DETAIL_BASE}{href}"

            # Top-position: price often in <span class="font-normal">City, € X k.k.</span>
            top_text = top.text_content() or ""
            card_data = _extract_card_data(top_text)

            # Address from the link text (before the font-normal span)
            address = ""
            p_els = a.cssselect('p')
            if p_els:
                # Get text before the span
                p_text = p_els[0].text or ""
                address = p_text.strip().rstrip(',').strip()

            status = _extract_status_from_card(top)

            listings.append({
                "global_id": gid,
                "detail_url": detail_url,
                "listing_url": href,
                "address": address,
                "city": "",
                "postcode": "",
                "neighbourhood": "",
                "price": card_data.get("price", ""),
                "price_numeric": card_data.get("price_numeric"),
                "image_url": "",
                "living_area": card_data.get("living_area"),
                "bedrooms": None,
                "availability_status": status,
            })

    return listings


def scrape_all_pages(city: str, search_type: str, max_pages: int = None) -> list[dict]:
    """Scrape all search result pages."""
    all_listings = []
    page = 0
    
    while True:
        if max_pages and page >= max_pages:
            break
        
        # Build URL - /koop/ for buy, /huur/ for rent
        listing_type = "koop" if search_type == "buy" else "huur"
        url = f"https://www.funda.nl/zoeken/{listing_type}/?selected_area=%5B%22{city}%22%5D"
        if page > 0:
            url += f"&page={page}"
        
        log.info("Page %d: %s", page + 1, url)
        listings = scrape_search_page(url)
        
        if not listings:
            break
        
        all_listings.extend(listings)
        log.info("  Found %d listings (total: %d)", len(listings), len(all_listings))
        
        # If fewer than 15 results, we're at the end
        if len(listings) < 15:
            break
        
        page += 1
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    
    return all_listings


def run_scrape(city: str, search_type: str, db_path: str, delta: bool = False, max_pages: int = None) -> dict:
    conn = init_db(db_path)
    
    log.info("=" * 50)
    log.info("Ground Control Scraper (Scrapling)")
    log.info("  City: %s | Type: %s", city, search_type)
    log.info("=" * 50)
    
    listings = scrape_all_pages(city, search_type, max_pages)
    
    if not listings:
        log.warning("No listings found!")
        conn.close()
        return {"pages": 0, "found": 0, "new": 0, "updated": 0}
    
    stats = {"new": 0, "updated": 0, "unchanged": 0}
    active_ids = set()
    
    for listing in listings:
        result = upsert_listing(conn, listing, search_type)
        stats[result] += 1
        active_ids.add(listing["global_id"])
    
    inactive = 0
    if not delta:
        inactive = mark_inactive(conn, active_ids, city, search_type)
        log.info("Marked %d as inactive", inactive)
    
    pages_scraped = max(1, len(listings) // 15 + 1) if listings else 1
    conn.execute("""INSERT INTO scrape_runs (city, search_type, pages_scraped, listings_found, new_listings, updated_listings)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (city, search_type, pages_scraped, len(listings), stats["new"], stats["updated"]))
    conn.commit()
    
    calculate_stats(conn)
    conn.close()
    
    log.info("-" * 50)
    log.info("RESULTS: %d found, %d new, %d updated, %d inactive",
              len(listings), stats.get("new", 0), stats.get("updated", 0), inactive)
    log.info("-" * 50)
    
    return {"pages": pages_scraped, "found": len(listings), "new": stats.get("new", 0), "updated": stats.get("updated", 0)}


def export_csv(db_path: str, output_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM listings WHERE is_active = 1 ORDER BY first_seen DESC").fetchall()
    conn.close()
    
    if not rows:
        log.warning("No active listings")
        return
    
    keys = rows[0].keys()
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))
    log.info("Exported %d -> %s", len(rows), output_path)


def show_stats(db_path: str):
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM listings WHERE is_active = 1").fetchone()[0]
    conn.close()
    print(f"Total: {total}, Active: {active}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", default="amsterdam")
    parser.add_argument("--type", default="buy", choices=["buy", "rent"])
    parser.add_argument("--db", default="ground_control.db")
    parser.add_argument("--delta", action="store_true")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--export-path", default="export.csv")
    args = parser.parse_args()
    
    if args.stats:
        show_stats(args.db)
    elif args.export:
        export_csv(args.db, args.export_path)
    else:
        run_scrape(args.city, args.type, args.db, args.delta, args.max_pages)
