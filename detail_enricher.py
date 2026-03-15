"""
Ground Control — Detail Page Enricher
======================================
Fetches individual Funda listing pages and extracts exhaustive metadata
not available from the Elasticsearch search API.

New fields extracted:
  - description         Full property description text
  - year_built          Construction year (Bouwjaar)
  - num_rooms           Total rooms (Aantal kamers)
  - num_bathrooms       Bathroom count (Aantal badkamers)
  - bathroom_features   Bathroom fittings (Badkamervoorzieningen)
  - num_floors          Number of storeys in unit (Aantal woonlagen)
  - floor_level         Which floor the unit is on (Gelegen op)
  - outdoor_area_m2     Terrace/balcony/garden m² (Gebouwgebonden buitenruimte + Tuin)
  - volume_m3           Volume in m³ (Inhoud)
  - amenities           Extras — lift, solar panels, etc. (Voorzieningen)
  - insulation          Insulation type (Isolatie)
  - heating             Heating type (Verwarming)
  - location_type       Park/water/quiet street etc. (Ligging)
  - has_balcony         True if balcony or roof terrace present
  - balcony_type        e.g. 'balkon', 'dakterras', 'both'
  - parking_type        Parking availability (Soort parkeergelegenheid)
  - vve_contribution    VvE monthly service costs (free text)
  - erfpacht            Leasehold / erfpacht info (free text)
  - acceptance          Delivery date / oplevering (Aanvaarding)
  - photo_urls          JSON array of all photo URLs from the page
  - energy_label        Energy rating A-G (Energielabel)
  - construction_type   "Bestaande bouw" or "Nieuwbouw" (Soort bouw)
  - object_type         Property type (Soort woning / Soort appartement)
  - address             Street + house number from page header
  - postcode            Dutch postcode from page header
  - city                City name from page header
  - neighbourhood       Neighbourhood name from page header
  - detail_enriched     Boolean flag — enrichment complete
  - detail_enriched_at  Timestamp of last enrichment run

Usage:
    # Enrich all unenriched listings
    python detail_enricher.py

    # Re-enrich all listings (force refresh)
    python detail_enricher.py --force

    # Enrich a single listing by global_id
    python detail_enricher.py --id 42968121

    # Dry-run — parse and print without writing
    python detail_enricher.py --id 42968121 --dry-run

    # Limit batch size
    python detail_enricher.py --limit 50
"""

import argparse
import json
import logging
import random
import re
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from curl_cffi import requests as http_client
from lxml import html as lhtml

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

DETAIL_BASE = "https://www.funda.nl"
PHOTO_WIDTH = 1440
MIN_DELAY = 2.0
MAX_DELAY = 4.5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-7s │ %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("detail-enricher")


# ──────────────────────────────────────────────────────────────────────
# Schema migration — add enrichment columns to listings table
# ──────────────────────────────────────────────────────────────────────

ENRICHMENT_COLUMNS = {
    "description":        "TEXT",
    "energy_label":       "TEXT",
    "construction_type":  "TEXT",
    "object_type":        "TEXT",
    "address":            "TEXT",
    "postcode":           "TEXT",
    "city":               "TEXT",
    "neighbourhood":      "TEXT",
    "year_built":         "TEXT",
    "num_rooms":          "INTEGER",
    "num_bathrooms":      "INTEGER",
    "bathroom_features":  "TEXT",
    "num_floors":         "INTEGER",
    "floor_level":        "TEXT",
    "outdoor_area_m2":    "INTEGER",
    "volume_m3":          "INTEGER",
    "amenities":          "TEXT",
    "insulation":         "TEXT",
    "heating":            "TEXT",
    "location_type":      "TEXT",
    "has_balcony":        "BOOLEAN DEFAULT 0",
    "balcony_type":       "TEXT",
    "parking_type":       "TEXT",
    "vve_contribution":   "TEXT",
    "erfpacht":           "TEXT",
    "acceptance":         "TEXT",
    "photo_urls":         "TEXT",
    "detail_enriched":    "BOOLEAN DEFAULT 0",
    "detail_enriched_at": "DATETIME",
    "status_changed_at":  "DATETIME",
}


