#!/usr/bin/env python3
"""
Generate a simple Leaflet map of listings by postcode area.
"""
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "ground_control.db"
OUTPUT_PATH = Path(__file__).parent / "listings_map.html"

# Approximate Amsterdam postcode area centers (4-digit prefix -> lat/lon)
# These are rough centroids for Amsterdam postcode areas
POSTCODE_COORDS = {
    "1011": (52.3676, 4.9000),  # Centrum
    "1012": (52.3720, 4.8940),  # Centrum
    "1013": (52.3780, 4.8900),  # Westermarkt
    "1014": (52.3860, 4.8850),  # Westerpark
    "1015": (52.3580, 4.8800),  # Jordaan
    "1016": (52.3650, 4.8960),  # Grachtengordel
    "1017": (52.3600, 4.9020),  # Leidseplein
    "1018": (52.3540, 4.9120),  # Plantage
    "1019": (52.3620, 4.9200),  # Oost
    "1021": (52.3840, 4.9150),  # Noord
    "1022": (52.3900, 4.9100),  # Noord
    "1023": (52.3950, 4.9050),  # Noord
    "1024": (52.4000, 4.9200),  # Noord
    "1025": (52.4050, 4.9100),  # NDSM
    "1026": (52.4150, 4.9050),  # Landelijk Noord
    "1027": (52.4100, 4.9300),  # Waterland
    "1028": (52.4200, 4.9250),  # Zunderdorp
    "1031": (52.3800, 4.9050),  # Oud-West
    "1032": (52.3850, 4.9100),  # Westerdorp
    "1033": (52.3900, 4.8950),  # Houthavens
    "1034": (52.4000, 4.9050),  # Tuindorp Oostzaan
    "1035": (52.4080, 4.9000),  # Oostzaan
    "1041": (52.3550, 4.8700),  # Bos en Lommer
    "1042": (52.3600, 4.8650),  # Kolenkit
    "1043": (52.3650, 4.8600),  # Geuzenveld
    "1044": (52.3700, 4.8500),  # Slotermeer
    "1045": (52.3750, 4.8450),  # Puntepel
    "1046": (52.3800, 4.8400),  # Lutkemeer
    "1047": (52.3850, 4.8350),  # Schipluiden
    "1051": (52.3450, 4.8850),  # Overtoomse Veld
    "1052": (52.3420, 4.8900),  # Helmers
    "1053": (52.3400, 4.8950),  # Da Costabuurt
    "1054": (52.3380, 4.9000),  # Apollobuurt
    "1055": (52.3350, 4.8850),  # Bellamy
    "1056": (52.3300, 4.8900),  # Ten Katestraat
    "1057": (52.3250, 4.8950),  # Kinkerbuurt
    "1058": (52.3200, 4.9000),  # Hoofddorpplein
    "1059": (52.3150, 4.9050),  # Schinkelbuurt
    "1061": (52.3100, 4.8800),  # Osdorp
    "1062": (52.3050, 4.8750),  # Sloten
    "1063": (52.3000, 4.8900),  # Geuzenbuurt
    "1064": (52.2950, 4.8950),  # Hoofddorp
    "1065": (52.2900, 4.9000),  # Schiphol
    "1066": (52.2850, 4.9050),  # Nieuwebrug
    "1067": (52.2800, 4.9100),  # Rijk
    "1068": (52.2750, 4.9150),  # Langen
    "1069": (52.2700, 4.9200),  # Lutkemeer
    "1071": (52.3500, 4.9050),  # Museumkwartier
    "1072": (52.3450, 4.9100),  # De Pijp
    "1073": (52.3400, 4.9150),  # Weerdjes
    "1074": (52.3350, 4.9200),  # Rivierenbuurt
    "1075": (52.3300, 4.9250),  # Hoeken
    "1076": (52.3250, 4.9300),  # Scheldebuurt
    "1077": (52.3200, 4.9350),  # IJburg
    "1078": (52.3150, 4.9400),  # IJburg
    "1079": (52.3100, 4.9450),  # Ommoord
    "1081": (52.3050, 4.9500),  # Buitenveldert
    "1082": (52.3000, 4.9550),  # Zuidas
    "1083": (52.2950, 4.9600),  # Hoofddorp
    "1086": (52.2900, 4.9700),  # Diemen
    "1087": (52.2850, 4.9750),  # Dvm
    "1088": (52.2800, 4.9800),  # Verspreide
    "1089": (52.2750, 4.9850),  # Nieuwegeen
    "1091": (52.2950, 4.9350),  # Oost
    "1092": (52.2900, 4.9400),  # Oud Oost
    "1093": (52.2850, 4.9450),  # Dapperbuurt
    "1094": (52.2800, 4.9500),  # Oost Indische Buurt
    "1095": (52.2750, 4.9550),  # Indische Buurt
    "1096": (52.2700, 4.9600),  # Amsterdam Zuidoost
    "1097": (52.2650, 4.9650),  # Diemen
    "1098": (52.2600, 4.9700),  # Science Park
    "1099": (52.2550, 4.9750),  # Muiden
    "1101": (52.3100, 4.9550),  # Bijlmer
    "1102": (52.3050, 4.9600),  # Bijlmer
    "1103": (52.3000, 4.9650),  # Bijlmer
    "1104": (52.2950, 4.9700),  # Bijlmer
    "1105": (52.2900, 4.9750),  # Diemen
    "1106": (52.2850, 4.9800),  # Diemen
    "1107": (52.2800, 4.9850),  # Diemen
    "1108": (52.2750, 4.9900),  # Diemen
    "1109": (52.2700, 4.9950),  # Muiden
}


