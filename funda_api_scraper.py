"""
Funda.nl API Scraper
====================
Hits Funda's internal Elasticsearch search API directly — no browser automation needed.

Endpoint: POST https://listing-search-wonen.funda.io/_msearch/template
Discovered via reverse-engineering the Funda mobile app (pyfunda project).

Usage:
    # Initial load — scrape all pages
    python funda_api_scraper.py --city amsterdam --type buy --min-price 325000 --max-price 400000

    # Daily delta — only new listings since last run
    python funda_api_scraper.py --city amsterdam --type buy --min-price 325000 --max-price 400000 --delta

    # Export database to CSV
    python funda_api_scraper.py --export

Setup:
    pip install curl_cffi     # recommended — handles TLS fingerprinting
    # OR
    pip install requests      # fallback — may get blocked by bot detection
"""

import argparse
import csv
import json
import logging
import random
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

# TLS fingerprinting: prefer curl_cffi, fall back to requests
try:
    from curl_cffi import requests as http_client
    HTTP_BACKEND = "curl_cffi"
except ImportError:
    import requests as http_client
    HTTP_BACKEND = "requests"

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

API_URL = "https://listing-search-wonen.funda.io/_msearch/template"
ES_INDEX = "listings-wonen-searcher-alias-prod"
SEARCH_TEMPLATE_ID = "search_result_20250805"
RESULTS_PER_PAGE = 15

DETAIL_BASE = "https://www.funda.nl"
PHOTO_BASE = "https://cloud.funda.nl/valentina_media"
PHOTO_WIDTH = 464


def _generate_trace_headers() -> dict:
    """Generate Datadog tracing headers mimicking the Funda mobile app."""
    trace_id = str(random.randint(10**18, 10**19))
    parent_id = hex(random.randint(10**15, 10**16))[2:]
    tid = hex(int(time.time()))[2:] + "00000000"

    return {
        "User-Agent": "Dart/3.9 (dart:io)",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Referer": "https://www.funda.nl/",
        "Accept-Encoding": "gzip",
        "x-datadog-sampling-priority": "0",
        "x-datadog-origin": "rum",
        "x-datadog-parent-id": trace_id,
        "tracestate": f"dd=s:0;o:rum;p:{parent_id}",
        "traceparent": f"00-{tid}{trace_id[:16]}-{parent_id}-00",
    }


@dataclass
class ScraperConfig:
    # Search parameters
    city: str = "amsterdam"
    search_type: str = "buy"            # "buy" or "rent"
    min_price: Optional[int] = None
    max_price: Optional[int] = None
    object_types: list[str] = field(default_factory=lambda: ["residential"])
    property_types: list[str] = field(default_factory=lambda: ["house", "apartment"])
    construction_types: list[str] = field(default_factory=list)

    # Pagination
    max_pages: Optional[int] = None     # None = all pages

    # Rate limiting
    min_delay: float = 1.0
    max_delay: float = 3.0

    # Database
    db_path: str = "funda.db"

    # Mode
    delta_mode: bool = False            # Only fetch new listings


# ──────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("funda-api")


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
    is_active       BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    city            TEXT,
    search_type     TEXT,
    pages_scraped   INTEGER,
    listings_found  INTEGER,
    new_listings    INTEGER,
    updated_listings INTEGER
);

CREATE TABLE IF NOT EXISTS price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    global_id       INTEGER NOT NULL,
    old_price       INTEGER NOT NULL,
    new_price       INTEGER NOT NULL,
    recorded_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (global_id) REFERENCES listings(global_id)
);