def migrate_schema(conn: sqlite3.Connection) -> None:
    """Add enrichment columns if not present."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(listings)").fetchall()}
    added = []
    for col, col_type in ENRICHMENT_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {col_type}")
            added.append(col)
    if added:
        conn.commit()
        log.info("Schema: added %d new column(s): %s", len(added), ", ".join(added))
    else:
        log.info("Schema: all enrichment columns present")


# ──────────────────────────────────────────────────────────────────────
# HTTP client
# ──────────────────────────────────────────────────────────────────────

def make_session() -> http_client.Session:
    return http_client.Session(impersonate="safari15_5")


def fetch_detail_page(session: http_client.Session, detail_url: str, retries: int = 3) -> tuple[Optional[str], int]:
    """Fetch a listing detail page. Returns (HTML, status_code) or (None, status_code) on failure."""
    # Build full URL if relative
    url = detail_url if detail_url.startswith("http") else f"{DETAIL_BASE}{detail_url}"

    last_status = 0
    for attempt in range(1, retries + 1):
        try:
            resp = session.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Referer": "https://www.funda.nl/zoeken/koop/",
                "Cache-Control": "no-cache",
            }, timeout=20)

            last_status = resp.status_code
            if resp.status_code == 200:
                return resp.text, 200
            elif resp.status_code in (404, 410):
                log.warning("  %s — listing gone (%d)", url, resp.status_code)
                return None, resp.status_code
            elif resp.status_code == 429:
                wait = 10 * attempt
                log.warning("  429 rate limited — waiting %ds (attempt %d/%d)", wait, attempt, retries)
                time.sleep(wait)
            else:
                log.warning("  HTTP %d on %s (attempt %d)", resp.status_code, url, attempt)
                time.sleep(2 ** attempt)

        except Exception as e:
            log.warning("  Fetch error attempt %d: %s", attempt, e)
            time.sleep(2 ** attempt)

    return None, last_status


# ──────────────────────────────────────────────────────────────────────
# Parsers
# ──────────────────────────────────────────────────────────────────────

def _parse_int(text: str) -> Optional[int]:
    """Extract first integer from a text string."""
    if not text:
        return None
    m = re.search(r'\d+', text.replace('.', '').replace(',', ''))
    return int(m.group()) if m else None


def _text(el) -> str:
    return (el.text_content() or "").strip()


def build_dl_map(page) -> dict[str, str]:
    """Build a flat label→value dict from all <dl><dt><dd> pairs on the page."""
    result = {}
    for dl in page.cssselect("dl"):
        dts = dl.cssselect("dt")
        dds = dl.cssselect("dd")
        for dt, dd in zip(dts, dds):
            label = _text(dt)
            value = _text(dd)
            if label:
                result[label] = value
    return result


def extract_description(page) -> str:
    """Find the 'Omschrijving' section and extract clean description text."""
    # Strategy 1: look for paragraphs inside the Omschrijving section
    for section in page.cssselect("section, article, div"):
        headers = section.cssselect("h2, h3")
        if not headers or "omschrijving" not in _text(headers[0]).lower():
            continue
        # Collect <p> elements inside this section
        paras = [_text(p) for p in section.cssselect("p") if len(_text(p)) > 20]
        if paras:
            return "\n\n".join(paras)
        # Fallback: take raw text but strip at 'Advertentie' or 'Kenmerken'
        heading_text = _text(headers[0])
        full_text = _text(section).replace(heading_text, "", 1).strip()
        for stop_marker in ["Advertentie", "Kenmerken", "Overdracht", "Lees de volledige"]:
            idx = full_text.find(stop_marker)
            if idx > 50:
                full_text = full_text[:idx].strip()
                break
        if len(full_text) > 30:
            return full_text
    return ""


def extract_photos(page) -> list[str]:
    """Extract all high-res photo URLs from the page."""
    photos = []
    seen = set()
    for img in page.cssselect("img"):
        src = img.get("src", "") or img.get("data-src", "")
        if "funda" in src and ("valentina" in src or "cloud.funda" in src):
            # Normalise to 1440px width
            src = re.sub(r'width=\d+', f'width={PHOTO_WIDTH}', src)
            if src not in seen:
                seen.add(src)
                photos.append(src)
    return photos


def extract_vve(html_text: str) -> str:
    """Extract VvE / service cost info from raw HTML."""
    idx = html_text.find("VvE bijdrage")
    if idx < 0:
        idx = html_text.find("Servicekosten")
    if idx < 0:
        return ""
    # Grab surrounding context and strip tags
    snippet = html_text[idx: idx + 500]
    cleaned = re.sub(r'<[^>]+>', ' ', snippet)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:300]


def extract_erfpacht(html_text: str) -> str:
    """Extract erfpacht (leasehold) information."""
    idx = html_text.find("Erfpacht")
    if idx < 0:
        return ""
    snippet = html_text[idx: idx + 600]
    cleaned = re.sub(r'<[^>]+>', ' ', snippet)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned[:400]


def extract_energy_label(dl: dict) -> Optional[str]:
    """Extract clean energy label (A++++..G) from the Energielabel dd text.

    The dd often includes button text like "B Wat betekent dit?" — regex
    pulls just the label grade.
    """
    raw = dl.get("Energielabel", "")
    if not raw:
        return None
    m = re.match(r'^([A-G]\+{0,4})', raw.strip())
    return m.group(1) if m else None


def extract_header_data(page) -> dict:
    """Parse the <h1> header for address, postcode, city, neighbourhood."""
    result: dict[str, Optional[str]] = {
        "address": None,
        "postcode": None,
        "city": None,
        "neighbourhood": None,
    }
    h1 = page.cssselect("h1")
    if not h1:
        return result

    h1 = h1[0]
    spans = h1.cssselect("span")

    # First span: street address (e.g. "Transvaalstraat 62-4")
    if len(spans) >= 1:
        result["address"] = _text(spans[0]) or None

    # Second span: "1092 HN Amsterdam" — split into postcode + city
    if len(spans) >= 2:
        loc_text = _text(spans[1])
        pc_match = re.search(r'(\d{4}\s?[A-Z]{2})', loc_text)
        if pc_match:
            result["postcode"] = pc_match.group(1)
            result["city"] = loc_text[pc_match.end():].strip() or None
        elif loc_text:
            # No postcode found — entire text is likely the city
            result["city"] = loc_text

    # Neighbourhood: child <a> with aria-label or text
    links = h1.cssselect("a")
    for link in links:
        aria = (link.get("aria-label") or "").strip()
        if aria:
            result["neighbourhood"] = aria
            break
        link_text = _text(link)
        if link_text:
            result["neighbourhood"] = link_text
            break

    return result


def parse_detail(html_text: str, global_id: int) -> dict:
    """Parse a Funda detail page HTML into enrichment fields."""
    page = lhtml.fromstring(html_text)
    dl = build_dl_map(page)

    # ── Core fields from dl map ─────────────────────────────────────

    year_built = dl.get("Bouwjaar", "").strip() or None

    # Rooms: "3 kamers (2 slaapkamers)" → 3 rooms, 2 bedrooms
    rooms_raw = dl.get("Aantal kamers", "")
    num_rooms = _parse_int(rooms_raw.split("kamers")[0]) if "kamers" in rooms_raw else _parse_int(rooms_raw)

    # Bathrooms: "1 badkamer en 1 apart toilet" → 1
    bath_raw = dl.get("Aantal badkamers", "")
    num_bathrooms = _parse_int(bath_raw.split("badkamer")[0]) if "badkamer" in bath_raw else _parse_int(bath_raw)
    bathroom_features = dl.get("Badkamervoorzieningen", "").strip() or None

    # Floors: "2 woonlagen" → 2
    floors_raw = dl.get("Aantal woonlagen", "")
    num_floors = _parse_int(floors_raw)

    # Floor level: "1e woonlaag" → as text
    floor_level = dl.get("Gelegen op", "").strip() or None

    # Outdoor area: "Gebouwgebonden buitenruimte" or "Tuin"
    outdoor_raw = dl.get("Gebouwgebonden buitenruimte", "") or dl.get("Tuin oppervlakte", "") or dl.get("Tuin", "")
    outdoor_area_m2 = _parse_int(outdoor_raw) if "m²" in outdoor_raw or outdoor_raw.strip().isdigit() else None

    # Volume
    volume_raw = dl.get("Inhoud", "")
    volume_m3 = _parse_int(volume_raw)

    # Amenities
    amenities = dl.get("Voorzieningen", "").strip() or None

    # Energy
    insulation = dl.get("Isolatie", "").strip() or None
    heating = dl.get("Verwarming", "").strip() or None

    # Location type
    location_type = dl.get("Ligging", "").strip() or None

    # Balcony
    balcony_raw = (dl.get("Balkon/dakterras", "") or dl.get("Buitenruimte", "")).lower()
    has_balcony = bool(balcony_raw and balcony_raw != "geen")
    if "dakterras" in balcony_raw and "balkon" in balcony_raw:
        balcony_type = "both"
    elif "dakterras" in balcony_raw:
        balcony_type = "rooftop"
    elif "balkon" in balcony_raw:
        balcony_type = "balcony"
    else:
        balcony_type = None

    # Parking
    parking_type = dl.get("Soort parkeergelegenheid", "").strip() or None

    # Acceptance
    acceptance = dl.get("Aanvaarding", "").strip() or None
    if acceptance and "log in" in acceptance.lower():
        acceptance = None  # behind login

    # Energy label, construction type, object type
    energy_label = extract_energy_label(dl)
    construction_type = dl.get("Soort bouw", "").strip() or None
    object_type = (dl.get("Soort appartement", "") or dl.get("Soort woning", "")).strip() or None

    # Header: address, postcode, city, neighbourhood
    header = extract_header_data(page)

    # ── Price from page text ─────────────────────────────────────────
    page_text = page.text_content() if page is not None else ""
    price_match = re.search(r'€\s?(\d{1,3}(?:\.\d{3})*)', page_text)
    price_numeric = int(price_match.group(1).replace('.', '')) if price_match else None

    # ── Rich text fields ────────────────────────────────────────────

    description = extract_description(page)
    vve_contribution = extract_vve(html_text)
    erfpacht = extract_erfpacht(html_text)
    photo_urls = extract_photos(page)

    result = {
        "global_id":          global_id,
        "description":        description or None,
        "energy_label":       energy_label,
        "construction_type":  construction_type,
        "object_type":        object_type,
        "year_built":         year_built,
        "num_rooms":          num_rooms,
        "num_bathrooms":      num_bathrooms,
        "bathroom_features":  bathroom_features,
        "num_floors":         num_floors,
        "floor_level":        floor_level,
        "outdoor_area_m2":    outdoor_area_m2,
        "volume_m3":          volume_m3,
        "amenities":          amenities,
        "insulation":         insulation,
        "heating":            heating,
        "location_type":      location_type,
        "has_balcony":        has_balcony,
        "balcony_type":       balcony_type,
        "parking_type":       parking_type,
        "vve_contribution":   vve_contribution or None,
        "erfpacht":           erfpacht or None,
        "acceptance":         acceptance,
        "photo_urls":         json.dumps(photo_urls) if photo_urls else None,
        "detail_enriched":    True,
        "detail_enriched_at": datetime.now(timezone.utc).isoformat(),
    }

    # Only include price keys if detail page actually has a price —
    # avoids overwriting prices already extracted from search cards.
    if price_numeric is not None:
        result["price_numeric"] = price_numeric
        result["price"] = f"€ {price_numeric:,}"

    # Only include header fields if non-empty — don't overwrite existing data with blanks.
    for key in ("address", "postcode", "city", "neighbourhood"):
        if header.get(key):
            result[key] = header[key]

    return result


# ──────────────────────────────────────────────────────────────────────
# Database writes
# ──────────────────────────────────────────────────────────────────────

def write_enrichment(conn: sqlite3.Connection, data: dict) -> None:
    """Write enrichment data back to the listings table."""
    fields = [k for k in data if k != "global_id"]
    set_clause = ", ".join(f"{f} = ?" for f in fields)
    values = [data[f] for f in fields]
    values.append(data["global_id"])
    conn.execute(
        f"UPDATE listings SET {set_clause} WHERE global_id = ?",
        values,
    )
    conn.commit()


def get_unenriched(conn: sqlite3.Connection, limit: Optional[int] = None,
                   force: bool = False, specific_id: Optional[int] = None) -> list[tuple[int, str]]:
    """Return (global_id, detail_url) for listings needing enrichment."""
    if specific_id:
        rows = conn.execute(
            "SELECT global_id, detail_url FROM listings WHERE global_id = ? AND detail_url != ''",
            (specific_id,),
        ).fetchall()
    elif force:
        query = "SELECT global_id, detail_url FROM listings WHERE detail_url != '' ORDER BY first_seen DESC"
        if limit:
            query += f" LIMIT {limit}"
        rows = conn.execute(query).fetchall()
    else:
        query = """
            SELECT global_id, detail_url FROM listings
            WHERE (detail_enriched IS NULL OR detail_enriched = 0)
              AND detail_url != ''
              AND is_active = 1
            ORDER BY first_seen DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        rows = conn.execute(query).fetchall()
    return [(r[0], r[1]) for r in rows]


