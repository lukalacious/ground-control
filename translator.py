"""
Ground Control — Dutch to English Translator
=============================================
Static field translations + Claude Haiku API for descriptions.

Usage:
    # Translate all untranslated listings
    python translator.py

    # Limit batch size
    python translator.py --limit 20
"""

import argparse
import logging
import os
import re
import time

from db import get_dict_cursor, close_pool

# ──────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("translator")

# Rate limiting: max requests per minute for Haiku
RATE_LIMIT_DELAY = 1.0  # seconds between API calls


# ──────────────────────────────────────────────────────────────────────
# Static translation map
# ──────────────────────────────────────────────────────────────────────

DUTCH_TO_ENGLISH = {
    # Construction types
    "Bestaande bouw": "Existing build",
    "Nieuwbouw": "New build",

    # Floor levels
    "Begane grond": "Ground floor",
    "1e woonlaag": "1st floor",
    "2e woonlaag": "2nd floor",
    "3e woonlaag": "3rd floor",
    "4e woonlaag": "4th floor",
    "5e woonlaag": "5th floor",
    "6e woonlaag": "6th floor",
    "7e woonlaag": "7th floor",
    "8e woonlaag": "8th floor",
    "9e woonlaag": "9th floor",
    "10e woonlaag": "10th floor",
    "Kelder": "Basement",
    "Souterrain": "Basement level",

    # Balcony / outdoor
    "Dakterras": "Roof terrace",
    "Balkon": "Balcony",
    "Frans balkon": "French balcony",
    "Tuin": "Garden",
    "Patio": "Patio",
    "Atrium": "Atrium",

    # Object types
    "Appartement": "Apartment",
    "Bovenwoning": "Upper floor apartment",
    "Benedenwoning": "Ground floor apartment",
    "Penthouse": "Penthouse",
    "Maisonnette": "Maisonette",
    "Portiekwoning": "Stairwell apartment",
    "Galerijflat": "Gallery flat",
    "Tussenverdieping": "Split level",
    "Eengezinswoning": "Single-family home",
    "Tussenwoning": "Terraced house",
    "Hoekwoning": "Corner house",
    "Vrijstaande woning": "Detached house",
    "2-onder-1-kapwoning": "Semi-detached house",
    "Geschakelde woning": "Linked house",
    "Herenhuis": "Townhouse",
    "Grachtenpand": "Canal house",
    "Villa": "Villa",
    "Woonboot": "Houseboat",
    "Woonboerderij": "Farmhouse",

    # Parking
    "Betaald parkeren": "Paid parking",
    "Openbaar parkeren": "Public parking",
    "Parkeergarage": "Parking garage",
    "Parkeerkelder": "Underground parking",
    "Parkeerplaats": "Parking space",
    "Eigen parkeerplaats": "Private parking space",
    "Carport": "Carport",
    "Garage": "Garage",

    # Location
    "Aan park": "Near park",
    "Aan water": "Near water",
    "In woonwijk": "Residential area",
    "In centrum": "City center",
    "Aan drukke weg": "On busy road",
    "Aan rustige weg": "On quiet road",
    "In bosrijke omgeving": "Wooded area",
    "Vrij uitzicht": "Open view",
    "Beschutte ligging": "Sheltered location",
    "Landelijk gelegen": "Rural location",

    # Heating
    "Centrale verwarming": "Central heating",
    "Blokverwarming": "District heating",
    "Stadsverwarming": "City heating",
    "Vloerverwarming": "Underfloor heating",
    "Gaskachels": "Gas heaters",
    "Elektrische verwarming": "Electric heating",
    "Warmtepomp": "Heat pump",
    "CV-ketel": "Central heating boiler",

    # Insulation
    "Dakisolatie": "Roof insulation",
    "Dubbel glas": "Double glazing",
    "Spouwmuurisolatie": "Cavity wall insulation",
    "Vloerisolatie": "Floor insulation",
    "Muurisolatie": "Wall insulation",
    "Volledig geïsoleerd": "Fully insulated",
    "Gedeeltelijk dubbel glas": "Partial double glazing",
    "HR glas": "HR glass",
    "Driedubbel glas": "Triple glazing",
    "Eco-bouw": "Eco build",

    # Acceptance / delivery
    "In overleg": "By arrangement",
    "Per direct": "Immediately",
    "Na oplevering": "After completion",

    # Amenities
    "Lift": "Elevator",
    "Zonnepanelen": "Solar panels",
    "Mechanische ventilatie": "Mechanical ventilation",
    "Airconditioning": "Air conditioning",
    "Alarm": "Alarm system",
    "Rolluiken": "Roller shutters",
    "Zwembad": "Swimming pool",
    "Sauna": "Sauna",
    "Jacuzzi": "Jacuzzi",
    "Open haard": "Fireplace",
    "Windmolens": "Wind turbines",
    "Glasvezel": "Fiber optic",
    "Satellietschotel": "Satellite dish",
}


