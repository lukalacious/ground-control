"""
Undervalue Scorer for Ground Control listings.

Scoring weights (redistributed from gen1 — WOZ dropped since API doesn't expose it):
  - Price per m2 vs neighbourhood average: 40%
  - Price per m2 vs city average:          30%
  - Days on market:                        30%

Higher score = more undervalued = better deal.
"""

import sqlite3
from datetime import datetime, timezone

WEIGHTS = {
    "vs_neighbourhood": 0.40,
    "vs_city": 0.30,
    "days_on_market": 0.30,
}


def score_listings(db_path: str) -> list[dict]:
    """Score all active listings and return sorted list (highest score first)."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # City-wide avg price/m2
    city_row = conn.execute(
        "SELECT avg_price_m2 FROM city_stats ORDER BY calculated_at DESC LIMIT 1"
    ).fetchone()
    city_avg_m2 = city_row["avg_price_m2"] if city_row else None

    # Neighbourhood avg price/m2 lookup
    hood_stats = {}
    for row in conn.execute("SELECT neighbourhood, avg_price_m2 FROM neighbourhood_stats"):
        hood_stats[row["neighbourhood"]] = row["avg_price_m2"]

    # Score all listings (including sold/inactive for dashboard filtering)
    listings = conn.execute(
        """SELECT global_id, address, city, postcode, neighbourhood, price, price_numeric,
                  listing_url, detail_url, agent_name, image_url,
                  living_area, plot_area, bedrooms, energy_label, object_type,
                  construction_type, first_seen, last_seen, is_active, previous_price,
                  availability_status, predicted_price, residual
           FROM listings WHERE price_numeric > 0"""
    ).fetchall()

    now = datetime.now(timezone.utc)
    scored = []

    for listing in listings:
        row = dict(listing)
        score = 0.0
        details = {}

        # Price per m2
        price_m2 = None
        if row["living_area"] and row["living_area"] > 0:
            price_m2 = row["price_numeric"] / row["living_area"]
            row["price_m2"] = round(price_m2, 1)

        if price_m2:
            # vs neighbourhood
            hood_avg = hood_stats.get(row["neighbourhood"])
            if hood_avg and hood_avg > 0:
                diff = (hood_avg - price_m2) / hood_avg
                score += diff * WEIGHTS["vs_neighbourhood"] * 100
                details["vs_neighbourhood_pct"] = round(diff * 100, 1)

            # vs city
            if city_avg_m2 and city_avg_m2 > 0:
                diff = (city_avg_m2 - price_m2) / city_avg_m2
                score += diff * WEIGHTS["vs_city"] * 100
                details["vs_city_pct"] = round(diff * 100, 1)

        # Days on market
        days_on_market = 0
        if row["first_seen"]:
            try:
                first = datetime.fromisoformat(row["first_seen"].replace("Z", "+00:00"))
                days_on_market = max(0, (now - first).days)
            except (ValueError, TypeError):
                pass
        days_score = min(days_on_market, 90) / 90 * WEIGHTS["days_on_market"] * 100
        score += days_score
        details["days_on_market"] = days_on_market

        row["score"] = round(score, 2)
        row["score_details"] = details
        if price_m2 is None:
            row["price_m2"] = None

        scored.append(row)

    conn.close()
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored
