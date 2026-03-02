#!/usr/bin/env python3
"""Geocode Amsterdam neighbourhood names using the PDOK Locatieserver API.

Resolves neighbourhood names from the database to lat/lng coordinates and caches
results in neighbourhood_coords.json. Only geocodes new/missing names on
subsequent runs.

Cache format: {"name": [lat, lng, "wijknaam"]}

PDOK Locatieserver is the Dutch government's free geocoding service — no API
key required.
"""

import argparse
import json
import re
import sqlite3
import time
import urllib.request
import urllib.parse
from pathlib import Path

DB_PATH = Path(__file__).parent / "ground_control.db"
CACHE_PATH = Path(__file__).parent / "neighbourhood_coords.json"

PDOK_BASE = "https://api.pdok.nl/bzk/locatieserver/search/v3_1/free"

# Amsterdam bounding box for validation
AMS_LAT_MIN, AMS_LAT_MAX = 52.28, 52.43
AMS_LNG_MIN, AMS_LNG_MAX = 4.73, 5.02

RATE_LIMIT = 0.2  # seconds between API calls


def get_neighbourhoods(db_path: Path) -> list[str]:
    """Get distinct neighbourhood names from the database."""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT DISTINCT neighbourhood FROM neighbourhood_stats ORDER BY neighbourhood"
    ).fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]


def load_cache(cache_path: Path) -> dict[str, list[float]]:
    """Load existing geocode cache."""
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    return {}


def save_cache(cache_path: Path, cache: dict[str, list[float]]) -> None:
    """Save geocode cache to JSON."""
    cache_path.write_text(
        json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def parse_centroid(wkt: str) -> tuple[float, float] | None:
    """Parse PDOK's WKT centroid 'POINT(lng lat)' → (lat, lng)."""
    m = re.match(r"POINT\(([\d.]+)\s+([\d.]+)\)", wkt)
    if not m:
        return None
    lng, lat = float(m.group(1)), float(m.group(2))
    # Validate within Amsterdam bbox
    if AMS_LAT_MIN <= lat <= AMS_LAT_MAX and AMS_LNG_MIN <= lng <= AMS_LNG_MAX:
        return (lat, lng)
    return None


def query_pdok(query: str, fq_type: str = "buurt") -> tuple[float, float, str] | None:
    """Query PDOK Locatieserver and return (lat, lng, wijknaam) or None."""
    params = urllib.parse.urlencode({
        "q": query,
        "rows": "1",
        "fq": f"type:{fq_type}",
    })
    # Add Amsterdam municipality filter separately
    url = f"{PDOK_BASE}?{params}&fq=gemeentenaam:Amsterdam"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "GroundControl/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        docs = data.get("response", {}).get("docs", [])
        if docs and "centroide_ll" in docs[0]:
            coords = parse_centroid(docs[0]["centroide_ll"])
            if coords:
                wijknaam = docs[0].get("wijknaam", "") or ""
                return (coords[0], coords[1], wijknaam)
    except Exception as e:
        print(f"  API error for '{query}': {e}")
    return None


def geocode_name(name: str) -> tuple[float, float, str] | None:
    """Try multiple strategies to geocode a neighbourhood name.
    Returns (lat, lng, wijknaam) or None."""
    # Strategy 1: direct search as buurt
    result = query_pdok(f"{name} Amsterdam")
    if result:
        return result
    time.sleep(RATE_LIMIT)

    # Strategy 2: strip directional suffixes (-Noord, -Zuid, -Oost, -West, -Midden)
    stripped = re.sub(r"-(Noord|Zuid|Oost|West|Midden|Zuidoost|Noordwest|Noordoost|Zuidwest)$", "", name)
    if stripped != name:
        result = query_pdok(f"{stripped} Amsterdam")
        if result:
            return result
        time.sleep(RATE_LIMIT)

    # Strategy 3: try as wijk (district) instead of buurt
    result = query_pdok(f"{name} Amsterdam", fq_type="wijk")
    if result:
        return result
    time.sleep(RATE_LIMIT)

    # Strategy 4: try as adres (address/area)
    result = query_pdok(f"{name} Amsterdam", fq_type="adres")
    if result:
        return result

    return None


def needs_wijk(entry: list) -> bool:
    """Check if a cache entry is missing wijknaam (old 2-element format)."""
    return len(entry) < 3 or not entry[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Geocode neighbourhood names via PDOK")
    parser.add_argument("--force", action="store_true",
                        help="Re-geocode all entries (useful to backfill wijknaam)")
    args = parser.parse_args()

    neighbourhoods = get_neighbourhoods(DB_PATH)
    cache = load_cache(CACHE_PATH)

    if args.force:
        # Re-geocode everything to backfill wijknaam
        missing = neighbourhoods
        print(f"Force mode: re-geocoding all {len(missing)} neighbourhoods...")
    else:
        # Geocode new names + entries missing wijknaam
        missing = [n for n in neighbourhoods
                   if n not in cache or needs_wijk(cache.get(n, []))]

    if not missing:
        print(f"All {len(cache)} neighbourhoods already geocoded with wijk data.")
        return

    print(f"Geocoding {len(missing)} neighbourhoods ({len(cache)} in cache)...")

    found = 0
    skipped = []

    for i, name in enumerate(missing, 1):
        print(f"  [{i}/{len(missing)}] {name}...", end=" ", flush=True)

        result = geocode_name(name)
        if result:
            lat, lng, wijk = result
            cache[name] = [lat, lng, wijk]
            wijk_str = f" [{wijk}]" if wijk else ""
            print(f"→ ({lat:.4f}, {lng:.4f}){wijk_str}")
            found += 1
        else:
            print("→ SKIPPED (not found)")
            skipped.append(name)

        time.sleep(RATE_LIMIT)

    save_cache(CACHE_PATH, cache)

    # Summary
    wijk_count = len(set(e[2] for e in cache.values() if len(e) >= 3 and e[2]))
    print(f"\nDone: {found} geocoded, {len(skipped)} skipped, {len(cache)} total cached, {wijk_count} distinct wijken")
    if skipped:
        print(f"Skipped: {', '.join(skipped)}")


if __name__ == "__main__":
    main()
