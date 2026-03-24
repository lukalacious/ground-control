"""
Migrate Ground Control SQLite database to Neon PostgreSQL.

Usage:
    python migrate_to_neon.py
    python migrate_to_neon.py --db path/to/ground_control.db
    python migrate_to_neon.py --dry-run
"""

import argparse
import json
import os
import sqlite3
from pathlib import Path

import psycopg2
from psycopg2.extras import execute_values

DB_PATH = Path(__file__).parent / "ground_control.db"


def get_neon_conn():
    url = os.environ.get("DATABASE_URL")
    if not url:
        env_file = Path(__file__).parent / "web" / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip('"')
                    break
    if not url:
        raise RuntimeError("DATABASE_URL not set and web/.env not found")
    return psycopg2.connect(url)


def migrate_listings(sqlite_conn, pg_conn, dry_run=False):
    cursor = sqlite_conn.execute("SELECT * FROM listings")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()
    print(f"  Found {len(rows)} listings in SQLite")

    if dry_run or not rows:
        return len(rows)

    # Map SQLite column names to Postgres column names (snake_case matches)
    pg_columns = columns  # Schema uses same snake_case names via @map

    placeholders = ", ".join(["%s"] * len(pg_columns))
    col_names = ", ".join(pg_columns)
    conflict_col = "global_id"

    # Build upsert: insert or update on conflict
    update_cols = [c for c in pg_columns if c != conflict_col]
    update_set = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)

    query = f"""
        INSERT INTO listings ({col_names})
        VALUES ({placeholders})
        ON CONFLICT ({conflict_col}) DO UPDATE SET {update_set}
    """

    pg_cur = pg_conn.cursor()
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        # Convert sqlite3.Row to tuples, handling boolean conversion
        clean_batch = []
        for row in batch:
            values = []
            for j, col in enumerate(pg_columns):
                val = row[j]
                # SQLite booleans (0/1) → Python bool for Postgres
                if col in ("is_project", "is_active", "has_balcony", "detail_enriched", "description_translated"):
                    val = bool(val) if val is not None else False
                values.append(val)
            clean_batch.append(tuple(values))

        pg_cur.executemany(query, clean_batch)
        print(f"  Inserted batch {i // batch_size + 1} ({len(batch)} rows)")

    pg_conn.commit()
    return len(rows)


def migrate_price_history(sqlite_conn, pg_conn, dry_run=False):
    cursor = sqlite_conn.execute("SELECT global_id, old_price, new_price, recorded_at FROM price_history")
    rows = cursor.fetchall()
    print(f"  Found {len(rows)} price history records in SQLite")

    if dry_run or not rows:
        return len(rows)

    pg_cur = pg_conn.cursor()
    query = """
        INSERT INTO price_history (global_id, old_price, new_price, recorded_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
    """
    pg_cur.executemany(query, [tuple(row) for row in rows])
    pg_conn.commit()
    return len(rows)


def migrate_neighbourhood_stats(sqlite_conn, pg_conn, dry_run=False):
    cursor = sqlite_conn.execute("SELECT neighbourhood, avg_price_m2, median_price, listing_count, calculated_at FROM neighbourhood_stats")
    rows = cursor.fetchall()
    print(f"  Found {len(rows)} neighbourhood stats records in SQLite")

    if dry_run or not rows:
        return len(rows)

    pg_cur = pg_conn.cursor()
    query = """
        INSERT INTO neighbourhood_stats (neighbourhood, avg_price_m2, median_price, listing_count, calculated_at)
        VALUES (%s, %s, %s, %s, %s)
    """
    pg_cur.executemany(query, [tuple(row) for row in rows])
    pg_conn.commit()
    return len(rows)


def migrate_city_stats(sqlite_conn, pg_conn, dry_run=False):
    cursor = sqlite_conn.execute("SELECT avg_price_m2, median_price, median_days_on_market, listing_count, calculated_at FROM city_stats")
    rows = cursor.fetchall()
    print(f"  Found {len(rows)} city stats records in SQLite")

    if dry_run or not rows:
        return len(rows)

    pg_cur = pg_conn.cursor()
    query = """
        INSERT INTO city_stats (avg_price_m2, median_price, median_days_on_market, listing_count, calculated_at)
        VALUES (%s, %s, %s, %s, %s)
    """
    pg_cur.executemany(query, [tuple(row) for row in rows])
    pg_conn.commit()
    return len(rows)


def migrate_scrape_runs(sqlite_conn, pg_conn, dry_run=False):
    cursor = sqlite_conn.execute("SELECT run_at, city, search_type, pages_scraped, listings_found, new_listings, updated_listings FROM scrape_runs")
    rows = cursor.fetchall()
    print(f"  Found {len(rows)} scrape run records in SQLite")

    if dry_run or not rows:
        return len(rows)

    pg_cur = pg_conn.cursor()
    query = """
        INSERT INTO scrape_runs (run_at, city, search_type, pages_scraped, listings_found, new_listings, updated_listings)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    pg_cur.executemany(query, [tuple(row) for row in rows])
    pg_conn.commit()
    return len(rows)


def main():
    parser = argparse.ArgumentParser(description="Migrate SQLite to Neon PostgreSQL")
    parser.add_argument("--db", default=str(DB_PATH), help="Path to SQLite database")
    parser.add_argument("--dry-run", action="store_true", help="Count records without migrating")
    args = parser.parse_args()

    print(f"SQLite database: {args.db}")
    sqlite_conn = sqlite3.connect(args.db)
    sqlite_conn.row_factory = sqlite3.Row

    if not args.dry_run:
        pg_conn = get_neon_conn()
        print(f"Connected to Neon PostgreSQL")
    else:
        pg_conn = None
        print("DRY RUN — counting records only")

    print("\n1. Migrating listings...")
    n = migrate_listings(sqlite_conn, pg_conn, args.dry_run)

    print("\n2. Migrating price history...")
    migrate_price_history(sqlite_conn, pg_conn, args.dry_run)

    print("\n3. Migrating neighbourhood stats...")
    migrate_neighbourhood_stats(sqlite_conn, pg_conn, args.dry_run)

    print("\n4. Migrating city stats...")
    migrate_city_stats(sqlite_conn, pg_conn, args.dry_run)

    print("\n5. Migrating scrape runs...")
    migrate_scrape_runs(sqlite_conn, pg_conn, args.dry_run)

    print(f"\nMigration {'would complete' if args.dry_run else 'complete'}!")
    print(f"  {n} listings migrated to Neon")

    sqlite_conn.close()
    if pg_conn:
        pg_conn.close()


if __name__ == "__main__":
    main()
