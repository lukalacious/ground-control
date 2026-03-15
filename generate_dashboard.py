#!/usr/bin/env python3
"""Generate the Ground Control house-hunting dashboard.

Outputs:
  public/index.html   — HTML shell with CSS + JS (~80KB)
  public/listings.json — All listing data + stats (~3-5MB)
"""

import argparse
import json
import random
import sqlite3
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

from scorer import score_listings

DB_PATH = Path(__file__).parent / "ground_control.db"
PUBLIC_DIR = Path(__file__).parent / "public"
COORDS_PATH = Path(__file__).parent / "neighbourhood_coords.json"

# Approximate Amsterdam postcode area centers (4-digit prefix -> lat/lon)
POSTCODE_COORDS = {
    "1011": (52.3676, 4.9000), "1012": (52.3720, 4.8940), "1013": (52.3780, 4.8900),
    "1014": (52.3860, 4.8850), "1015": (52.3580, 4.8800), "1016": (52.3650, 4.8960),
    "1017": (52.3600, 4.9020), "1018": (52.3540, 4.9120), "1019": (52.3620, 4.9200),
    "1021": (52.3840, 4.9150), "1022": (52.3900, 4.9100), "1023": (52.3950, 4.9050),
    "1024": (52.4000, 4.9200), "1025": (52.4050, 4.9100), "1026": (52.4150, 4.9050),
    "1027": (52.4100, 4.9300), "1028": (52.4200, 4.9250), "1031": (52.3800, 4.9050),
    "1032": (52.3850, 4.9100), "1033": (52.3900, 4.8950), "1034": (52.4000, 4.9050),
    "1035": (52.4080, 4.9000), "1041": (52.3550, 4.8700), "1042": (52.3600, 4.8650),
    "1043": (52.3650, 4.8600), "1044": (52.3700, 4.8500), "1045": (52.3750, 4.8450),
    "1046": (52.3800, 4.8400), "1047": (52.3850, 4.8350), "1051": (52.3450, 4.8850),
    "1052": (52.3420, 4.8900), "1053": (52.3400, 4.8950), "1054": (52.3380, 4.9000),
    "1055": (52.3350, 4.8850), "1056": (52.3300, 4.8900), "1057": (52.3250, 4.8950),
    "1058": (52.3200, 4.9000), "1059": (52.3150, 4.9050), "1061": (52.3100, 4.8800),
    "1062": (52.3050, 4.8750), "1063": (52.3000, 4.8900), "1064": (52.2950, 4.8950),
    "1065": (52.2900, 4.9000), "1066": (52.2850, 4.9050), "1067": (52.2800, 4.9100),
    "1068": (52.2750, 4.9150), "1069": (52.2700, 4.9200), "1071": (52.3500, 4.9050),
    "1072": (52.3450, 4.9100), "1073": (52.3400, 4.9150), "1074": (52.3350, 4.9200),
    "1075": (52.3300, 4.9250), "1076": (52.3250, 4.9300), "1077": (52.3200, 4.9350),
    "1078": (52.3150, 4.9400), "1079": (52.3100, 4.9450), "1081": (52.3050, 4.9500),
    "1082": (52.3000, 4.9550), "1083": (52.2950, 4.9600), "1086": (52.2900, 4.9700),
    "1087": (52.2850, 4.9750), "1088": (52.2800, 4.9800), "1089": (52.2750, 4.9850),
    "1091": (52.2950, 4.9350), "1092": (52.2900, 4.9400), "1093": (52.2850, 4.9450),
    "1094": (52.2800, 4.9500), "1095": (52.2750, 4.9550), "1096": (52.2700, 4.9600),
    "1097": (52.2650, 4.9650), "1098": (52.2600, 4.9700), "1099": (52.2550, 4.9750),
    "1101": (52.3100, 4.9550), "1102": (52.3050, 4.9600), "1103": (52.3000, 4.9650),
    "1104": (52.2950, 4.9700), "1105": (52.2900, 4.9750), "1106": (52.2850, 4.9800),
    "1107": (52.2800, 4.9850), "1108": (52.2750, 4.9900), "1109": (52.2700, 4.9950),
}


def assign_coords(listings: list[dict]) -> None:
    """Assign lat/lng to each listing from postcode prefix + jitter."""
    for listing in listings:
        pc = (listing.get("postcode") or "").replace(" ", "")
        prefix = pc[:4]
        coords = POSTCODE_COORDS.get(prefix)
        if not coords and len(prefix) >= 3:
            for k, v in POSTCODE_COORDS.items():
                if k.startswith(prefix[:3]):
                    coords = v
                    break
        if coords:
            listing["latitude"] = round(coords[0] + random.uniform(-0.002, 0.002), 6)
            listing["longitude"] = round(coords[1] + random.uniform(-0.002, 0.002), 6)
        else:
            listing["latitude"] = None
            listing["longitude"] = None


def get_price_history(db_path: str) -> dict[int, list[dict]]:
    """Get price history grouped by global_id."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT global_id, old_price, new_price, recorded_at FROM price_history ORDER BY recorded_at DESC"
    ).fetchall()
    conn.close()

    history: dict[int, list[dict]] = {}
    for r in rows:
        gid = r["global_id"]
        if gid not in history:
            history[gid] = []
        history[gid].append({
            "old_price": r["old_price"],
            "new_price": r["new_price"],
            "date": r["recorded_at"][:10] if r["recorded_at"] else None,
        })
    return history


def get_stats(db_path: str) -> dict:
    """Get latest city stats."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM city_stats ORDER BY calculated_at DESC LIMIT 1").fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"avg_price_m2": 0, "median_price": 0, "median_days_on_market": 0, "listing_count": 0}