CREATE TABLE IF NOT EXISTS neighbourhood_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    neighbourhood   TEXT NOT NULL,
    avg_price_m2    REAL,
    median_price    REAL,
    listing_count   INTEGER,
    calculated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS city_stats (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    avg_price_m2    REAL,
    median_price    REAL,
    median_days_on_market REAL,
    listing_count   INTEGER,
    calculated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_listings_city ON listings(city);
CREATE INDEX IF NOT EXISTS idx_listings_active ON listings(is_active);
CREATE INDEX IF NOT EXISTS idx_listings_first_seen ON listings(first_seen);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen);
CREATE INDEX IF NOT EXISTS idx_price_history_global_id ON price_history(global_id);
CREATE INDEX IF NOT EXISTS idx_price_history_recorded_at ON price_history(recorded_at);
CREATE INDEX IF NOT EXISTS idx_neighbourhood_stats_name ON neighbourhood_stats(neighbourhood);
"""


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialise SQLite database with schema."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create tables first
    conn.executescript(DB_SCHEMA)

    # Add columns that may not exist yet (upgrade path from old schema)
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    new_cols = {
        "postcode": "TEXT",
        "neighbourhood": "TEXT",
        "living_area": "INTEGER",
        "plot_area": "INTEGER",
        "bedrooms": "INTEGER",
        "energy_label": "TEXT",
        "object_type": "TEXT",
        "construction_type": "TEXT",
        "previous_price": "INTEGER",
    }
    for col, col_type in new_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {col_type}")

    conn.commit()
    log.info("Database ready: %s (backend: %s)", db_path, HTTP_BACKEND)
    return conn


def upsert_listing(conn: sqlite3.Connection, listing: dict, search_type: str) -> str:
    """Insert or update a listing. Returns 'new', 'updated', or 'unchanged'."""
    now = datetime.now(timezone.utc).isoformat()
    global_id = listing["globalId"]

    existing = conn.execute(
        "SELECT global_id, price, price_numeric, previous_price, is_active FROM listings WHERE global_id = ?",
        (global_id,),
    ).fetchone()

    price = listing.get("price", "")
    price_numeric = listing.get("price_numeric")
    address = listing.get("address", "")
    city = listing.get("city", "")
    listing_url = listing.get("listingUrl", "")
    detail_url = listing.get("detailUrl", "")

    if existing is None:
        conn.execute(
            """INSERT INTO listings
               (global_id, address, city, postcode, neighbourhood, price, price_numeric,
                listing_url, detail_url, agent_name, agent_url, image_url,
                living_area, plot_area, bedrooms, energy_label, object_type,
                construction_type, is_project, labels, listing_type,
                first_seen, last_seen, is_active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                global_id,
                address,
                city,
                listing.get("postcode", ""),
                listing.get("neighbourhood", ""),
                price,
                price_numeric,
                listing_url,
                detail_url,
                listing.get("agentName", ""),
                listing.get("agentUrl", ""),
                listing.get("imageUrl", ""),
                listing.get("livingArea"),
                listing.get("plotArea"),
                listing.get("bedrooms"),
                listing.get("energyLabel", ""),
                listing.get("objectType", ""),
                listing.get("constructionType", ""),
                listing.get("isProject", False),
                json.dumps(listing.get("labels", [])),
                search_type,
                now,
                now,
            ),
        )
        return "new"
    else:
        old_price_numeric = existing["price_numeric"]
        price_changed = (old_price_numeric and price_numeric
                         and old_price_numeric != price_numeric)

        if price_changed:
            conn.execute(
                "INSERT INTO price_history (global_id, old_price, new_price) VALUES (?, ?, ?)",
                (global_id, old_price_numeric, price_numeric),
            )
            log.info("  Price change: %s  %d -> %d", listing.get("address", ""), old_price_numeric, price_numeric)

        prev_price = old_price_numeric if price_changed else existing["previous_price"]
        reactivated = not existing["is_active"]

        conn.execute(
            """UPDATE listings
               SET price = ?, price_numeric = ?, previous_price = ?,
                   last_seen = ?, is_active = 1,
                   image_url = ?, living_area = ?, bedrooms = ?, energy_label = ?
               WHERE global_id = ?""",
            (
                price,
                price_numeric,
                prev_price,
                now,
                listing.get("imageUrl", ""),
                listing.get("livingArea"),
                listing.get("bedrooms"),
                listing.get("energyLabel", ""),
                global_id,
            ),
        )
        return "updated" if (price_changed or reactivated) else "unchanged"


def mark_inactive(conn: sqlite3.Connection, active_ids: set[int], city: str, search_type: str) -> int:
    """Mark listings not seen in this run as inactive."""
    if not active_ids:
        return 0
    placeholders = ",".join("?" * len(active_ids))
    cursor = conn.execute(
        f"""UPDATE listings SET is_active = 0
            WHERE city = ? AND listing_type = ? AND is_active = 1
            AND global_id NOT IN ({placeholders})""",
        (city, search_type, *active_ids),
    )
    return cursor.rowcount


