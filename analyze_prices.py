#!/usr/bin/env python3
"""Analyze housing price data from funda.db."""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "funda.db"


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def print_header(title: str):
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def basic_stats(conn: sqlite3.Connection):
    print_header("BASIC STATISTICS")

    row = conn.execute("""
        SELECT
            COUNT(*)                                    AS total,
            SUM(is_active)                              AS active,
            COUNT(*) - SUM(is_active)                   AS inactive,
            printf('€%,d', AVG(price_numeric))          AS avg_price,
            printf('€%,d', MIN(price_numeric))          AS min_price,
            printf('€%,d', MAX(price_numeric))          AS max_price,
            printf('€%,d', median_price)                AS median_price,
            printf('€%,d', AVG(CASE WHEN living_area > 0 THEN price_numeric * 1.0 / living_area END)) AS avg_price_m2,
            printf('%.0f m²', AVG(CASE WHEN living_area > 0 THEN living_area END)) AS avg_area,
            printf('%.1f', AVG(CASE WHEN bedrooms > 0 THEN bedrooms END)) AS avg_bedrooms,
            COUNT(DISTINCT neighbourhood)               AS neighbourhoods
        FROM listings,
             (SELECT price_numeric AS median_price
              FROM listings
              WHERE price_numeric > 0
              ORDER BY price_numeric
              LIMIT 1 OFFSET (SELECT COUNT(*) / 2 FROM listings WHERE price_numeric > 0))
        WHERE price_numeric > 0
    """).fetchone()

    print(f"  Total listings:      {row['total']}")
    print(f"  Active listings:     {row['active']}")
    print(f"  Inactive listings:   {row['inactive']}")
    print(f"  Neighbourhoods:      {row['neighbourhoods']}")
    print(f"  Average price:       {row['avg_price']}")
    print(f"  Median price:        {row['median_price']}")
    print(f"  Min / Max price:     {row['min_price']} / {row['max_price']}")
    print(f"  Avg price per m²:    {row['avg_price_m2']}")
    print(f"  Avg living area:     {row['avg_area']}")
    print(f"  Avg bedrooms:        {row['avg_bedrooms']}")

    # Property type breakdown
    rows = conn.execute("""
        SELECT object_type, COUNT(*) AS cnt,
               printf('€%,d', AVG(price_numeric)) AS avg_price
        FROM listings WHERE price_numeric > 0
        GROUP BY object_type ORDER BY cnt DESC
    """).fetchall()

    print(f"\n  By property type:")
    for r in rows:
        print(f"    {r['object_type'] or 'unknown':20s}  {r['cnt']:>5}  avg {r['avg_price']}")


def neighbourhood_analysis(conn: sqlite3.Connection):
    print_header("PRICE DISTRIBUTION BY NEIGHBOURHOOD")

    rows = conn.execute("""
        SELECT
            neighbourhood,
            COUNT(*)                                     AS cnt,
            printf('€%,d', AVG(price_numeric))           AS avg_price,
            printf('€%,d', MIN(price_numeric))           AS min_price,
            printf('€%,d', MAX(price_numeric))           AS max_price,
            printf('€%,d', AVG(CASE WHEN living_area > 0 THEN price_numeric * 1.0 / living_area END)) AS avg_m2
        FROM listings
        WHERE price_numeric > 0 AND neighbourhood IS NOT NULL AND neighbourhood != ''
        GROUP BY neighbourhood
        HAVING COUNT(*) >= 5
        ORDER BY AVG(price_numeric) DESC
    """).fetchall()

    print(f"\n  {'Neighbourhood':<30s} {'#':>4}  {'Avg Price':>12}  {'Min':>12}  {'Max':>12}  {'€/m²':>8}")
    print(f"  {'-'*30} {'-'*4}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*8}")
    for r in rows:
        print(f"  {r['neighbourhood']:<30s} {r['cnt']:>4}  {r['avg_price']:>12}  {r['min_price']:>12}  {r['max_price']:>12}  {r['avg_m2'] or 'N/A':>8}")

    # Most / least expensive
    print(f"\n  Top 5 most expensive neighbourhoods (by avg price/m²):")
    top = conn.execute("""
        SELECT neighbourhood,
               printf('€%,d', AVG(price_numeric / living_area)) AS avg_m2,
               COUNT(*) AS cnt
        FROM listings
        WHERE price_numeric > 0 AND living_area > 0
              AND neighbourhood IS NOT NULL AND neighbourhood != ''
        GROUP BY neighbourhood HAVING COUNT(*) >= 5
        ORDER BY AVG(price_numeric * 1.0 / living_area) DESC LIMIT 5
    """).fetchall()
    for i, r in enumerate(top, 1):
        print(f"    {i}. {r['neighbourhood']:<30s} {r['avg_m2']}/m²  ({r['cnt']} listings)")

    print(f"\n  Top 5 most affordable neighbourhoods (by avg price/m²):")
    bottom = conn.execute("""
        SELECT neighbourhood,
               printf('€%,d', AVG(price_numeric / living_area)) AS avg_m2,
               COUNT(*) AS cnt
        FROM listings
        WHERE price_numeric > 0 AND living_area > 0
              AND neighbourhood IS NOT NULL AND neighbourhood != ''
        GROUP BY neighbourhood HAVING COUNT(*) >= 5
        ORDER BY AVG(price_numeric * 1.0 / living_area) ASC LIMIT 5
    """).fetchall()
    for i, r in enumerate(bottom, 1):
        print(f"    {i}. {r['neighbourhood']:<30s} {r['avg_m2']}/m²  ({r['cnt']} listings)")


