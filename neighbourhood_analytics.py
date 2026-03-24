"""
Ground Control — Neighbourhood Analytics
=========================================
Computes deep neighbourhood statistics: percentiles, trends, comparables.

Usage:
    python neighbourhood_analytics.py           # Recompute all analytics
    python neighbourhood_analytics.py --dry-run # Print without writing
"""

import argparse
import json
import logging
import statistics
from datetime import datetime, timezone

from db import get_dict_cursor, close_pool

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("neighbourhood-analytics")

MIN_LISTINGS = 3  # Minimum listings per neighbourhood to compute stats


# ──────────────────────────────────────────────────────────────────────
# Percentile helper
# ──────────────────────────────────────────────────────────────────────

def _percentile(data: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100) of a sorted list."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c >= len(sorted_data):
        return sorted_data[-1]
    d0 = sorted_data[f] * (c - k)
    d1 = sorted_data[c] * (k - f)
    return d0 + d1


# ──────────────────────────────────────────────────────────────────────
# Analytics computation
# ──────────────────────────────────────────────────────────────────────

def compute_analytics(dry_run: bool = False) -> dict:
    """Recompute neighbourhood analytics for all neighbourhoods."""
    stats = {"neighbourhoods": 0, "listings_covered": 0}

    # Fetch all active listings with valid price and area
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT global_id, neighbourhood, price_numeric, living_area, first_seen
            FROM listings
            WHERE is_active = true
              AND price_numeric > 0
              AND living_area > 0
              AND neighbourhood IS NOT NULL
              AND neighbourhood != ''
            ORDER BY neighbourhood, first_seen
        """)
        rows = cur.fetchall()

    log.info("Loaded %d active listings with valid data", len(rows))

    # Group by neighbourhood
    by_hood: dict[str, list[dict]] = {}
    for row in rows:
        hood = row["neighbourhood"]
        if hood not in by_hood:
            by_hood[hood] = []
        by_hood[hood].append(dict(row))

    log.info("Found %d unique neighbourhoods", len(by_hood))

    now = datetime.now(timezone.utc).isoformat()
    analytics_rows = []

    for hood, listings in by_hood.items():
        if len(listings) < MIN_LISTINGS:
            continue

        prices_m2 = [l["price_numeric"] / l["living_area"] for l in listings]
        prices = [l["price_numeric"] for l in listings]

        # Percentiles of price_m2
        p10 = round(_percentile(prices_m2, 10), 2)
        p25 = round(_percentile(prices_m2, 25), 2)
        p50 = round(_percentile(prices_m2, 50), 2)
        p75 = round(_percentile(prices_m2, 75), 2)
        p90 = round(_percentile(prices_m2, 90), 2)
        avg_m2 = round(statistics.mean(prices_m2), 2)

        # Price stats
        median_price = round(statistics.median(prices), 2)
        min_price = min(prices)
        max_price = max(prices)
        listing_count = len(listings)

        # Trend data: group by month, compute avg price_m2
        monthly: dict[str, list[float]] = {}
        for l in listings:
            fs = l["first_seen"]
            if fs:
                month_key = str(fs)[:7]  # "2026-03"
                if month_key not in monthly:
                    monthly[month_key] = []
                monthly[month_key].append(l["price_numeric"] / l["living_area"])

        trend_data = []
        for month_key in sorted(monthly.keys()):
            trend_data.append({
                "month": month_key,
                "avg_price_m2": round(statistics.mean(monthly[month_key]), 2),
                "count": len(monthly[month_key]),
            })

        analytics_rows.append({
            "neighbourhood": hood,
            "p10_price_m2": p10,
            "p25_price_m2": p25,
            "p50_price_m2": p50,
            "p75_price_m2": p75,
            "p90_price_m2": p90,
            "avg_price_m2": avg_m2,
            "median_price": median_price,
            "min_price": min_price,
            "max_price": max_price,
            "listing_count": listing_count,
            "trend_data": json.dumps(trend_data),
            "calculated_at": now,
        })

        stats["neighbourhoods"] += 1
        stats["listings_covered"] += listing_count

    if dry_run:
        log.info("[DRY RUN] Would upsert %d neighbourhood records:", len(analytics_rows))
        for a in analytics_rows:
            log.info("  %s: %d listings, avg=%.0f/m2, median=%.0f",
                     a["neighbourhood"], a["listing_count"],
                     a["avg_price_m2"], a["median_price"])
        return stats

    # Upsert into neighbourhood_analytics
    with get_dict_cursor() as cur:
        for a in analytics_rows:
            cur.execute("""
                INSERT INTO neighbourhood_analytics
                    (neighbourhood, p10_price_m2, p25_price_m2, p50_price_m2,
                     p75_price_m2, p90_price_m2, avg_price_m2, median_price,
                     min_price, max_price, listing_count, trend_data, calculated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (neighbourhood)
                DO UPDATE SET
                    p10_price_m2 = EXCLUDED.p10_price_m2,
                    p25_price_m2 = EXCLUDED.p25_price_m2,
                    p50_price_m2 = EXCLUDED.p50_price_m2,
                    p75_price_m2 = EXCLUDED.p75_price_m2,
                    p90_price_m2 = EXCLUDED.p90_price_m2,
                    avg_price_m2 = EXCLUDED.avg_price_m2,
                    median_price = EXCLUDED.median_price,
                    min_price = EXCLUDED.min_price,
                    max_price = EXCLUDED.max_price,
                    listing_count = EXCLUDED.listing_count,
                    trend_data = EXCLUDED.trend_data,
                    calculated_at = EXCLUDED.calculated_at
            """, (
                a["neighbourhood"], a["p10_price_m2"], a["p25_price_m2"],
                a["p50_price_m2"], a["p75_price_m2"], a["p90_price_m2"],
                a["avg_price_m2"], a["median_price"], a["min_price"],
                a["max_price"], a["listing_count"], a["trend_data"],
                a["calculated_at"],
            ))

    log.info("Upserted %d neighbourhood records (%d listings covered)",
             stats["neighbourhoods"], stats["listings_covered"])
    return stats


# ──────────────────────────────────────────────────────────────────────
# Query helpers
# ──────────────────────────────────────────────────────────────────────

def get_property_percentile(neighbourhood: str, price_m2: float) -> float:
    """
    Return the 0-100 percentile of a price_m2 value within a neighbourhood.
    Lower percentile = cheaper relative to neighbourhood.
    """
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT price_numeric, living_area
            FROM listings
            WHERE is_active = true
              AND neighbourhood = %s
              AND price_numeric > 0
              AND living_area > 0
        """, (neighbourhood,))
        rows = cur.fetchall()

    if not rows:
        return 50.0  # Default to median if no data

    prices_m2 = sorted(l["price_numeric"] / l["living_area"] for l in rows)
    below = sum(1 for p in prices_m2 if p < price_m2)
    return round((below / len(prices_m2)) * 100, 1)