def log_run(conn: sqlite3.Connection, city: str, search_type: str,
            pages: int, found: int, new: int, updated: int) -> None:
    conn.execute(
        """INSERT INTO scrape_runs (city, search_type, pages_scraped, listings_found, new_listings, updated_listings)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (city, search_type, pages, found, new, updated),
    )


def calculate_neighbourhood_stats(conn: sqlite3.Connection) -> None:
    """Calculate per-neighbourhood price statistics from active listings."""
    conn.execute("DELETE FROM neighbourhood_stats")

    rows = conn.execute("""
        SELECT neighbourhood, GROUP_CONCAT(price_numeric) as prices,
               AVG(CAST(price_numeric AS REAL) / living_area) as avg_m2,
               COUNT(*) as cnt
        FROM listings
        WHERE is_active = 1 AND living_area > 0 AND price_numeric > 0
              AND neighbourhood IS NOT NULL AND neighbourhood != ''
        GROUP BY neighbourhood
        HAVING COUNT(*) >= 3
    """).fetchall()

    for row in rows:
        prices = sorted(int(p) for p in row["prices"].split(","))
        median = prices[len(prices) // 2]
        conn.execute(
            """INSERT INTO neighbourhood_stats (neighbourhood, avg_price_m2, median_price, listing_count)
               VALUES (?, ?, ?, ?)""",
            (row["neighbourhood"], row["avg_m2"], median, row["cnt"]),
        )
    conn.commit()
    log.info("Neighbourhood stats: %d neighbourhoods calculated", len(rows))


def calculate_city_stats(conn: sqlite3.Connection) -> dict:
    """Calculate city-wide statistics."""
    conn.execute("DELETE FROM city_stats")

    row = conn.execute("""
        SELECT AVG(CAST(price_numeric AS REAL) / living_area) as avg_m2,
               COUNT(*) as cnt
        FROM listings
        WHERE is_active = 1 AND living_area > 0 AND price_numeric > 0
    """).fetchone()

    prices = [r[0] for r in conn.execute(
        "SELECT price_numeric FROM listings WHERE is_active = 1 AND price_numeric > 0 ORDER BY price_numeric"
    ).fetchall()]
    median_price = prices[len(prices) // 2] if prices else 0

    days = sorted(
        r[0] for r in conn.execute(
            "SELECT julianday('now') - julianday(first_seen) FROM listings WHERE is_active = 1 AND first_seen IS NOT NULL"
        ).fetchall()
        if r[0] is not None
    )
    median_dom = days[len(days) // 2] if days else 0

    stats = {
        "avg_price_m2": row["avg_m2"] or 0,
        "median_price": median_price,
        "median_days_on_market": round(median_dom, 1),
        "listing_count": row["cnt"] or 0,
    }
    conn.execute(
        """INSERT INTO city_stats (avg_price_m2, median_price, median_days_on_market, listing_count)
           VALUES (?, ?, ?, ?)""",
        (stats["avg_price_m2"], stats["median_price"], stats["median_days_on_market"], stats["listing_count"]),
    )
    conn.commit()
    log.info("City stats: avg EUR/m2=%.0f, median=%.0f, listings=%d",
             stats["avg_price_m2"], stats["median_price"], stats["listing_count"])
    return stats


# ──────────────────────────────────────────────────────────────────────
# API client
# ──────────────────────────────────────────────────────────────────────

class FundaAPIClient:
    """Client for Funda's Elasticsearch search API."""

    def __init__(self, cfg: ScraperConfig):
        self.cfg = cfg
        self._request_count = 0

        # Create session based on available backend
        if HTTP_BACKEND == "curl_cffi":
            self.session = http_client.Session(impersonate="safari15_5")
            log.info("Using curl_cffi (safari15_5 TLS fingerprint)")
        else:
            self.session = http_client.Session()
            log.warning("Using plain requests — may be blocked by TLS fingerprinting. "
                        "Install curl_cffi: pip install curl_cffi")

    def _build_ndjson_body(self, offset: int = 0) -> str:
        """Build the NDJSON request body for Elasticsearch _msearch/template."""
        offering = "buy" if self.cfg.search_type == "buy" else "rent"
        price_key = "selling_price" if self.cfg.search_type == "buy" else "rent_price"

        params = {
            "availability": ["available", "negotiations"],
            "type": ["single"],
            "zoning": self.cfg.object_types,
            "object_type": self.cfg.property_types,
            "publication_date": {"no_preference": True},
            "offering_type": offering,
            "page": {"from": offset},
            "sort": {"field": "publish_date_utc", "order": "desc"},
            "selected_area": [self.cfg.city],
        }

        # Add price filter if specified
        if self.cfg.min_price or self.cfg.max_price:
            price_filter = {}
            if self.cfg.min_price:
                price_filter["from"] = self.cfg.min_price
            if self.cfg.max_price:
                price_filter["to"] = self.cfg.max_price
            params["price"] = {price_key: price_filter}

        index_line = json.dumps({"index": ES_INDEX})
        query_line = json.dumps({"id": SEARCH_TEMPLATE_ID, "params": params})
        return f"{index_line}\n{query_line}\n"

    @staticmethod
    def _normalize_listing(hit: dict, search_type: str) -> dict:
        """Transform an ES hit into a flat dict for upsert_listing."""
        source = hit.get("_source", {})
        addr = source.get("address", {})

        # Build full address string
        street = addr.get("street_name", "")
        house_num = str(addr.get("house_number", ""))
        house_suffix = addr.get("house_number_suffix", "") or ""
        full_address = f"{street} {house_num}{house_suffix}".strip()

        city = addr.get("city", "")

        # Price
        price_data = source.get("price", {})
        price_key = "selling_price" if search_type == "buy" else "rent_price"
        price_list = price_data.get(price_key, [])
        price_numeric = price_list[0] if price_list else None

        # Include price condition (k.k. / v.o.n.)
        condition = price_data.get(f"{price_key}_condition", "")
        condition_map = {"kosten_koper": "k.k.", "vrij_op_naam": "v.o.n."}
        condition_str = condition_map.get(condition, "")

        if price_numeric:
            price_str = f"{price_numeric:,.0f} {condition_str}".replace(",", ".").strip()
        else:
            price_str = ""

        # Photo — Funda CDN uses chunked ID format: 224821207 → 224/821/207.jpg
        thumbnails = source.get("thumbnail_id", [])
        if thumbnails:
            tid = str(thumbnails[0])
            chunked = "/".join(tid[i:i+3] for i in range(0, len(tid), 3))
            photo_url = f"{PHOTO_BASE}/{chunked}.jpg?options=width={PHOTO_WIDTH}"
        else:
            photo_url = ""

        # Areas
        floor_area_list = source.get("floor_area", [])
        living_area = floor_area_list[0] if floor_area_list else None
        plot_range = source.get("plot_area_range") or source.get("floor_area_range") or {}
        plot_area = plot_range.get("gte") if "plot_area_range" in source else None

        global_id = hit.get("_id", "")

        # Use the real Funda URL from the response
        relative_url = source.get("object_detail_page_relative_url", "")
        listing_url = relative_url
        detail_url = f"{DETAIL_BASE}{relative_url}" if relative_url else ""

        # Agent info
        agents = source.get("agent", [])
        primary_agent = next((a for a in agents if a.get("is_primary")), agents[0] if agents else {})
        agent_name = primary_agent.get("name", "")
        agent_url = primary_agent.get("relative_url", "")

        return {
            "globalId": int(global_id) if global_id else 0,
            "address": full_address,
            "city": city,
            "postcode": addr.get("postal_code", ""),
            "neighbourhood": addr.get("neighbourhood", ""),
            "price": price_str,
            "price_numeric": price_numeric,
            "listingUrl": listing_url,
            "detailUrl": detail_url,
            "imageUrl": photo_url,
            "livingArea": living_area,
            "plotArea": plot_area,
            "bedrooms": source.get("number_of_bedrooms"),
            "energyLabel": source.get("energy_label", ""),
            "objectType": source.get("object_type", ""),
            "constructionType": source.get("construction_type", ""),
            "agentName": agent_name,
            "agentUrl": agent_url,
            "isProject": source.get("type") == "project",
            "labels": [],
        }

    def search(self, offset: int = 0, retries: int = 3) -> list[dict]:
        """Execute a single search and return normalized listings."""
        self._request_count += 1

        # Rate limit
        if self._request_count > 1:
            delay = random.uniform(self.cfg.min_delay, self.cfg.max_delay)
            log.info("  Waiting %.1fs ...", delay)
            time.sleep(delay)

        for attempt in range(1, retries + 1):
            headers = _generate_trace_headers()
            body = self._build_ndjson_body(offset)

            response = self.session.post(
                API_URL,
                headers=headers,
                data=body.encode("utf-8"),
            )

            if response.status_code == 403:
                log.error("403 Forbidden — TLS fingerprint may be blocked. "
                          "Try: pip install curl_cffi")
                raise PermissionError("API returned 403. Install curl_cffi for TLS fingerprinting.")

            if response.status_code in (400, 429, 500, 502, 503):
                if attempt < retries:
                    wait = 2 ** attempt + random.uniform(0, 1)
                    log.warning("  %d error — retrying in %.1fs (attempt %d/%d)",
                                response.status_code, wait, attempt, retries)
                    time.sleep(wait)
                    continue
                log.error("  %d error — giving up after %d attempts", response.status_code, retries)

            response.raise_for_status()
            break

        data = response.json()

        # Parse Elasticsearch multi-search response
        responses = data.get("responses", [])
        if not responses:
            return []

        hits = responses[0].get("hits", {}).get("hits", [])
        return [self._normalize_listing(hit, self.cfg.search_type) for hit in hits]

    def get_total_count(self) -> Optional[int]:
        """Get total number of matching listings (from first request)."""
        headers = _generate_trace_headers()
        body = self._build_ndjson_body(0)

        response = self.session.post(
            API_URL,
            headers=headers,
            data=body.encode("utf-8"),
        )
        response.raise_for_status()
        data = response.json()
        responses = data.get("responses", [])
        if responses:
            return responses[0].get("hits", {}).get("total", {}).get("value")
        return None

    def search_all_pages(self) -> list[dict]:
        """Paginate through all search results."""
        all_listings = []
        page = 0
        offset = 0

        while True:
            if self.cfg.max_pages and page >= self.cfg.max_pages:
                log.info("Reached max pages limit (%d)", self.cfg.max_pages)
                break

            log.info("Page %d (offset %d) ...", page + 1, offset)
            try:
                listings = self.search(offset)
            except Exception as e:
                log.error("Failed on page %d: %s", page + 1, e)
                break

            if not listings:
                log.info("No more listings — pagination complete")
                break

            all_listings.extend(listings)
            log.info("  Got %d listings (total: %d)", len(listings), len(all_listings))

            if len(listings) < RESULTS_PER_PAGE:
                log.info("Last page reached (got %d < %d listings)",
                         len(listings), RESULTS_PER_PAGE)
                break

            page += 1
            offset += RESULTS_PER_PAGE

        return all_listings


# ──────────────────────────────────────────────────────────────────────
# Main scraper orchestration
# ──────────────────────────────────────────────────────────────────────

def run_scrape(cfg: ScraperConfig) -> dict:
    """Run a full scrape and store results in SQLite."""
    conn = init_db(cfg.db_path)
    client = FundaAPIClient(cfg)

    log.info("=" * 60)
    log.info("Funda API Scraper")
    log.info("  City: %s | Type: %s", cfg.city, cfg.search_type)
    if cfg.min_price or cfg.max_price:
        log.info("  Price: %s - %s", cfg.min_price or "any", cfg.max_price or "any")
    log.info("  Database: %s", cfg.db_path)
    log.info("  Mode: %s", "delta" if cfg.delta_mode else "full")
    log.info("=" * 60)

    # Fetch all listings
    listings = client.search_all_pages()

    if not listings:
        log.warning("No listings found!")
        conn.close()
        return {"pages": 0, "found": 0, "new": 0, "updated": 0}

    # Upsert into database
    stats = {"new": 0, "updated": 0, "unchanged": 0}
    active_ids = set()

    for listing in listings:
        result = upsert_listing(conn, listing, cfg.search_type)
        stats[result] += 1
        active_ids.add(listing["globalId"])

    # Mark listings no longer appearing as inactive (full mode only)
    inactive_count = 0
    if not cfg.delta_mode:
        inactive_count = mark_inactive(conn, active_ids, cfg.city, cfg.search_type)
        if inactive_count:
            log.info("Marked %d listings as inactive", inactive_count)

    # Calculate pages scraped
    pages_scraped = (len(listings) + RESULTS_PER_PAGE - 1) // RESULTS_PER_PAGE

    # Log the run
    log_run(conn, cfg.city, cfg.search_type, pages_scraped, len(listings), stats["new"], stats["updated"])

    conn.commit()

    # Calculate statistics
    calculate_neighbourhood_stats(conn)
    calculate_city_stats(conn)

    conn.close()

    log.info("-" * 60)
    log.info("RESULTS")
    log.info("  Total listings: %d", len(listings))
    log.info("  New:            %d", stats["new"])
    log.info("  Updated:        %d", stats["updated"])
    log.info("  Unchanged:      %d", stats["unchanged"])
    log.info("  Deactivated:    %d", inactive_count)
    log.info("-" * 60)

    return {
        "pages": pages_scraped,
        "found": len(listings),
        "new": stats["new"],
        "updated": stats["updated"],
    }


def export_csv(db_path: str, output_path: str = "funda_export.csv") -> None:
    """Export active listings from SQLite to CSV."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM listings WHERE is_active = 1 ORDER BY first_seen DESC"
    ).fetchall()
    conn.close()

    if not rows:
        log.warning("No active listings to export")
        return

    keys = rows[0].keys()
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(dict(row))

    log.info("Exported %d listings -> %s", len(rows), output_path)


def show_stats(db_path: str) -> None:
    """Print database statistics."""
    conn = sqlite3.connect(db_path)
    total = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    active = conn.execute("SELECT COUNT(*) FROM listings WHERE is_active = 1").fetchone()[0]
    inactive = conn.execute("SELECT COUNT(*) FROM listings WHERE is_active = 0").fetchone()[0]
    runs = conn.execute("SELECT COUNT(*) FROM scrape_runs").fetchone()[0]
    last_run = conn.execute("SELECT MAX(run_at) FROM scrape_runs").fetchone()[0]

    cities = conn.execute(
        "SELECT city, COUNT(*) as cnt FROM listings WHERE is_active = 1 GROUP BY city ORDER BY cnt DESC"
    ).fetchall()

    conn.close()

    print(f"\n{'='*50}")
    print(f"  Funda Database Stats: {db_path}")
    print(f"{'='*50}")
    print(f"  Total listings:    {total}")
    print(f"  Active:            {active}")
    print(f"  Inactive:          {inactive}")
    print(f"  Scrape runs:       {runs}")
    print(f"  Last run:          {last_run or 'never'}")
    print(f"\n  Active listings by city:")
    for row in cities:
        print(f"    {row[0]}: {row[1]}")
    print(f"{'='*50}\n")


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Funda.nl API Scraper — Elasticsearch search endpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Initial full load
  python funda_api_scraper.py --city amsterdam --type buy --min-price 325000 --max-price 400000

  # Daily delta (nightly cron)
  python funda_api_scraper.py --city amsterdam --type buy --min-price 325000 --max-price 400000 --delta

  # Multiple cities
  python funda_api_scraper.py --city amsterdam --type buy
  python funda_api_scraper.py --city rotterdam --type buy

  # Export to CSV
  python funda_api_scraper.py --export

  # Show database stats
  python funda_api_scraper.py --stats
        """,
    )

    # Search params
    parser.add_argument("--city", default="amsterdam")
    parser.add_argument("--type", dest="search_type", default="buy", choices=["buy", "rent"])
    parser.add_argument("--min-price", type=int, default=None)
    parser.add_argument("--max-price", type=int, default=None)
    parser.add_argument("--max-pages", type=int, default=None, help="Limit pages (default: all)")
    parser.add_argument("--zoning", nargs="+", default=["residential"],
                        help="Zoning types: residential, commercial, etc.")
    parser.add_argument("--property-type", nargs="+", default=["house", "apartment"],
                        help="Property types: house, apartment, etc.")

    # Rate limiting
    parser.add_argument("--min-delay", type=float, default=1.0, help="Min seconds between requests")
    parser.add_argument("--max-delay", type=float, default=3.0, help="Max seconds between requests")

    # Database
    parser.add_argument("--db", default="funda.db", help="SQLite database path")

    # Modes
    parser.add_argument("--delta", action="store_true", help="Only fetch new listings (skip deactivation)")
    parser.add_argument("--export", action="store_true", help="Export active listings to CSV")
    parser.add_argument("--stats", action="store_true", help="Show database statistics")
    parser.add_argument("--export-path", default="funda_export.csv")

    args = parser.parse_args()

    if args.stats:
        show_stats(args.db)
    elif args.export:
        export_csv(args.db, args.export_path)
    else:
        config = ScraperConfig(
            city=args.city,
            search_type=args.search_type,
            min_price=args.min_price,
            max_price=args.max_price,
            max_pages=args.max_pages,
            object_types=args.zoning,
            property_types=args.property_type,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            db_path=args.db,
            delta_mode=args.delta,
        )
        run_scrape(config)