def get_neighbourhood_stats(db_path: str) -> dict:
    """Get neighbourhood stats as a dict keyed by name."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM neighbourhood_stats ORDER BY listing_count DESC").fetchall()
    conn.close()
    return {r["neighbourhood"]: {"avg_price_m2": round(r["avg_price_m2"], 1), "median_price": r["median_price"], "count": r["listing_count"]} for r in rows}


def count_new_today(db_path: str) -> int:
    """Count listings first seen in the last 24h."""
    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM listings WHERE is_active = 1 AND first_seen >= datetime('now', '-1 day')"
    ).fetchone()[0]
    conn.close()
    return count


def load_coords(coords_path: Path) -> dict:
    """Load neighbourhood coordinates from geocoder cache."""
    if coords_path.exists():
        return json.loads(coords_path.read_text(encoding="utf-8"))
    return {}


def build_map_data(hood_stats: dict, coords: dict) -> dict:
    """Merge neighbourhood stats with coordinates into map data."""
    map_data = {}
    for name, stats in hood_stats.items():
        if name in coords:
            entry = coords[name]
            lat, lng = entry[0], entry[1]
            wijk = entry[2] if len(entry) >= 3 else ""
            stadsdeel = entry[3] if len(entry) >= 4 else ""
            map_data[name] = {
                "avg_price_m2": stats["avg_price_m2"],
                "median_price": stats["median_price"],
                "count": stats["count"],
                "lat": lat,
                "lng": lng,
                "wijk": wijk,
                "stadsdeel": stadsdeel,
            }
    return map_data


def build_html(generated_at: str) -> str:
    """Build the HTML shell that loads data from listings.json."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
    <title>Ground Control</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
          integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin="">
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        :root {{
            --gold: #c49a6c; --bg: #08090d; --card: #111318; --card-border: #1a1c24;
            --text: #c8c4be; --muted: #5a5650; --muted2: #6b6762; --input-bg: #161a24;
            --input-border: #1e2028; --green: #6aad7a; --red: #7a3030;
            --nav-h: 56px; --safe-b: env(safe-area-inset-bottom, 0px);
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg); color: var(--text); line-height: 1.4;
            padding-bottom: calc(var(--nav-h) + var(--safe-b));
            -webkit-tap-highlight-color: transparent;
        }}

        /* ── Loading screen ── */
        .loading {{
            position: fixed; inset: 0; background: var(--bg); z-index: 9999;
            display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px;
        }}
        .loading.hidden {{ display: none; }}
        .loading h2 {{ color: var(--gold); font-size: 20px; }}
        .spinner {{
            width: 36px; height: 36px; border: 3px solid var(--card-border);
            border-top-color: var(--gold); border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}

        /* ── Bottom nav ── */
        .bottom-nav {{
            position: fixed; bottom: 0; left: 0; right: 0; height: calc(var(--nav-h) + var(--safe-b));
            padding-bottom: var(--safe-b);
            background: #0c0d12; border-top: 1px solid var(--card-border);
            display: flex; z-index: 900;
        }}
        .nav-item {{
            flex: 1; display: flex; flex-direction: column; align-items: center;
            justify-content: center; gap: 2px; color: var(--muted); font-size: 10px;
            font-weight: 600; cursor: pointer; border: none; background: none;
            position: relative; transition: color 0.15s;
        }}
        .nav-item.active {{ color: var(--gold); }}
        .nav-item svg {{ width: 22px; height: 22px; }}
        .nav-badge {{
            position: absolute; top: 4px; right: calc(50% - 18px);
            background: var(--gold); color: #0a0b10; font-size: 9px; font-weight: 700;
            min-width: 16px; height: 16px; border-radius: 8px; padding: 0 4px;
            display: flex; align-items: center; justify-content: center;
        }}
        .nav-badge:empty {{ display: none; }}

        /* ── Views ── */
        .view {{ display: none; }}
        .view.active {{ display: block; }}
        .view-map.active {{ display: flex; flex-direction: column; height: calc(100dvh - var(--nav-h) - var(--safe-b)); }}

        /* ── Header ── */
        .header {{
            padding: 12px 16px 0; display: flex; align-items: center; gap: 10px;
        }}
        .header h1 {{ color: var(--gold); font-size: 18px; letter-spacing: 0.5px; white-space: nowrap; }}
        .header .subtitle {{ color: var(--muted); font-size: 11px; }}

        /* ── Search bar ── */
        .search-wrap {{ padding: 10px 16px; }}
        .search-wrap input {{
            width: 100%; padding: 10px 14px; border: 1px solid var(--input-border);
            border-radius: 10px; background: var(--card); color: var(--text); font-size: 15px;
        }}
        .search-wrap input::placeholder {{ color: #4a4640; }}
        .search-wrap input:focus {{ outline: none; border-color: var(--gold); }}

        /* ── Stats bar ── */
        .stats-bar {{
            display: flex; gap: 8px; padding: 0 16px 10px; overflow-x: auto;
            scrollbar-width: none; -webkit-overflow-scrolling: touch;
        }}
        .stats-bar::-webkit-scrollbar {{ display: none; }}
        .stat {{
            background: var(--card); padding: 10px 14px; border-radius: 10px;
            min-width: 90px; text-align: center; flex-shrink: 0;
            border: 1px solid var(--card-border);
        }}
        .stat-value {{ font-size: 17px; font-weight: 700; color: var(--gold); }}
        .stat-label {{ font-size: 9px; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: 0.4px; }}

        /* ── Inline filter summary ── */
        .filter-summary {{
            padding: 0 16px 8px; display: flex; gap: 6px; align-items: center;
            overflow-x: auto; scrollbar-width: none;
        }}
        .filter-summary::-webkit-scrollbar {{ display: none; }}
        .filter-chip {{
            padding: 6px 12px; border-radius: 14px; font-size: 12px;
            font-weight: 600; cursor: pointer; border: 1px solid #252530;
            background: transparent; color: var(--muted2); white-space: nowrap;
            transition: all 0.15s; flex-shrink: 0;
        }}
        .filter-chip.active {{ background: var(--gold); color: #0a0b10; border-color: var(--gold); }}
        .filter-chip.active.chip-sold {{ background: var(--red); color: #ddd; border-color: var(--red); }}
        .filter-chip:hover {{ border-color: var(--gold); }}
        .sort-select {{
            padding: 6px 10px; border-radius: 14px; font-size: 12px; font-weight: 600;
            border: 1px solid #252530; background: var(--card); color: var(--text);
            flex-shrink: 0;
        }}
        .sort-select:focus {{ outline: none; border-color: var(--gold); }}

        /* ── Result bar ── */
        .result-bar {{
            padding: 0 16px 8px; font-size: 13px; color: var(--muted);
            display: flex; justify-content: space-between; align-items: center;
        }}

        /* ── Grid / card list ── */
        .grid {{
            padding: 0 16px; display: flex; flex-direction: column; gap: 12px;
        }}
        .card {{
            background: var(--card); border-radius: 12px; overflow: hidden;
            transition: transform 0.15s, box-shadow 0.15s; position: relative;
            border: 1px solid var(--card-border);
        }}
        .card:active {{ transform: scale(0.98); }}
        .card-top {{ display: flex; gap: 0; }}
        .card-img {{
            width: 120px; min-height: 100px; background: #0c0d12; overflow: hidden;
            flex-shrink: 0;
        }}
        .card-img img {{ width: 100%; height: 100%; object-fit: cover; display: block; }}
        .card-body {{ padding: 10px 12px; flex: 1; min-width: 0; }}
        .card-price-row {{ display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; }}
        .card-price {{ font-size: 18px; font-weight: 700; color: var(--gold); }}
        .card-prev-price {{ font-size: 12px; color: var(--red); text-decoration: line-through; }}
        .card-pred-badge {{
            display: inline-flex; align-items: center; gap: 3px;
            padding: 2px 6px; border-radius: 4px; font-size: 11px; font-weight: 700;
        }}
        .pred-under {{ background: rgba(106,173,122,0.15); color: var(--green); }}
        .pred-over {{ background: rgba(122,48,48,0.15); color: var(--red); }}
        .card-address {{ font-size: 13px; color: var(--text); margin: 2px 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
        .card-stats {{
            display: flex; gap: 8px; font-size: 11px; color: var(--muted); margin-top: 4px; flex-wrap: wrap;
        }}
        .card-stats span {{ white-space: nowrap; }}

        /* Badges */
        .badges {{ position: absolute; top: 8px; left: 8px; display: flex; gap: 4px; z-index: 2; }}
        .badge {{
            padding: 2px 6px; border-radius: 4px; font-size: 10px;
            font-weight: 700; text-transform: uppercase;
        }}
        .badge-new {{ background: var(--gold); color: #0a0b10; }}
        .badge-drop {{ background: var(--red); color: #ddd; }}
        .badge-offer {{ background: rgba(196,154,108,0.8); color: #0a0b10; }}
        .badge-sold {{ background: var(--red); color: #ddd; }}
        .card.card-sold {{ opacity: 0.6; }}

        /* Score + Fav on card */
        .card-actions {{
            position: absolute; top: 8px; right: 8px; display: flex; gap: 4px; z-index: 2;
        }}
        .badge-score {{
            padding: 2px 7px; border-radius: 4px; font-size: 11px; font-weight: 700;
        }}
        .score-high {{ background: var(--gold); color: #0a0b10; }}
        .score-mid {{ background: rgba(196,154,108,0.6); color: #111; }}
        .score-low {{ background: var(--input-border); color: var(--muted); }}
        .fav-btn {{
            background: rgba(0,0,0,0.5); border: none; cursor: pointer;
            width: 28px; height: 28px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; font-size: 16px;
        }}
        .fav-btn.faved {{ color: #e25555; }}
        .fav-btn:not(.faved) {{ color: #555; }}

        /* Energy label colors */
        .el-A, .el-Ap {{ color: var(--green); }} .el-B {{ color: #94a86a; }}
        .el-C {{ color: var(--gold); }} .el-D {{ color: #c47a50; }}
        .el-E {{ color: #a04040; }} .el-F, .el-G {{ color: var(--red); }}

        /* ── Filter drawer ── */
        .drawer-overlay {{
            display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
            z-index: 950;
        }}
        .drawer-overlay.open {{ display: block; }}
        .filter-drawer {{
            position: fixed; bottom: 0; left: 0; right: 0;
            background: var(--card); border-radius: 16px 16px 0 0;
            max-height: 85vh; overflow-y: auto; z-index: 960;
            transform: translateY(100%); transition: transform 0.3s ease;
            padding-bottom: calc(16px + var(--safe-b));
        }}
        .filter-drawer.open {{ transform: translateY(0); }}
        .drawer-handle {{
            width: 36px; height: 4px; background: #333; border-radius: 2px;
            margin: 10px auto 6px;
        }}
        .drawer-header {{
            display: flex; justify-content: space-between; align-items: center;
            padding: 4px 20px 12px; border-bottom: 1px solid var(--card-border);
        }}
        .drawer-header h3 {{ color: var(--gold); font-size: 16px; }}
        .drawer-section {{
            padding: 14px 20px; border-bottom: 1px solid var(--card-border);
        }}
        .drawer-section h4 {{
            font-size: 12px; color: var(--muted2); text-transform: uppercase;
            letter-spacing: 0.3px; margin-bottom: 10px;
        }}
        .drawer-row {{ display: flex; gap: 8px; }}
        .drawer-row input, .drawer-row select {{
            flex: 1; padding: 10px 12px; border: 1px solid var(--input-border);
            border-radius: 8px; background: var(--input-bg); color: var(--text); font-size: 14px;
        }}
        .drawer-row input:focus, .drawer-row select:focus {{ outline: none; border-color: var(--gold); }}
        .drawer-toggles {{ display: flex; flex-wrap: wrap; gap: 8px; }}
        .drawer-toggle {{
            padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 600;
            border: 1px solid #252530; background: transparent; color: var(--muted2);
            cursor: pointer; transition: all 0.15s;
        }}
        .drawer-toggle.active {{ background: var(--gold); color: #0a0b10; border-color: var(--gold); }}
        .drawer-toggle.active.toggle-sold {{ background: var(--red); color: #ddd; border-color: var(--red); }}
        .drawer-actions {{
            padding: 14px 20px; display: flex; gap: 10px;
        }}
        .btn {{
            padding: 12px 20px; background: var(--gold); color: #0a0b10; border: none;
            border-radius: 10px; cursor: pointer; font-weight: 700; font-size: 14px;
            flex: 1; text-align: center;
        }}
        .btn:active {{ opacity: 0.8; }}
        .btn-ghost {{
            background: transparent; border: 1px solid #252530; color: var(--muted2);
        }}

        /* ── Neighbourhood selector (inside drawer) ── */
        .hood-section {{ padding: 14px 20px; }}
        .stadsdeel-pills {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
        .stadsdeel-pill {{
            padding: 5px 12px; border-radius: 12px; font-size: 12px;
            font-weight: 700; cursor: pointer; border: 2px solid #252530;
            background: transparent; color: var(--muted2); white-space: nowrap;
        }}
        .stadsdeel-pill.sd-all {{ background: var(--gold); color: #0a0b10; border-color: var(--gold); }}
        .stadsdeel-pill.sd-partial {{ background: rgba(196,154,108,0.3); color: var(--gold); border-color: var(--gold); border-style: dashed; }}
        .stadsdeel-pill.sd-none {{ background: transparent; color: var(--muted2); border-color: #252530; }}
        .wijk-pills {{ display: flex; flex-wrap: wrap; gap: 4px; max-height: 100px; overflow-y: auto; }}
        .wijk-pill {{
            padding: 3px 8px; border-radius: 10px; font-size: 10px;
            font-weight: 600; cursor: pointer; border: 1.5px solid #252530;
            background: transparent; color: var(--muted2); white-space: nowrap;
        }}
        .wijk-pill.wijk-all {{ background: var(--gold); color: #0a0b10; border-color: var(--gold); }}
        .wijk-pill.wijk-partial {{ background: rgba(196,154,108,0.3); color: var(--gold); border-color: var(--gold); border-style: dashed; }}
        .wijk-pill.wijk-none {{ background: transparent; color: var(--muted2); border-color: #252530; }}
        #drawerHoodMap {{ height: 200px; border-radius: 8px; margin: 10px 0; border: 1px solid var(--card-border); }}

        /* ── Map view ── */
        #map {{ flex: 1; z-index: 1; }}
        .map-legend {{
            background: var(--card); padding: 10px 16px; display: flex;
            align-items: center; gap: 10px; font-size: 11px; color: var(--muted);
            border-top: 1px solid var(--card-border);
        }}
        .legend-gradient {{
            flex: 1; height: 10px; border-radius: 5px;
            background: linear-gradient(to right, #2a6e4a, #6a8a3a, #c49a6c, #c47a50, #b85a3a, #8b2020);
        }}
        .legend-label {{ white-space: nowrap; }}

        /* Map bottom sheet */
        .map-sheet {{
            position: absolute; bottom: 0; left: 0; right: 0; z-index: 800;
            background: var(--card); border-radius: 16px 16px 0 0;
            max-height: 45vh; overflow-y: auto;
            transform: translateY(100%); transition: transform 0.3s ease;
            border-top: 1px solid var(--card-border);
        }}
        .map-sheet.open {{ transform: translateY(0); }}
        .map-sheet .card {{ border-radius: 0; border-left: none; border-right: none; border-top: none; }}

        /* Leaflet overrides */
        .leaflet-popup-content-wrapper {{
            background: var(--card); color: var(--text); border-radius: 8px;
            border: 1px solid #252530;
        }}
        .leaflet-popup-tip {{ background: var(--card); }}
        .leaflet-popup-content {{ font-size: 13px; line-height: 1.5; }}
        .leaflet-popup-content a {{ color: var(--gold); }}
        .hood-bubble {{ pointer-events: auto; }}
        .bubble-label {{
            background: none !important; border: none !important;
            display: flex; align-items: center; justify-content: center;
        }}
        .bubble-label span {{
            color: #fff; font-size: 11px; font-weight: 700;
            text-shadow: 0 1px 3px rgba(0,0,0,.8); pointer-events: none;
        }}

        /* ── Detail modal ── */
        .modal-overlay {{
            display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.9);
            z-index: 1000; overflow-y: auto;
        }}
        .modal-overlay.open {{ display: block; }}
        .modal-content {{
            background: var(--card); min-height: 100vh;
            animation: slideUp 0.25s ease;
        }}
        @keyframes slideUp {{ from {{ transform: translateY(30px); opacity: 0; }} to {{ transform: none; opacity: 1; }} }}
        .modal-close {{
            position: fixed; top: 12px; right: 12px; background: rgba(0,0,0,0.6);
            border: none; color: #ccc; font-size: 28px; cursor: pointer;
            width: 40px; height: 40px; border-radius: 50%; z-index: 1001;
            display: flex; align-items: center; justify-content: center;
        }}
        .modal-close:active {{ background: rgba(0,0,0,0.9); }}

        /* Photo gallery */
        .gallery {{
            position: relative; width: 100%; height: 280px; background: #0c0d12;
            overflow: hidden;
        }}
        .gallery-track {{
            display: flex; height: 100%; transition: transform 0.3s ease;
            will-change: transform;
        }}
        .gallery-track img {{
            width: 100%; height: 100%; object-fit: cover; flex-shrink: 0;
        }}
        .gallery-counter {{
            position: absolute; bottom: 10px; right: 12px; background: rgba(0,0,0,0.6);
            padding: 3px 8px; border-radius: 10px; font-size: 11px; color: #ccc;
        }}
        .gallery-dots {{
            position: absolute; bottom: 10px; left: 50%; transform: translateX(-50%);
            display: flex; gap: 5px;
        }}
        .gallery-dot {{
            width: 6px; height: 6px; border-radius: 50%; background: rgba(255,255,255,0.3);
        }}
        .gallery-dot.active {{ background: var(--gold); }}

        .modal-body {{ padding: 16px; }}
        .modal-price {{ font-size: 24px; font-weight: 700; color: var(--gold); }}
        .modal-address {{ font-size: 15px; color: var(--text); margin: 4px 0; }}
        .modal-sub {{ color: var(--muted); font-size: 13px; margin-bottom: 12px; }}

        /* Prediction section */
        .pred-section {{
            background: var(--input-bg); border-radius: 10px; padding: 12px;
            margin-bottom: 14px; border: 1px solid var(--card-border);
        }}
        .pred-row {{ display: flex; justify-content: space-between; align-items: center; margin: 4px 0; font-size: 14px; }}
        .pred-row .val {{ font-weight: 600; }}
        .pred-highlight {{ font-size: 16px; font-weight: 700; }}

        /* Property grid */
        .prop-grid {{
            display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 14px;
        }}
        .det {{ background: var(--input-bg); padding: 10px; border-radius: 8px; text-align: center; }}
        .det-label {{ font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.3px; }}
        .det-value {{ font-weight: 600; color: var(--gold); font-size: 14px; }}

        /* Modal sections */
        .modal-section {{ margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--input-border); }}
        .modal-section h4 {{ color: var(--gold); margin-bottom: 8px; font-size: 13px; text-transform: uppercase; letter-spacing: 0.3px; }}
        .modal-row {{ display: flex; justify-content: space-between; align-items: center; margin: 5px 0; font-size: 13px; }}
        .modal-row .val {{ font-weight: 600; }}
        .residual-positive {{ color: var(--green); }}
        .residual-negative {{ color: var(--red); }}

        /* Description */
        .description-text {{
            font-size: 13px; color: var(--muted); line-height: 1.6;
            max-height: 120px; overflow: hidden; position: relative;
            transition: max-height 0.3s;
        }}
        .description-text.expanded {{ max-height: none; }}
        .desc-toggle {{
            color: var(--gold); font-size: 12px; font-weight: 600;
            cursor: pointer; margin-top: 4px; display: inline-block;
        }}

        .modal-actions {{
            margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--input-border);
            display: flex; gap: 10px;
        }}
        .modal-actions a.btn {{
            text-decoration: none; display: flex; align-items: center; justify-content: center;
        }}

        /* ── Desktop overrides (>768px) ── */
        @media (min-width: 769px) {{
            body {{ padding-bottom: 0; }}
            .bottom-nav {{
                position: fixed; top: 0; bottom: auto; left: 0; right: 0;
                height: 52px; border-top: none; border-bottom: 1px solid var(--card-border);
                padding-bottom: 0;
            }}
            .nav-item {{ flex-direction: row; gap: 6px; font-size: 13px; }}
            .nav-item svg {{ width: 18px; height: 18px; }}
            .view {{ padding-top: 52px; }}
            .view-map.active {{ height: calc(100vh - 52px); margin-top: 52px; }}
            .header {{ padding-top: 16px; }}

            .grid {{
                display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
                gap: 14px;
            }}
            .card {{ cursor: pointer; }}
            .card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 24px rgba(0,0,0,.5); border-color: #252530; }}
            .card-img {{ width: 160px; min-height: 130px; }}

            .modal-content {{
                max-width: 700px; margin: 40px auto; min-height: auto;
                border-radius: 12px; border: 1px solid #252530;
            }}
            .modal-close {{ position: absolute; }}
            .gallery {{ height: 400px; }}

            .filter-drawer {{
                max-width: 420px; left: auto; right: 0;
                border-radius: 16px 0 0 0; max-height: calc(100vh - 52px);
            }}

            .prop-grid {{ grid-template-columns: 1fr 1fr 1fr; }}
        }}

        @media (max-width: 360px) {{
            .card-img {{ width: 100px; }}
            .card-price {{ font-size: 16px; }}
            .stat {{ min-width: 75px; padding: 8px 10px; }}
            .stat-value {{ font-size: 15px; }}
        }}
    </style>
</head>
<body>
    <!-- Loading screen -->
    <div class="loading" id="loadingScreen">
        <div class="spinner"></div>
        <h2>Ground Control</h2>
        <div style="color:#5a5650;font-size:12px">Loading listings...</div>
    </div>

    <!-- Bottom navigation -->
    <nav class="bottom-nav" id="bottomNav">
        <button class="nav-item active" data-view="list" onclick="switchView('list')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
            <span>List</span>
        </button>
        <button class="nav-item" data-view="map" onclick="switchView('map')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4-7 4z"/><path d="M8 2v16"/><path d="M16 6v16"/></svg>
            <span>Map</span>
        </button>
        <button class="nav-item" data-view="favs" onclick="switchView('favs')">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z"/></svg>
            <span>Saved</span>
            <span class="nav-badge" id="navFavBadge"></span>
        </button>
        <button class="nav-item" data-view="filters" onclick="openFilterDrawer()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>
            <span>Filters</span>
            <span class="nav-badge" id="navFilterBadge"></span>
        </button>
    </nav>

    <!-- ═══ LIST VIEW ═══ -->
    <div class="view view-list active" id="viewList">
        <div class="header">
            <h1>Ground Control</h1>
            <span class="subtitle" id="genTime"></span>
        </div>
        <div class="search-wrap">
            <input type="text" id="searchInput" placeholder="Search address, postcode, neighbourhood..." autocomplete="off">
        </div>
        <div class="stats-bar" id="statsBar"></div>
        <div class="filter-summary" id="filterSummary"></div>
        <div class="result-bar">
            <span>Showing <strong id="showCount">0</strong> of <strong id="totalCount">0</strong></span>
            <select class="sort-select" id="fSort" onchange="applyFilters()">
                <option value="score">Best deal</option>
                <option value="price_asc">Price &uarr;</option>
                <option value="price_desc">Price &darr;</option>
                <option value="pm2_asc">EUR/m&sup2; &uarr;</option>
                <option value="area_desc">Largest</option>
                <option value="beds_desc">Most beds</option>
                <option value="newest">Newest</option>
                <option value="dom_desc">Longest listed</option>
                <option value="underpriced">Most underpriced</option>
            </select>
        </div>
        <div class="grid" id="grid"></div>
        <div id="loadMore" style="height:1px;"></div>
    </div>

    <!-- ═══ MAP VIEW ═══ -->
    <div class="view view-map" id="viewMap">
        <div id="map"></div>
        <div class="map-legend">
            <span class="legend-label">&euro;3.5k/m&sup2;</span>
            <div class="legend-gradient"></div>
            <span class="legend-label">&euro;11.5k/m&sup2;</span>
        </div>
        <div class="map-sheet" id="mapSheet">
            <div class="drawer-handle"></div>
            <div id="mapSheetContent"></div>
        </div>
    </div>

    <!-- ═══ FAVOURITES VIEW ═══ -->
    <div class="view view-favs" id="viewFavs">
        <div class="header"><h1>Saved Properties</h1></div>
        <div class="result-bar" style="padding-top:12px;">
            <span><strong id="favCount">0</strong> saved</span>
        </div>
        <div class="grid" id="favGrid"></div>
        <div id="favEmpty" style="text-align:center;padding:60px 20px;color:#5a5650;display:none;">
            <h3 style="color:var(--muted2);margin-bottom:8px;">No saved properties</h3>
            <p style="font-size:13px;">Tap the heart on any listing to save it here.</p>
        </div>
    </div>

    <!-- ═══ FILTER DRAWER ═══ -->
    <div class="drawer-overlay" id="drawerOverlay" onclick="closeFilterDrawer()"></div>
    <div class="filter-drawer" id="filterDrawer">
        <div class="drawer-handle"></div>
        <div class="drawer-header">
            <h3>Filters</h3>
            <button class="btn btn-ghost" style="padding:6px 12px;flex:0;" onclick="resetFilters()">Reset</button>
        </div>

        <div class="drawer-section">
            <h4>Price Range</h4>
            <div class="drawer-row">
                <input type="number" id="fMinPrice" placeholder="Min &euro;" step="10000">
                <input type="number" id="fMaxPrice" placeholder="Max &euro;" step="10000">
            </div>
        </div>

        <div class="drawer-section">
            <h4>Living Area (m&sup2;)</h4>
            <div class="drawer-row">
                <input type="number" id="fMinArea" placeholder="Min" step="5">
                <input type="number" id="fMaxArea" placeholder="Max" step="5">
            </div>
        </div>

        <div class="drawer-section">
            <h4>Bedrooms</h4>
            <div class="drawer-row">
                <input type="number" id="fMinBed" placeholder="Min" min="0" max="10">
            </div>
        </div>

        <div class="drawer-section">
            <h4>Energy Label</h4>
            <div class="drawer-row">
                <select id="fEnergy">
                    <option value="">All</option>
                    <option value="A">A+</option>
                    <option value="B">B</option>
                    <option value="C">C</option>
                    <option value="D">D</option>
                    <option value="E">E+</option>
                </select>
            </div>
        </div>

        <div class="drawer-section">
            <h4>Status</h4>
            <div class="drawer-toggles">
                <button class="drawer-toggle active" id="dtAvailable" onclick="toggleStatus('available')">Available</button>
                <button class="drawer-toggle active" id="dtNegotiations" onclick="toggleStatus('negotiations')">Under Offer</button>
                <button class="drawer-toggle toggle-sold" id="dtSold" onclick="toggleStatus('sold')">Sold</button>
            </div>
        </div>

        <div class="drawer-section">
            <h4>Quick Filters</h4>
            <div class="drawer-toggles">
                <button class="drawer-toggle" id="dtNewOnly" onclick="toggleQuick('new')">New (24h)</button>
                <button class="drawer-toggle" id="dtDropOnly" onclick="toggleQuick('drop')">Price Drops</button>
            </div>
        </div>

        <div class="hood-section" id="hoodSection">
            <h4 style="font-size:12px;color:var(--muted2);text-transform:uppercase;letter-spacing:0.3px;margin-bottom:10px;">
                Neighbourhoods <span id="hoodExcludeCount" style="color:#888;font-size:11px;"></span>
            </h4>
            <div class="stadsdeel-pills" id="stadsdeelPills"></div>
            <div class="wijk-pills" id="wijkPills"></div>
            <div id="drawerHoodMap"></div>
            <div style="display:flex;gap:6px;margin-top:8px;">
                <button class="btn btn-ghost" style="padding:6px 10px;font-size:11px;flex:1;" onclick="hoodSelectAll(true)">Select All</button>
                <button class="btn btn-ghost" style="padding:6px 10px;font-size:11px;flex:1;" onclick="hoodSelectAll(false)">Deselect All</button>
                <button class="btn btn-ghost" style="padding:6px 10px;font-size:11px;flex:1;" onclick="hoodInvert()">Invert</button>
            </div>
        </div>

        <div class="drawer-actions">
            <button class="btn" onclick="applyFilters(); closeFilterDrawer();">Apply Filters</button>
        </div>
    </div>

    <!-- ═══ DETAIL MODAL ═══ -->
    <div class="modal-overlay" id="modalOverlay">
        <div class="modal-content" id="modalContent"></div>
    </div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"
        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>
<script>
// ═══════════════════════════════════════════
// Ground Control — Mobile-First Dashboard
// ═══════════════════════════════════════════

let LISTINGS = [], STATS = {{}}, NEIGHBOURHOOD_STATS = {{}}, MAP_DATA = {{}}, GENERATED_AT = '';
const PAGE_SIZE = 50;
let filtered = [], showing = 0, currentView = 'list';
let leafletMap = null, mapMarkers = [];
let hoodSelectorMap = null, hoodMapMarkers = {{}};
let excludedHoods = new Set(JSON.parse(localStorage.getItem('gc_excluded_hoods') || '[]'));
let favourites = new Set(JSON.parse(localStorage.getItem('gc_favourites') || '[]'));
let activeStatuses = new Set(['available', 'negotiations']);
let quickFilters = {{ new: false, drop: false }};
let hoodSortCol = -1, hoodSortAsc = true;

// ── Data loading ──
async function loadData() {{
    try {{
        const resp = await fetch('listings.json');
        if (!resp.ok) throw new Error('Failed to load data');
        const data = await resp.json();
        LISTINGS = data.listings;
        STATS = data.stats;
        NEIGHBOURHOOD_STATS = data.neighbourhood_stats;
        MAP_DATA = data.map_data;
        GENERATED_AT = data.generated_at;
        document.getElementById('loadingScreen').classList.add('hidden');
        init();
    }} catch (err) {{
        document.getElementById('loadingScreen').innerHTML =
            `<h2 style="color:#c49a6c">Ground Control</h2><p style="color:#7a3030;margin-top:10px;">Failed to load data: ${{err.message}}</p>`;
    }}
}}

// ── Init ──
function init() {{
    document.getElementById('genTime').textContent =
        GENERATED_AT ? GENERATED_AT.slice(0, 16).replace('T', ' ') + ' UTC' : '';
    renderStats();
    buildHierarchy();
    updateFavCount();
    applyFilters();
    setupListeners();
}}

function renderStats() {{
    const s = STATS;
    const newToday = LISTINGS.filter(l => isNew(l)).length;
    const drops = LISTINGS.filter(l => hasDrop(l)).length;
    const underpriced = LISTINGS.filter(l => l.residual && l.residual > 0 && l.is_active).length;
    // Compute median predicted price
    const predictedPrices = LISTINGS.filter(l => l.predicted_price && l.is_active).map(l => l.predicted_price).sort((a, b) => a - b);
    const medianPredicted = predictedPrices.length > 0 ? predictedPrices[Math.floor(predictedPrices.length / 2)] : 0;

    document.getElementById('statsBar').innerHTML = `
        <div class="stat"><div class="stat-value">${{s.listing_count || 0}}</div><div class="stat-label">Active</div></div>
        <div class="stat"><div class="stat-value">${{newToday}}</div><div class="stat-label">New 24h</div></div>
        <div class="stat"><div class="stat-value">${{drops}}</div><div class="stat-label">Drops</div></div>
        <div class="stat"><div class="stat-value">${{underpriced}}</div><div class="stat-label">Underpriced</div></div>
        <div class="stat"><div class="stat-value">&euro;${{Math.round(s.avg_price_m2 || 0).toLocaleString()}}</div><div class="stat-label">Avg /m&sup2;</div></div>
        <div class="stat"><div class="stat-value">&euro;${{Math.round(s.median_price || 0).toLocaleString()}}</div><div class="stat-label">Median</div></div>
        <div class="stat"><div class="stat-value">&euro;${{Math.round(medianPredicted).toLocaleString()}}</div><div class="stat-label">Med. Pred.</div></div>
        <div class="stat"><div class="stat-value">${{Math.round(s.median_days_on_market || 0)}}d</div><div class="stat-label">Med. DOM</div></div>
    `;
}}

function isNew(l) {{
    if (!l.first_seen) return false;
    return (new Date(GENERATED_AT) - new Date(l.first_seen)) < 86400000;
}}
function hasDrop(l) {{
    return l.previous_price && l.previous_price > l.price_numeric;
}}
function matchesSearch(l, term) {{
    const h = `${{l.address||''}} ${{l.postcode||''}} ${{l.neighbourhood||''}} ${{l.city||''}} ${{l.agent_name||''}}`.toLowerCase();
    return term.split(/\\s+/).filter(Boolean).every(w => h.includes(w));
}}

// ── Favourites ──
function toggleFav(e, globalId) {{
    if (e) e.stopPropagation();
    if (favourites.has(globalId)) favourites.delete(globalId);
    else favourites.add(globalId);
    localStorage.setItem('gc_favourites', JSON.stringify([...favourites]));
    document.querySelectorAll(`.fav-btn[data-id="${{globalId}}"]`).forEach(btn => {{
        btn.classList.toggle('faved', favourites.has(globalId));
        btn.innerHTML = favourites.has(globalId) ? '&#9829;' : '&#9825;';
    }});
    updateFavCount();
    if (currentView === 'favs') renderFavs();
}}
function updateFavCount() {{
    const n = favourites.size;
    document.getElementById('navFavBadge').textContent = n > 0 ? n : '';
    const fc = document.getElementById('favCount');
    if (fc) fc.textContent = n;
}}

// ── View switching ──
function switchView(view) {{
    currentView = view;
    document.querySelectorAll('.nav-item').forEach(ni => {{
        ni.classList.toggle('active', ni.dataset.view === view);
    }});
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));

    if (view === 'list') {{
        document.getElementById('viewList').classList.add('active');
    }} else if (view === 'map') {{
        document.getElementById('viewMap').classList.add('active');
        initMap();
        setTimeout(() => {{ leafletMap.invalidateSize(); updateMap(); }}, 100);
    }} else if (view === 'favs') {{
        document.getElementById('viewFavs').classList.add('active');
        renderFavs();
    }}
}}

// ── Filter drawer ──
function openFilterDrawer() {{
    document.getElementById('drawerOverlay').classList.add('open');
    document.getElementById('filterDrawer').classList.add('open');
    document.body.style.overflow = 'hidden';
    initHoodMap();
}}
function closeFilterDrawer() {{
    document.getElementById('drawerOverlay').classList.remove('open');
    document.getElementById('filterDrawer').classList.remove('open');
    document.body.style.overflow = '';
}}
function toggleStatus(status) {{
    if (activeStatuses.has(status)) activeStatuses.delete(status);
    else activeStatuses.add(status);
    const map = {{ available: 'dtAvailable', negotiations: 'dtNegotiations', sold: 'dtSold' }};
    document.getElementById(map[status]).classList.toggle('active', activeStatuses.has(status));
}}
function toggleQuick(key) {{
    quickFilters[key] = !quickFilters[key];
    const map = {{ new: 'dtNewOnly', drop: 'dtDropOnly' }};
    document.getElementById(map[key]).classList.toggle('active', quickFilters[key]);
}}

// ── Filtering ──
function applyFilters() {{
    const minP = parseInt(document.getElementById('fMinPrice').value) || 0;
    const maxP = parseInt(document.getElementById('fMaxPrice').value) || Infinity;
    const minA = parseInt(document.getElementById('fMinArea').value) || 0;
    const maxA = parseInt(document.getElementById('fMaxArea').value) || Infinity;
    const minB = parseInt(document.getElementById('fMinBed').value) || 0;
    const energy = document.getElementById('fEnergy').value;
    const searchTerm = (document.getElementById('searchInput').value || '').toLowerCase().trim();
    const sort = document.getElementById('fSort').value;

    filtered = LISTINGS.filter(l => {{
        if (l.price_numeric < minP || l.price_numeric > maxP) return false;
        if ((l.living_area || 0) < minA || (l.living_area || 0) > maxA) return false;
        if ((l.bedrooms || 0) < minB) return false;
        if (energy) {{
            const el = (l.energy_label || '').replace(/[+]/g, '');
            if (energy === 'A' && !['A', 'A+', 'A++', 'A+++', 'A++++'].includes(l.energy_label)) return false;
            if (energy === 'E' && !['E', 'F', 'G'].includes(el)) return false;
            if (energy !== 'A' && energy !== 'E' && el !== energy) return false;
        }}
        if (!activeStatuses.has(l.availability_status || 'available')) return false;
        if (excludedHoods.has(l.neighbourhood)) return false;
        if (quickFilters.new && !isNew(l)) return false;
        if (quickFilters.drop && !hasDrop(l)) return false;
        if (searchTerm && !matchesSearch(l, searchTerm)) return false;
        return true;
    }});

    const sorters = {{
        score: (a, b) => (b.score || 0) - (a.score || 0),
        price_asc: (a, b) => a.price_numeric - b.price_numeric,
        price_desc: (a, b) => b.price_numeric - a.price_numeric,
        pm2_asc: (a, b) => (a.price_m2 || 99999) - (b.price_m2 || 99999),
        area_desc: (a, b) => (b.living_area || 0) - (a.living_area || 0),
        beds_desc: (a, b) => (b.bedrooms || 0) - (a.bedrooms || 0),
        newest: (a, b) => (b.first_seen || '').localeCompare(a.first_seen || ''),
        dom_desc: (a, b) => ((b.score_details?.days_on_market || 0) - (a.score_details?.days_on_market || 0)),
        underpriced: (a, b) => (b.residual || 0) - (a.residual || 0),
    }};
    filtered.sort(sorters[sort] || sorters.score);

    showing = 0;
    document.getElementById('grid').innerHTML = '';
    document.getElementById('showCount').textContent = '0';
    document.getElementById('totalCount').textContent = filtered.length;

    if (filtered.length === 0) {{
        document.getElementById('grid').innerHTML = `
            <div style="text-align:center;padding:60px 20px;color:var(--muted);">
                <h3 style="color:var(--muted2);margin-bottom:8px;">No properties match</h3>
                <p style="font-size:13px;">Try adjusting your filters.</p>
            </div>`;
    }} else {{
        loadMore();
    }}
    if (currentView === 'map' && leafletMap) updateMap();
    updateFilterBadge();
    renderFilterSummary();
}}

function updateFilterBadge() {{
    let count = 0;
    if (document.getElementById('fMinPrice').value) count++;
    if (document.getElementById('fMaxPrice').value) count++;
    if (document.getElementById('fMinArea').value) count++;
    if (document.getElementById('fMaxArea').value) count++;
    if (document.getElementById('fMinBed').value) count++;
    if (document.getElementById('fEnergy').value) count++;
    if (quickFilters.new) count++;
    if (quickFilters.drop) count++;
    const search = document.getElementById('searchInput');
    if (search && search.value.trim()) count++;
    if (!activeStatuses.has('available') || !activeStatuses.has('negotiations') || activeStatuses.has('sold')) count++;
    if (excludedHoods.size > 0) count++;
    document.getElementById('navFilterBadge').textContent = count > 0 ? count : '';
}}

function renderFilterSummary() {{
    const chips = [];
    chips.push(`<button class="filter-chip ${{activeStatuses.has('available') ? 'active' : ''}}" onclick="toggleStatus('available');applyFilters()">Available</button>`);
    chips.push(`<button class="filter-chip ${{activeStatuses.has('negotiations') ? 'active' : ''}}" onclick="toggleStatus('negotiations');applyFilters()">Under Offer</button>`);
    chips.push(`<button class="filter-chip ${{activeStatuses.has('sold') ? 'active' : ''}} chip-sold" onclick="toggleStatus('sold');applyFilters()">Sold</button>`);
    if (quickFilters.new) chips.push(`<button class="filter-chip active" onclick="toggleQuick('new');applyFilters()">New 24h</button>`);
    if (quickFilters.drop) chips.push(`<button class="filter-chip active" onclick="toggleQuick('drop');applyFilters()">Drops</button>`);
    if (excludedHoods.size > 0) chips.push(`<button class="filter-chip active" onclick="openFilterDrawer()">${{excludedHoods.size}} hoods hidden</button>`);
    document.getElementById('filterSummary').innerHTML = chips.join('');
}}

function resetFilters() {{
    document.getElementById('fMinPrice').value = '';
    document.getElementById('fMaxPrice').value = '';
    document.getElementById('fMinArea').value = '';
    document.getElementById('fMaxArea').value = '';
    document.getElementById('fMinBed').value = '';
    document.getElementById('fEnergy').value = '';
    document.getElementById('fSort').value = 'score';
    document.getElementById('searchInput').value = '';
    activeStatuses = new Set(['available', 'negotiations']);
    quickFilters = {{ new: false, drop: false }};
    document.getElementById('dtAvailable').classList.add('active');
    document.getElementById('dtNegotiations').classList.add('active');
    document.getElementById('dtSold').classList.remove('active');
    document.getElementById('dtNewOnly').classList.remove('active');
    document.getElementById('dtDropOnly').classList.remove('active');
    applyFilters();
}}

// ── Card rendering ──
function loadMore() {{
    const grid = document.getElementById('grid');
    const end = Math.min(showing + PAGE_SIZE, filtered.length);
    for (let i = showing; i < end; i++) grid.appendChild(createCard(filtered[i]));
    showing = end;
    document.getElementById('showCount').textContent = showing;
}}

function createCard(l) {{
    const div = document.createElement('div');
    const isSold = l.availability_status === 'sold';
    const isOffer = l.availability_status === 'negotiations';
    div.className = 'card' + (isSold ? ' card-sold' : '');
    div.onclick = () => openModal(l.global_id);

    const isN = isNew(l);
    const drop = hasDrop(l);
    const dropPct = drop ? Math.round((1 - l.price_numeric / l.previous_price) * 100) : 0;

    let sc = 'score-low';
    if (l.score >= 15) sc = 'score-high';
    else if (l.score >= 5) sc = 'score-mid';

    const elBase = (l.energy_label || '').replace(/[+]/g, '');

    // Prediction badge
    let predBadge = '';
    if (l.predicted_price) {{
        const diff = l.price_numeric - l.predicted_price;
        const absDiff = Math.abs(Math.round(diff / 1000));
        if (diff < 0) predBadge = `<span class="card-pred-badge pred-under">&darr; &euro;${{absDiff}}k under</span>`;
        else predBadge = `<span class="card-pred-badge pred-over">&uarr; &euro;${{absDiff}}k over</span>`;
    }}

    const prevHtml = drop ? `<span class="card-prev-price">&euro;${{l.previous_price.toLocaleString()}}</span>` : '';
    const imgUrl = l.image_url || (l.photo_urls && l.photo_urls.length > 0 ? l.photo_urls[0] : '');

    div.innerHTML = `
        <div class="badges">
            ${{isSold ? '<span class="badge badge-sold">Sold</span>' : ''}}
            ${{isOffer ? '<span class="badge badge-offer">Offer</span>' : ''}}
            ${{isN ? '<span class="badge badge-new">New</span>' : ''}}
            ${{drop ? `<span class="badge badge-drop">-${{dropPct}}%</span>` : ''}}
        </div>
        <div class="card-actions">
            <span class="badge-score ${{sc}}">${{l.score?.toFixed(1) || '—'}}</span>
            <button class="fav-btn ${{favourites.has(l.global_id) ? 'faved' : ''}}" data-id="${{l.global_id}}"
                onclick="toggleFav(event,${{l.global_id}})">${{favourites.has(l.global_id) ? '&#9829;' : '&#9825;'}}</button>
        </div>
        <div class="card-top">
            <div class="card-img">${{imgUrl ? `<img src="${{imgUrl}}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}}</div>
            <div class="card-body">
                <div class="card-price-row">
                    <span class="card-price">&euro;${{l.price_numeric.toLocaleString()}}</span>
                    ${{prevHtml}}
                    ${{predBadge}}
                </div>
                <div class="card-address">${{l.address || 'Unknown'}}</div>
                <div class="card-stats">
                    ${{l.living_area ? `<span>${{l.living_area}}m&sup2;</span>` : ''}}
                    ${{l.bedrooms != null ? `<span>${{l.bedrooms}} bed</span>` : ''}}
                    ${{l.energy_label ? `<span class="el-${{elBase}}">${{l.energy_label}}</span>` : ''}}
                    ${{l.year_built ? `<span>${{l.year_built}}</span>` : ''}}
                    ${{l.price_m2 ? `<span>&euro;${{Math.round(l.price_m2).toLocaleString()}}/m&sup2;</span>` : ''}}
                </div>
            </div>
        </div>
    `;
    return div;
}}

// ── Favourites view ──
function renderFavs() {{
    const grid = document.getElementById('favGrid');
    const empty = document.getElementById('favEmpty');
    grid.innerHTML = '';
    const favListings = LISTINGS.filter(l => favourites.has(l.global_id));
    document.getElementById('favCount').textContent = favListings.length;
    if (favListings.length === 0) {{
        empty.style.display = 'block';
        return;
    }}
    empty.style.display = 'none';
    favListings.forEach(l => grid.appendChild(createCard(l)));
}}

// ── Map ──
function initMap() {{
    if (leafletMap) return;
    leafletMap = L.map('map').setView([52.3676, 4.9041], 12);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd', maxZoom: 19
    }}).addTo(leafletMap);
}}

function priceToColor(priceM2) {{
    const min = 3500, max = 11500;
    const t = Math.max(0, Math.min(1, (priceM2 - min) / (max - min)));
    let r, g, b;
    if (t < 0.5) {{
        const s = t * 2;
        r = Math.round(42 + s * 154); g = Math.round(110 + s * 44); b = Math.round(74 - s * 30);
    }} else {{
        const s = (t - 0.5) * 2;
        r = Math.round(196 + s * 16); g = Math.round(154 - s * 96); b = Math.round(44 - s * 12);
    }}
    return `rgb(${{r}},${{g}},${{b}})`;
}}

function bubbleRadius(count) {{
    return Math.max(8, Math.min(40, 8 + Math.sqrt(count) * 5.75));
}}

function updateMap() {{
    if (!leafletMap) return;

    // Clear existing markers
    mapMarkers.forEach(m => leafletMap.removeLayer(m));
    mapMarkers = [];

    // Aggregate filtered listings by neighbourhood
    const agg = {{}};
    filtered.forEach(l => {{
        const hood = l.neighbourhood;
        if (!hood || !MAP_DATA[hood]) return;
        if (!agg[hood]) agg[hood] = {{ listings: [], totalPm2: 0, count: 0 }};
        agg[hood].listings.push(l);
        if (l.price_m2) {{ agg[hood].totalPm2 += l.price_m2; agg[hood].count++; }}
    }});

    Object.entries(agg).forEach(([hood, data]) => {{
        const md = MAP_DATA[hood];
        const avgPm2 = data.count > 0 ? data.totalPm2 / data.count : md.avg_price_m2;
        const color = priceToColor(avgPm2);
        const radius = bubbleRadius(data.listings.length);

        const marker = L.circleMarker([md.lat, md.lng], {{
            radius: radius,
            fillColor: color,
            color: '#fff',
            weight: 1,
            opacity: 0.8,
            fillOpacity: 0.7,
        }}).addTo(leafletMap);

        // Count label inside bubble
        const label = L.marker([md.lat, md.lng], {{
            icon: L.divIcon({{
                className: 'bubble-label',
                html: `<span>${{data.listings.length}}</span>`,
                iconSize: [radius * 2, radius * 2],
                iconAnchor: [radius, radius],
            }}),
            interactive: false,
        }}).addTo(leafletMap);
        mapMarkers.push(label);

        // Build popup with top 5 listings
        const top5 = data.listings
            .sort((a, b) => (a.price_m2 || 99999) - (b.price_m2 || 99999))
            .slice(0, 5);

        let popupHtml = `<strong>${{hood}}</strong><br>`;
        popupHtml += `<span style="color:#888">${{data.listings.length}} listings &middot; Avg &euro;${{Math.round(avgPm2).toLocaleString()}}/m&sup2;</span>`;

        if (top5.length > 0) {{
            popupHtml += '<div style="margin-top:6px">';
            top5.forEach(l => {{
                popupHtml += `<div class="popup-listing">`;
                popupHtml += `<a href="${{l.detail_url}}" target="_blank">&euro;${{l.price_numeric.toLocaleString()}}</a>`;
                popupHtml += ` &middot; ${{l.living_area || '?'}}m&sup2;`;
                if (l.price_m2) popupHtml += ` &middot; &euro;${{Math.round(l.price_m2).toLocaleString()}}/m&sup2;`;
                popupHtml += `<br><span style="color:#888;font-size:11px">${{l.address || ''}}</span>`;
                popupHtml += `</div>`;
            }});
            popupHtml += '</div>';
        }}

        marker.bindPopup(popupHtml, {{ maxWidth: 300 }});
        mapMarkers.push(marker);
    }});
}}

// ── Hood map (in drawer) ──
function initHoodMap() {{
    if (hoodSelectorMap) {{
        hoodSelectorMap.invalidateSize();
        return;
    }}
    const el = document.getElementById('drawerHoodMap');
    if (!el) return;
    hoodSelectorMap = L.map('drawerHoodMap').setView([52.3676, 4.9041], 11);
    L.tileLayer('https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png', {{
        attribution: '', subdomains: 'abcd', maxZoom: 19
    }}).addTo(hoodSelectorMap);
    Object.entries(MAP_DATA).forEach(([name, d]) => {{
        const included = !excludedHoods.has(name);
        const m = L.circleMarker([d.lat, d.lng], {{
            radius: 8, fillColor: included ? '#c49a6c' : 'transparent',
            color: included ? '#c49a6c' : '#7a3030',
            weight: included ? 1 : 2, fillOpacity: included ? 0.7 : 0, opacity: 0.9,
        }}).addTo(hoodSelectorMap);
        m.bindTooltip(name);
        m.on('click', () => onHoodMapClick(name));
        hoodMapMarkers[name] = m;
    }});
}}

function onHoodMapClick(name) {{
    if (excludedHoods.has(name)) excludedHoods.delete(name);
    else excludedHoods.add(name);
    updateHoodMapMarker(name);
    updateAllWijkPills();
    updateAllStadsdeelPills();
    saveExcludedHoods();
}}
function updateHoodMapMarker(name) {{
    const m = hoodMapMarkers[name];
    if (!m) return;
    const inc = !excludedHoods.has(name);
    m.setStyle({{ fillColor: inc ? '#c49a6c' : 'transparent', color: inc ? '#c49a6c' : '#7a3030', weight: inc ? 1 : 2, fillOpacity: inc ? 0.7 : 0 }});
}}
function updateAllHoodMapMarkers() {{ Object.keys(hoodMapMarkers).forEach(updateHoodMapMarker); }}

// ── Hood hierarchy ──
const stadsdeelGroups = {{}}, wijkGroups = {{}}, wijkToStadsdeel = {{}};
function buildHierarchy() {{
    Object.entries(MAP_DATA).forEach(([name, d]) => {{
        const wijk = d.wijk || '(unknown)';
        const sd = d.stadsdeel || '(unknown)';
        if (!wijkGroups[wijk]) wijkGroups[wijk] = [];
        wijkGroups[wijk].push(name);
        if (!stadsdeelGroups[sd]) stadsdeelGroups[sd] = [];
        stadsdeelGroups[sd].push(name);
        wijkToStadsdeel[wijk] = sd;
    }});
    renderStadsdeelPills();
    renderWijkPills();
}}

function getStadsdeelState(sd) {{
    const b = stadsdeelGroups[sd] || [];
    if (b.length === 0) return 'none';
    const exc = b.filter(x => excludedHoods.has(x)).length;
    if (exc === 0) return 'all'; if (exc === b.length) return 'none'; return 'partial';
}}
function getWijkState(w) {{
    const b = wijkGroups[w] || [];
    if (b.length === 0) return 'none';
    const exc = b.filter(x => excludedHoods.has(x)).length;
    if (exc === 0) return 'all'; if (exc === b.length) return 'none'; return 'partial';
}}
function renderStadsdeelPills() {{
    const c = document.getElementById('stadsdeelPills');
    if (!c) return;
    c.innerHTML = Object.keys(stadsdeelGroups).sort().map(sd => {{
        const state = getStadsdeelState(sd);
        const count = stadsdeelGroups[sd].length;
        return `<button class="stadsdeel-pill sd-${{state}}" data-sd="${{sd}}" onclick="toggleStadsdeel('${{sd.replace(/'/g, "\\\\'")}}')">${{sd}} (${{count}})</button>`;
    }}).join('');
}}
function renderWijkPills() {{
    const c = document.getElementById('wijkPills');
    if (!c) return;
    c.innerHTML = Object.keys(wijkGroups).sort().map(w => {{
        const state = getWijkState(w);
        const count = wijkGroups[w].length;
        return `<button class="wijk-pill wijk-${{state}}" data-wijk="${{w}}" onclick="toggleWijk('${{w.replace(/'/g, "\\\\'")}}')">${{w}} (${{count}})</button>`;
    }}).join('');
}}
function toggleStadsdeel(sd) {{
    const buurten = stadsdeelGroups[sd] || [];
    const state = getStadsdeelState(sd);
    if (state === 'none') buurten.forEach(b => excludedHoods.delete(b));
    else buurten.forEach(b => excludedHoods.add(b));
    saveExcludedHoods(); updateAllHoodMapMarkers(); updateAllWijkPills(); updateAllStadsdeelPills();
}}
function toggleWijk(w) {{
    const buurten = wijkGroups[w] || [];
    const state = getWijkState(w);
    if (state === 'none') buurten.forEach(b => excludedHoods.delete(b));
    else buurten.forEach(b => excludedHoods.add(b));
    saveExcludedHoods(); updateAllHoodMapMarkers(); updateAllWijkPills(); updateAllStadsdeelPills();
}}
function updateAllStadsdeelPills() {{
    document.querySelectorAll('.stadsdeel-pill').forEach(p => {{
        p.className = `stadsdeel-pill sd-${{getStadsdeelState(p.dataset.sd)}}`;
    }});
}}
function updateAllWijkPills() {{
    document.querySelectorAll('.wijk-pill').forEach(p => {{
        p.className = `wijk-pill wijk-${{getWijkState(p.dataset.wijk)}}`;
    }});
}}
function hoodSelectAll(include) {{
    excludedHoods = include ? new Set() : new Set(Object.keys(NEIGHBOURHOOD_STATS));
    saveExcludedHoods(); updateAllHoodMapMarkers(); updateAllWijkPills(); updateAllStadsdeelPills();
}}
function hoodInvert() {{
    const newExc = new Set(Object.keys(NEIGHBOURHOOD_STATS).filter(h => !excludedHoods.has(h)));
    excludedHoods = newExc;
    saveExcludedHoods(); updateAllHoodMapMarkers(); updateAllWijkPills(); updateAllStadsdeelPills();
}}
function saveExcludedHoods() {{
    localStorage.setItem('gc_excluded_hoods', JSON.stringify([...excludedHoods]));
    const n = excludedHoods.size;
    const el = document.getElementById('hoodExcludeCount');
    if (el) el.textContent = n > 0 ? `(${{n}} hidden)` : '';
}}

// ── Detail modal ──
function openModal(globalId) {{
    const l = LISTINGS.find(x => x.global_id === globalId);
    if (!l) return;
    const overlay = document.getElementById('modalOverlay');
    const content = document.getElementById('modalContent');
    const isFaved = favourites.has(l.global_id);
    const drop = hasDrop(l);
    const dropPct = drop ? Math.round((1 - l.price_numeric / l.previous_price) * 100) : 0;
    const elBase = (l.energy_label || '').replace(/[+]/g, '');

    // Photo gallery
    const photos = (l.photo_urls && l.photo_urls.length > 0) ? l.photo_urls : (l.image_url ? [l.image_url] : []);
    let galleryHtml = '';
    if (photos.length > 0) {{
        const imgs = photos.slice(0, 20).map(u => `<img src="${{u}}" alt="" referrerpolicy="no-referrer">`).join('');
        const dots = photos.slice(0, 20).map((_, i) => `<div class="gallery-dot ${{i === 0 ? 'active' : ''}}" data-i="${{i}}"></div>`).join('');
        galleryHtml = `
            <div class="gallery" id="gallery" data-idx="0" data-max="${{Math.min(photos.length, 20)}}">
                <div class="gallery-track" id="galleryTrack">${{imgs}}</div>
                <div class="gallery-counter"><span id="galIdx">1</span>/${{Math.min(photos.length, 20)}}</div>
                <div class="gallery-dots" id="galleryDots">${{dots}}</div>
            </div>`;
    }}

    // ML prediction section
    let predHtml = '';
    if (l.predicted_price) {{
        const diff = l.price_numeric - l.predicted_price;
        const diffPct = ((diff / l.predicted_price) * 100).toFixed(1);
        const cls = diff > 0 ? 'residual-negative' : 'residual-positive';
        const label = diff > 0 ? 'overpriced' : 'underpriced';
        predHtml = `<div class="pred-section">
            <div class="pred-row"><span>ML Predicted</span><span class="val" style="color:var(--gold);font-size:16px;font-weight:700">&euro;${{Math.round(l.predicted_price).toLocaleString()}}</span></div>
            <div class="pred-row"><span>Asking Price</span><span class="val">&euro;${{l.price_numeric.toLocaleString()}}</span></div>
            <div class="pred-row"><span>Difference</span><span class="val ${{cls}} pred-highlight">&euro;${{Math.abs(Math.round(diff)).toLocaleString()}} (${{Math.abs(diffPct)}}% ${{label}})</span></div>
        </div>`;
    }}

    // Score breakdown
    let scoreHtml = '';
    if (l.score_details) {{
        const sd = l.score_details;
        scoreHtml = `<div class="modal-section"><h4>Deal Score</h4>
            <div class="modal-row"><span>vs Neighbourhood</span><span class="val">${{sd.vs_neighbourhood_pct != null ? sd.vs_neighbourhood_pct + '%' : 'n/a'}}</span></div>
            <div class="modal-row"><span>vs City avg</span><span class="val">${{sd.vs_city_pct != null ? sd.vs_city_pct + '%' : 'n/a'}}</span></div>
            <div class="modal-row"><span>Days on market</span><span class="val">${{sd.days_on_market ?? '?'}}</span></div>
            <div class="modal-row"><span><strong>Total</strong></span><span class="val" style="color:var(--gold)"><strong>${{l.score?.toFixed(1) || '--'}}</strong></span></div>
        </div>`;
    }}

    // Price history
    let historyHtml = '';
    if (l.price_history && l.price_history.length > 0) {{
        historyHtml = `<div class="modal-section"><h4>Price History</h4>` +
            l.price_history.map(h => `<div class="modal-row"><span>${{h.date}}</span><span>&euro;${{h.old_price.toLocaleString()}} &rarr; &euro;${{h.new_price.toLocaleString()}}</span></div>`).join('') +
            `</div>`;
    }}

    // Description
    let descHtml = '';
    if (l.description) {{
        const cleanDesc = l.description.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        descHtml = `<div class="modal-section"><h4>Description</h4>
            <div class="description-text" id="descText">${{cleanDesc}}</div>
            <span class="desc-toggle" onclick="document.getElementById('descText').classList.toggle('expanded'); this.textContent = this.textContent === 'Show more' ? 'Show less' : 'Show more';">Show more</span>
        </div>`;
    }}

    // Financials
    let finHtml = '';
    const finItems = [];
    if (l.vve_contribution) finItems.push(['VvE', l.vve_contribution.length > 60 ? l.vve_contribution.slice(0, 60) + '...' : l.vve_contribution]);
    if (l.erfpacht) finItems.push(['Erfpacht', l.erfpacht.length > 60 ? l.erfpacht.slice(0, 60) + '...' : l.erfpacht]);
    if (l.acceptance) finItems.push(['Acceptance', l.acceptance]);
    if (finItems.length > 0) {{
        finHtml = `<div class="modal-section"><h4>Financial</h4>` +
            finItems.map(([k, v]) => `<div class="modal-row"><span>${{k}}</span><span class="val" style="font-size:12px;max-width:200px;text-align:right">${{v}}</span></div>`).join('') +
            `</div>`;
    }}

    // Features
    let featHtml = '';
    const featItems = [];
    if (l.amenities) featItems.push(['Amenities', l.amenities]);
    if (l.insulation) featItems.push(['Insulation', l.insulation]);
    if (l.heating) featItems.push(['Heating', l.heating]);
    if (l.location_type) featItems.push(['Location', l.location_type]);
    if (l.bathroom_features) featItems.push(['Bathroom', l.bathroom_features]);
    if (featItems.length > 0) {{
        featHtml = `<div class="modal-section"><h4>Features</h4>` +
            featItems.map(([k, v]) => `<div class="modal-row"><span>${{k}}</span><span class="val" style="font-size:12px;max-width:200px;text-align:right">${{v}}</span></div>`).join('') +
            `</div>`;
    }}

    content.innerHTML = `
        <button class="modal-close" onclick="closeModal()">&times;</button>
        ${{galleryHtml}}
        <div class="modal-body">
            <div class="modal-price">&euro;${{l.price_numeric.toLocaleString()}}${{drop ? ` <span style="font-size:14px;color:var(--red);text-decoration:line-through">&euro;${{l.previous_price.toLocaleString()}} (-${{dropPct}}%)</span>` : ''}}</div>
            <div class="modal-address">${{l.address || 'Unknown'}}</div>
            <div class="modal-sub">${{l.neighbourhood || ''}}${{l.postcode ? ' &middot; ' + l.postcode : ''}}${{l.city ? ' &middot; ' + l.city : ''}}</div>

            ${{predHtml}}

            <div class="prop-grid">
                <div class="det"><div class="det-label">Area</div><div class="det-value">${{l.living_area || '--'}} m&sup2;</div></div>
                <div class="det"><div class="det-label">Bedrooms</div><div class="det-value">${{l.bedrooms ?? '--'}}</div></div>
                <div class="det"><div class="det-label">Rooms</div><div class="det-value">${{l.num_rooms ?? '--'}}</div></div>
                <div class="det"><div class="det-label">Bathrooms</div><div class="det-value">${{l.num_bathrooms ?? '--'}}</div></div>
                <div class="det"><div class="det-label">Floors</div><div class="det-value">${{l.num_floors ?? '--'}}</div></div>
                <div class="det"><div class="det-label">Floor</div><div class="det-value">${{l.floor_level || '--'}}</div></div>
                <div class="det"><div class="det-label">Year Built</div><div class="det-value">${{l.year_built || '--'}}</div></div>
                <div class="det"><div class="det-label">Type</div><div class="det-value">${{l.object_type || '--'}}</div></div>
                <div class="det"><div class="det-label">Energy</div><div class="det-value el-${{elBase}}">${{l.energy_label || '--'}}</div></div>
                <div class="det"><div class="det-label">EUR/m&sup2;</div><div class="det-value">${{l.price_m2 ? '&euro;' + Math.round(l.price_m2).toLocaleString() : '--'}}</div></div>
                <div class="det"><div class="det-label">Outdoor</div><div class="det-value">${{l.outdoor_area_m2 ? l.outdoor_area_m2 + ' m&sup2;' : '--'}}</div></div>
                <div class="det"><div class="det-label">Volume</div><div class="det-value">${{l.volume_m3 ? l.volume_m3 + ' m&sup3;' : '--'}}</div></div>
                <div class="det"><div class="det-label">Balcony</div><div class="det-value">${{l.has_balcony ? (l.balcony_type || 'Yes') : '--'}}</div></div>
                <div class="det"><div class="det-label">Parking</div><div class="det-value">${{l.parking_type || '--'}}</div></div>
                <div class="det"><div class="det-label">Construction</div><div class="det-value">${{l.construction_type || '--'}}</div></div>
                <div class="det"><div class="det-label">Plot</div><div class="det-value">${{l.plot_area ? l.plot_area + ' m&sup2;' : '--'}}</div></div>
            </div>

            ${{scoreHtml}}
            ${{historyHtml}}
            ${{descHtml}}
            ${{finHtml}}
            ${{featHtml}}

            <div class="modal-actions">
                <a href="${{l.detail_url}}" target="_blank" rel="noopener" class="btn">View Listing &rarr;</a>
                <button class="btn btn-ghost" onclick="toggleFav(null,${{l.global_id}}); openModal(${{l.global_id}});">
                    ${{isFaved ? '&#9829; Saved' : '&#9825; Save'}}
                </button>
            </div>
        </div>`;

    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';

    // Init gallery swipe
    if (photos.length > 1) initGallerySwipe();
}}

function closeModal() {{
    document.getElementById('modalOverlay').classList.remove('open');
    document.body.style.overflow = '';
    // Close map sheet too
    document.getElementById('mapSheet').classList.remove('open');
}}

// ── Gallery swipe ──
function initGallerySwipe() {{
    const gallery = document.getElementById('gallery');
    if (!gallery) return;
    const track = document.getElementById('galleryTrack');
    const maxIdx = parseInt(gallery.dataset.max) - 1;
    let startX = 0, currentX = 0, isDragging = false;

    function goTo(idx) {{
        idx = Math.max(0, Math.min(idx, maxIdx));
        gallery.dataset.idx = idx;
        track.style.transform = `translateX(-${{idx * 100}}%)`;
        document.getElementById('galIdx').textContent = idx + 1;
        document.querySelectorAll('#galleryDots .gallery-dot').forEach((d, i) => d.classList.toggle('active', i === idx));
    }}

    gallery.addEventListener('touchstart', e => {{
        startX = e.touches[0].clientX; isDragging = true;
        track.style.transition = 'none';
    }}, {{ passive: true }});
    gallery.addEventListener('touchmove', e => {{
        if (!isDragging) return;
        currentX = e.touches[0].clientX;
        const diff = currentX - startX;
        const idx = parseInt(gallery.dataset.idx);
        track.style.transform = `translateX(calc(-${{idx * 100}}% + ${{diff}}px))`;
    }}, {{ passive: true }});
    gallery.addEventListener('touchend', () => {{
        isDragging = false;
        track.style.transition = 'transform 0.3s ease';
        const diff = currentX - startX;
        const idx = parseInt(gallery.dataset.idx);
        if (Math.abs(diff) > 50) {{
            goTo(diff > 0 ? idx - 1 : idx + 1);
        }} else {{
            goTo(idx);
        }}
    }});
    // Click dots
    document.querySelectorAll('#galleryDots .gallery-dot').forEach(dot => {{
        dot.addEventListener('click', () => goTo(parseInt(dot.dataset.i)));
    }});
}}

// ── Event listeners ──
function setupListeners() {{
    // Search with debounce
    let searchTimeout;
    document.getElementById('searchInput').addEventListener('input', () => {{
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(applyFilters, 250);
    }});
    // Escape closes modal
    document.addEventListener('keydown', e => {{ if (e.key === 'Escape') closeModal(); }});
    // Infinite scroll
    const observer = new IntersectionObserver(entries => {{
        if (entries[0].isIntersecting && showing < filtered.length) loadMore();
    }}, {{ rootMargin: '400px' }});
    observer.observe(document.getElementById('loadMore'));
    // Close map sheet on tap outside
    document.getElementById('map')?.addEventListener('click', () => {{
        document.getElementById('mapSheet').classList.remove('open');
    }});
}}

// ── Bootstrap ──
document.addEventListener('DOMContentLoaded', loadData);
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="Generate Ground Control dashboard")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--output-dir", default=str(PUBLIC_DIR))
    parser.add_argument("--open", action="store_true", help="Open in browser after generating")
    args = parser.parse_args()

    db = args.db
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Score all listings
    scored = score_listings(db)

    # Supplementary data
    price_hist = get_price_history(db)
    stats = get_stats(db)
    hood_stats = get_neighbourhood_stats(db)
    stats["new_today"] = count_new_today(db)

    # Load neighbourhood coordinates and build map data
    coords = load_coords(COORDS_PATH)
    map_data = build_map_data(hood_stats, coords)

    # Merge price history into scored listings
    for listing in scored:
        listing["price_history"] = price_hist.get(listing["global_id"], [])

    # Assign per-listing coordinates from postcode
    assign_coords(scored)

    # Serialize
    generated_at = datetime.now(timezone.utc).isoformat()

    # Write listings.json
    data_payload = {
        "listings": scored,
        "stats": stats,
        "neighbourhood_stats": hood_stats,
        "map_data": map_data,
        "generated_at": generated_at,
    }
    json_path = output_dir / "listings.json"
    json_str = json.dumps(data_payload, default=str)
    json_path.write_text(json_str, encoding="utf-8")

    # Write index.html
    html = build_html(generated_at)
    html_path = output_dir / "index.html"
    html_path.write_text(html, encoding="utf-8")

    print(f"Dashboard: {html_path} ({len(html):,} bytes)")
    print(f"Data:      {json_path} ({len(json_str):,} bytes, {len(scored)} listings)")

    if args.open:
        # Serve via simple HTTP server for fetch() to work
        import http.server
        import threading
        import functools

        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(output_dir))
        server = http.server.HTTPServer(("localhost", 8080), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        webbrowser.open("http://localhost:8080")
        print("Serving at http://localhost:8080 — press Ctrl+C to stop")
        try:
            thread.join()
        except KeyboardInterrupt:
            server.shutdown()


if __name__ == "__main__":
    main()