def get_listings(db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT global_id, postcode, price_numeric, living_area, bedrooms, 
               detail_url, has_balcony, energy_label
        FROM listings 
        WHERE is_active = 1 AND postcode != ''
        ORDER BY first_seen DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def generate_map(listings: list[dict]) -> str:
    """Generate Leaflet map HTML."""
    markers = []
    for l in listings:
        pc = l.get("postcode", "")
        if not pc:
            continue
        
        # Get 4-digit prefix
        prefix = pc.replace(" ", "")[:4]
        
        # Try exact match first, then first 3 digits
        coords = POSTCODE_COORDS.get(prefix)
        if not coords and len(prefix) >= 3:
            # Try first 3 digits
            for k, v in POSTCODE_COORDS.items():
                if k.startswith(prefix[:3]):
                    coords = v
                    break
        
        if not coords:
            continue
        
        # Add small random offset to spread markers
        import random
        lat = coords[0] + random.uniform(-0.003, 0.003)
        lon = coords[1] + random.uniform(-0.003, 0.003)
        
        price = f"€{l['price_numeric']:,.0f}" if l.get('price_numeric') else "?"
        area = f"{l.get('living_area', '?')}m²" if l.get('living_area') else ""
        beds = f"{l.get('bedrooms', '?')}bd" if l.get('bedrooms') else ""
        
        popup = f"""
        <b>{price}</b><br>
        {area} {beds}<br>
        <a href="{l.get('detail_url', '')}" target="_blank">View →</a>
        """
        
        # Color by price
        if l.get('price_numeric') and l['price_numeric'] < 400000:
            color = "green"
        elif l.get('price_numeric') and l['price_numeric'] < 600000:
            color = "orange"
        else:
            color = "red"
        
        markers.append(f"""L.marker([{lat}, {lon}]).bindPopup("{popup}").addTo(map);""")
    
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Ground Control - Listings Map</title>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body {{ margin: 0; padding: 0; }}
        #map {{ position: absolute; top: 0; bottom: 0; width: 100%; }}
        .info {{
            position: absolute;
            top: 10px;
            right: 10px;
            background: white;
            padding: 15px;
            z-index: 1000;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
        }}
    </style>
</head>
<body>
    <div class="info">
        <h3>🏠 Ground Control</h3>
        <p><b>{len(listings)}</b> listings</p>
        <p style="color:green">● &lt;€400k</p>
        <p style="color:orange">● €400-600k</p>
        <p style="color:red">● &gt;€600k</p>
    </div>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([52.3500, 4.9200], 12);
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            attribution: '© OpenStreetMap'
        }}).addTo(map);
        
        {chr(10).join(markers)}
    </script>
</body>
</html>"""
    return html


def main():
    listings = get_listings(DB_PATH)
    print(f"Got {len(listings)} listings with postcodes")
    
    html = generate_map(listings)
    OUTPUT_PATH.write_text(html)
    print(f"Map saved to: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