def time_analysis(conn: sqlite3.Connection):
    print_header("TIME-BASED ANALYSIS")

    # New listings per day
    rows = conn.execute("""
        SELECT DATE(first_seen) AS day,
               COUNT(*) AS new_listings,
               printf('€%,d', AVG(price_numeric)) AS avg_price
        FROM listings WHERE price_numeric > 0
        GROUP BY DATE(first_seen)
        ORDER BY day
    """).fetchall()

    print(f"\n  New listings per day:")
    print(f"  {'Date':<12s} {'New':>5}  {'Avg Price':>12}")
    print(f"  {'-'*12} {'-'*5}  {'-'*12}")
    for r in rows:
        print(f"  {r['day']:<12s} {r['new_listings']:>5}  {r['avg_price']:>12}")

    # Price changes (listings with previous_price)
    changes = conn.execute("""
        SELECT COUNT(*) AS cnt,
               SUM(CASE WHEN previous_price > price_numeric THEN 1 ELSE 0 END) AS reduced,
               SUM(CASE WHEN previous_price < price_numeric THEN 1 ELSE 0 END) AS increased,
               printf('€%,d', AVG(previous_price - price_numeric)) AS avg_change,
               printf('%.1f%%', AVG((previous_price - price_numeric) * 100.0 / previous_price)) AS avg_pct
        FROM listings
        WHERE previous_price IS NOT NULL AND previous_price > 0 AND price_numeric > 0
              AND previous_price != price_numeric
    """).fetchone()

    print(f"\n  Price changes (listings with previous price):")
    if changes['cnt'] > 0:
        print(f"    Total changed:    {changes['cnt']}")
        print(f"    Price reduced:    {changes['reduced']}")
        print(f"    Price increased:  {changes['increased']}")
        print(f"    Avg change:       {changes['avg_change']} ({changes['avg_pct']})")

        # Biggest reductions
        drops = conn.execute("""
            SELECT address, neighbourhood,
                   printf('€%,d', previous_price) AS old_price,
                   printf('€%,d', price_numeric) AS new_price,
                   printf('€%,d', previous_price - price_numeric) AS drop,
                   printf('%.1f%%', (previous_price - price_numeric) * 100.0 / previous_price) AS pct
            FROM listings
            WHERE previous_price IS NOT NULL AND previous_price > price_numeric
            ORDER BY (previous_price - price_numeric) DESC
            LIMIT 5
        """).fetchall()

        if drops:
            print(f"\n    Biggest price drops:")
            for i, r in enumerate(drops, 1):
                print(f"      {i}. {r['address']} ({r['neighbourhood']})")
                print(f"         {r['old_price']} → {r['new_price']}  (-{r['drop']}, -{r['pct']})")
    else:
        print(f"    No price changes recorded yet.")

    # Price history table
    history_count = conn.execute("SELECT COUNT(*) AS cnt FROM price_history").fetchone()['cnt']
    if history_count > 0:
        print(f"\n  Price history records: {history_count}")
        hist = conn.execute("""
            SELECT DATE(ph.recorded_at) AS day,
                   COUNT(*) AS changes,
                   SUM(CASE WHEN ph.new_price < ph.old_price THEN 1 ELSE 0 END) AS reductions,
                   printf('€%,d', AVG(ph.old_price - ph.new_price)) AS avg_change
            FROM price_history ph
            GROUP BY DATE(ph.recorded_at)
            ORDER BY day
        """).fetchall()
        print(f"  {'Date':<12s} {'Changes':>7}  {'Reductions':>10}  {'Avg Change':>12}")
        for r in hist:
            print(f"  {r['day']:<12s} {r['changes']:>7}  {r['reductions']:>10}  {r['avg_change']:>12}")


def best_value(conn: sqlite3.Connection):
    print_header("BEST VALUE LISTINGS")
    print("  (Price furthest below neighbourhood average price/m²)\n")

    rows = conn.execute("""
        WITH neighbourhood_avg AS (
            SELECT neighbourhood,
                   AVG(price_numeric * 1.0 / living_area) AS avg_m2
            FROM listings
            WHERE price_numeric > 0 AND living_area > 0
                  AND neighbourhood IS NOT NULL AND neighbourhood != ''
            GROUP BY neighbourhood
            HAVING COUNT(*) >= 3
        )
        SELECT
            l.address,
            l.neighbourhood,
            printf('€%,d', l.price_numeric)                       AS price,
            l.living_area                                          AS area,
            l.bedrooms,
            l.energy_label,
            printf('€%,d', l.price_numeric / l.living_area)       AS price_m2,
            printf('€%,d', CAST(na.avg_m2 AS INTEGER))            AS hood_avg_m2,
            printf('%.0f%%', (1 - (l.price_numeric * 1.0 / l.living_area) / na.avg_m2) * 100) AS below_avg,
            l.listing_url
        FROM listings l
        JOIN neighbourhood_avg na ON l.neighbourhood = na.neighbourhood
        WHERE l.price_numeric > 0 AND l.living_area > 0 AND l.is_active = 1
        ORDER BY (l.price_numeric * 1.0 / l.living_area) / na.avg_m2 ASC
        LIMIT 20
    """).fetchall()

    for i, r in enumerate(rows, 1):
        print(f"  {i:>2}. {r['address']} — {r['neighbourhood']}")
        print(f"      {r['price']}  |  {r['area']} m²  |  {r['bedrooms'] or '?'} bed  |  {r['energy_label'] or '?'}")
        print(f"      {r['price_m2']}/m² vs neighbourhood avg {r['hood_avg_m2']}/m²  ({r['below_avg']} below)")
        print(f"      https://www.funda.nl{r['listing_url']}")
        print()


def main():
    conn = connect()
    try:
        basic_stats(conn)
        neighbourhood_analysis(conn)
        time_analysis(conn)
        best_value(conn)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