# ──────────────────────────────────────────────────────────────────────
# Translation functions
# ──────────────────────────────────────────────────────────────────────

def translate_field(value: str) -> str:
    """
    Translate a structured field value using the static map.
    Handles comma-separated values (e.g. "Dubbel glas, Dakisolatie").
    """
    if not value or not value.strip():
        return value

    # Check direct match first
    if value.strip() in DUTCH_TO_ENGLISH:
        return DUTCH_TO_ENGLISH[value.strip()]

    # Handle comma-separated values
    parts = [p.strip() for p in value.split(",")]
    translated = []
    for part in parts:
        translated.append(DUTCH_TO_ENGLISH.get(part, part))
    return ", ".join(translated)


def _is_dutch(text: str) -> bool:
    """Heuristic: check if text appears to be Dutch."""
    dutch_markers = [
        r'\bde\b', r'\bhet\b', r'\been\b', r'\bvan\b', r'\bin\b',
        r'\bop\b', r'\bmet\b', r'\bvoor\b', r'\bis\b', r'\bworden\b',
        r'\bgelegen\b', r'\bwoning\b', r'\bkamer\b', r'\bbadkamer\b',
        r'\bkeuken\b', r'\bslaapkamer\b', r'\bverdieping\b',
    ]
    count = sum(1 for p in dutch_markers if re.search(p, text.lower()))
    return count >= 3


def translate_description(text: str) -> str | None:
    """
    Translate a Dutch property description to English using Claude Haiku API.
    Returns translated text or None if translation not needed/failed.
    """
    if not text or not text.strip():
        return None

    if not _is_dutch(text):
        log.debug("Text does not appear to be Dutch, skipping")
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set, cannot translate descriptions")
        return None

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        # Truncate very long descriptions to save tokens
        truncated = text[:4000] if len(text) > 4000 else text

        message = client.messages.create(
            model="claude-haiku-4-20250414",
            max_tokens=2000,
            system="Translate this Dutch property listing description to English. "
                   "Keep proper nouns, addresses, and technical terms intact. "
                   "Be concise and natural.",
            messages=[
                {"role": "user", "content": truncated}
            ],
        )

        translated = message.content[0].text
        return translated

    except Exception as e:
        log.error("Translation API error: %s", e)
        return None


# ──────────────────────────────────────────────────────────────────────
# Batch processing
# ──────────────────────────────────────────────────────────────────────

def process_all(limit: int | None = None) -> dict:
    """Translate descriptions for all untranslated listings."""
    stats = {"processed": 0, "translated": 0, "skipped": 0, "failed": 0}

    with get_dict_cursor() as cur:
        query = """
            SELECT global_id, description
            FROM listings
            WHERE description_translated = false
              AND description IS NOT NULL
              AND description != ''
            ORDER BY first_seen DESC
        """
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        rows = cur.fetchall()

    log.info("Found %d listings to translate", len(rows))

    if not rows:
        return stats

    for row in rows:
        gid = row["global_id"]
        description = row["description"]
        stats["processed"] += 1

        log.info("[%d/%d] Translating listing %d (%d chars)",
                 stats["processed"], len(rows), gid, len(description or ""))

        translated = translate_description(description)

        if translated:
            with get_dict_cursor() as cur:
                cur.execute("""
                    UPDATE listings
                    SET description_en = %s,
                        description_translated = true
                    WHERE global_id = %s
                """, (translated, gid))
            stats["translated"] += 1
            log.info("  Translated (%d chars -> %d chars)", len(description), len(translated))
        else:
            # Mark as translated even if we couldn't translate (e.g. not Dutch)
            with get_dict_cursor() as cur:
                cur.execute("""
                    UPDATE listings
                    SET description_translated = true
                    WHERE global_id = %s
                """, (gid,))
            stats["skipped"] += 1
            log.info("  Skipped (not Dutch or API unavailable)")

        # Rate limiting between API calls
        time.sleep(RATE_LIMIT_DELAY)

    log.info("Done: %d processed, %d translated, %d skipped, %d failed",
             stats["processed"], stats["translated"], stats["skipped"], stats["failed"])
    return stats


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ground Control — Dutch-English Translator")
    parser.add_argument("--limit", type=int, default=None, help="Max listings to translate")
    args = parser.parse_args()

    try:
        process_all(limit=args.limit)
    finally:
        close_pool()
