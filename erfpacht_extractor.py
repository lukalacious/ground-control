"""
Ground Control — Erfpacht Intelligence Extractor
=================================================
Parses structured erfpacht fields and free-text descriptions to determine
leasehold status, annual cost, and end year for Amsterdam properties.

Status values:
  - freehold      : eigen grond (no leasehold)
  - bought_off    : erfpacht afgekocht (one-time payment made)
  - perpetual     : eeuwigdurende erfpacht (no end date)
  - fixed_term    : erfpacht with a known end year
  - unknown       : insufficient data to classify

Usage:
    # Process all listings with erfpacht_status IS NULL
    python erfpacht_extractor.py

    # Limit batch size
    python erfpacht_extractor.py --limit 50
"""

import argparse
import logging
import re

from db import get_dict_cursor, close_pool

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("erfpacht-extractor")


# ──────────────────────────────────────────────────────────────────────
# Extraction logic
# ──────────────────────────────────────────────────────────────────────

def extract_erfpacht(erfpacht_field: str | None, description: str | None) -> dict:
    """
    Extract erfpacht status, amount, and end year from structured field
    and/or free-text description.

    Returns:
        {"status": str, "amount": float | None, "end_year": int | None}
    """
    result = {"status": "unknown", "amount": None, "end_year": None}

    # Try structured field first, then fall back to description
    texts = []
    if erfpacht_field and erfpacht_field.strip():
        texts.append(erfpacht_field.strip())
    if description and description.strip():
        texts.append(description.strip())

    if not texts:
        return result

    combined = " ".join(texts).lower()

    # ── Status detection (order matters — most specific first) ────────

    # Freehold: eigen grond
    if re.search(r'\beigen\s+grond\b', combined):
        result["status"] = "freehold"

    # Bought off: erfpacht afgekocht / afgekochte erfpacht
    elif re.search(r'\berfpacht\s+afgekocht\b', combined) or \
         re.search(r'\bafgekochte?\s+erfpacht\b', combined) or \
         re.search(r'\bafgekocht\b.*\berfpacht\b', combined):
        result["status"] = "bought_off"

    # Fixed term: erfpacht tot <year> / einddatum <year>
    elif re.search(r'\berfpacht\s+tot\s+\d{4}\b', combined) or \
         re.search(r'\beinddatum\b.*\d{4}', combined):
        result["status"] = "fixed_term"
        # Extract the year
        year_match = re.search(r'\b(erfpacht\s+tot|einddatum)\D*(\d{4})\b', combined)
        if year_match:
            result["end_year"] = int(year_match.group(2))

    # Perpetual: eeuwigdurende erfpacht / eeuwigdurend
    elif re.search(r'\beeuwigdurend(?:e)?\s*(?:erfpacht)?\b', combined):
        result["status"] = "perpetual"

    # Amsterdam default: gemeentelijke erfpacht → perpetual
    elif re.search(r'\bgemeentelijke\s+erfpacht\b', combined):
        result["status"] = "perpetual"

    # Generic erfpacht mention without specifics
    elif re.search(r'\berfpacht\b', combined):
        # Check if there's a year mentioned nearby
        year_match = re.search(r'\berfpacht\b.*?\b(20\d{2}|21\d{2})\b', combined)
        if year_match:
            result["status"] = "fixed_term"
            result["end_year"] = int(year_match.group(1))
        else:
            result["status"] = "perpetual"  # Default for Amsterdam

    # ── Amount extraction ─────────────────────────────────────────────

    # canon.*€<amount> / €<amount>.*per jaar
    amount_patterns = [
        r'canon\D*(?:€|eur)\s*([\d.,]+)',
        r'(?:€|eur)\s*([\d.,]+)\s*(?:per\s+jaar|p\.?j\.?|per\s+year)',
        r'([\d.,]+)\s*(?:€|euro)\s*(?:per\s+jaar|p\.?j\.?)',
        r'canon\D*([\d.,]+)',
    ]
    for pattern in amount_patterns:
        amount_match = re.search(pattern, combined)
        if amount_match:
            raw = amount_match.group(1)
            # Dutch number format: 1.234,56 → 1234.56
            raw = raw.replace('.', '').replace(',', '.')
            try:
                amount = float(raw)
                if 0 < amount < 100000:  # sanity check
                    result["amount"] = amount
                    break
            except ValueError:
                continue

    return result


# ──────────────────────────────────────────────────────────────────────
# Batch processing
# ──────────────────────────────────────────────────────────────────────

def process_all(limit: int | None = None) -> dict:
    """Process all listings where erfpacht_status IS NULL."""
    stats = {"processed": 0, "updated": 0, "skipped": 0}

    with get_dict_cursor() as cur:
        query = """
            SELECT global_id, erfpacht, description
            FROM listings
            WHERE erfpacht_status IS NULL
            ORDER BY first_seen DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        rows = cur.fetchall()

    log.info("Found %d listings to process", len(rows))

    if not rows:
        return stats

    with get_dict_cursor() as cur:
        for row in rows:
            gid = row["global_id"]
            result = extract_erfpacht(row["erfpacht"], row["description"])

            cur.execute("""
                UPDATE listings
                SET erfpacht_status = %s,
                    erfpacht_amount = %s,
                    erfpacht_end_year = %s
                WHERE global_id = %s
            """, (result["status"], result["amount"], result["end_year"], gid))

            stats["processed"] += 1
            if result["status"] != "unknown":
                stats["updated"] += 1
                log.info("  [%d] %s (amount=%s, end_year=%s)",
                         gid, result["status"], result["amount"], result["end_year"])
            else:
                stats["skipped"] += 1

    log.info("Done: %d processed, %d classified, %d unknown",
             stats["processed"], stats["updated"], stats["skipped"])
    return stats


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground Control — Erfpacht Extractor")
    parser.add_argument("--limit", type=int, default=None, help="Max listings to process")
    args = parser.parse_args()

    try:
        process_all(limit=args.limit)
    finally:
        close_pool()