def get_comparables(global_id: int, n: int = 5) -> list[dict]:
    """
    Find N most similar listings in the same neighbourhood by
    |price_m2 difference| + |living_area difference|.
    """
    # Get the target listing
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT global_id, neighbourhood, price_numeric, living_area
            FROM listings
            WHERE global_id = %s
        """, (global_id,))
        target = cur.fetchone()

    if not target or not target["neighbourhood"] or not target["living_area"]:
        return []

    target_m2 = target["price_numeric"] / target["living_area"]
    target_area = target["living_area"]

    # Get all active listings in the same neighbourhood
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT global_id, address, neighbourhood, price_numeric, living_area,
                   bedrooms, detail_url
            FROM listings
            WHERE is_active = true
              AND neighbourhood = %s
              AND global_id != %s
              AND price_numeric > 0
              AND living_area > 0
        """, (target["neighbourhood"], global_id))
        candidates = cur.fetchall()

    if not candidates:
        return []

    # Score by combined normalised distance
    scored = []
    for c in candidates:
        c = dict(c)
        c_m2 = c["price_numeric"] / c["living_area"]
        c["price_m2"] = round(c_m2, 1)

        # Normalised differences (0-1 scale roughly)
        m2_diff = abs(c_m2 - target_m2) / max(target_m2, 1)
        area_diff = abs(c["living_area"] - target_area) / max(target_area, 1)
        c["similarity_score"] = round(m2_diff + area_diff, 4)

        scored.append(c)

    scored.sort(key=lambda x: x["similarity_score"])
    return scored[:n]


# ──────────────────────────────────────────────────────────────────────
# Check for unique constraint on neighbourhood (needed for upsert)
# ──────────────────────────────────────────────────────────────────────

def _ensure_unique_constraint():
    """Ensure neighbourhood_analytics has a unique constraint on neighbourhood."""
    with get_dict_cursor() as cur:
        cur.execute("""
            SELECT COUNT(*) AS cnt
            FROM pg_indexes
            WHERE tablename = 'neighbourhood_analytics'
              AND indexdef LIKE '%neighbourhood%'
              AND indexdef LIKE '%UNIQUE%'
        """)
        row = cur.fetchone()
        if row["cnt"] == 0:
            log.info("Creating unique index on neighbourhood_analytics.neighbourhood")
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_neighbourhood_analytics_hood
                ON neighbourhood_analytics (neighbourhood)
            """)


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground Control — Neighbourhood Analytics")
    parser.add_argument("--dry-run", action="store_true", help="Print without writing to DB")
    args = parser.parse_args()

    try:
        _ensure_unique_constraint()
        compute_analytics(dry_run=args.dry_run)
    finally:
        close_pool()