# ──────────────────────────────────────────────────────────────────────
# Main enrichment loop
# ──────────────────────────────────────────────────────────────────────

def run_enrichment(
    db_path: str,
    limit: Optional[int] = None,
    force: bool = False,
    specific_id: Optional[int] = None,
    dry_run: bool = False,
) -> dict:
    """Run enrichment on unenriched listings."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    migrate_schema(conn)

    targets = get_unenriched(conn, limit=limit, force=force, specific_id=specific_id)
    total = len(targets)
    log.info("=" * 60)
    log.info("Detail Enricher")
    log.info("  Targets: %d listings", total)
    log.info("  Mode: %s", "dry-run" if dry_run else ("force" if force else "new only"))
    log.info("=" * 60)

    if not targets:
        log.info("Nothing to enrich.")
        conn.close()
        return {"total": 0, "success": 0, "failed": 0}

    session = make_session()
    success = failed = 0

    for i, (global_id, detail_url) in enumerate(targets, 1):
        log.info("[%d/%d] Enriching %d — %s", i, total, global_id, detail_url)

        # Rate limit between requests
        if i > 1:
            delay = random.uniform(MIN_DELAY, MAX_DELAY)
            log.info("  Waiting %.1fs...", delay)
            time.sleep(delay)

        html_text, status_code = fetch_detail_page(session, detail_url)
        if not html_text:
            if status_code in (404, 410):
                # Listing removed from Funda — mark as sold
                now = datetime.now(timezone.utc).isoformat()
                conn.execute("""UPDATE listings SET is_active = 0, availability_status = 'sold',
                    status_changed_at = ?, detail_enriched = 1, detail_enriched_at = ?
                    WHERE global_id = ? AND availability_status != 'sold'""",
                    (now, now, global_id))
                conn.commit()
                log.info("  Marked as sold (HTTP %d)", status_code)
            else:
                log.warning("  Failed to fetch — skipping")
            failed += 1
            continue

        try:
            data = parse_detail(html_text, global_id)
        except Exception as e:
            log.error("  Parse error: %s", e)
            failed += 1
            continue

        if dry_run:
            log.info("  [DRY RUN] Parsed:")
            for k, v in data.items():
                if k not in ("global_id", "detail_enriched_at", "photo_urls"):
                    if v:
                        log.info("    %-25s %s", k + ":", v)
            if data.get("photo_urls"):
                urls = json.loads(data["photo_urls"])
                log.info("    %-25s %d photos", "photo_urls:", len(urls))
        else:
            write_enrichment(conn, data)
            enriched_fields = [k for k, v in data.items()
                               if v and k not in ("global_id", "detail_enriched", "detail_enriched_at")]
            log.info("  ✓ Saved: %s", ", ".join(enriched_fields[:8]))

        success += 1

    conn.close()
    log.info("-" * 60)
    log.info("DONE — success: %d, failed: %d / %d", success, failed, total)
    return {"total": total, "success": success, "failed": failed}


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Ground Control — Detail Page Enricher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enrich all unenriched active listings
  python detail_enricher.py

  # Force re-enrich everything
  python detail_enricher.py --force

  # Enrich a specific listing (by global_id)
  python detail_enricher.py --id 42968121

  # Dry run — parse and print without writing to DB
  python detail_enricher.py --id 42968121 --dry-run

  # Batch limit
  python detail_enricher.py --limit 100
        """,
    )
    parser.add_argument("--db",       default="ground_control.db")
    parser.add_argument("--limit",    type=int, default=None)
    parser.add_argument("--force",    action="store_true")
    parser.add_argument("--id",       type=int, default=None, dest="specific_id")
    parser.add_argument("--dry-run",  action="store_true")
    args = parser.parse_args()

    run_enrichment(
        db_path=args.db,
        limit=args.limit,
        force=args.force,
        specific_id=args.specific_id,
        dry_run=args.dry_run,
    )
