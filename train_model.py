#!/usr/bin/env python3
"""Train separate apartment + house price models and write predictions to DB."""
import argparse
import json
import re
import pandas as pd
import numpy as np
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from sklearn.model_selection import KFold, RandomizedSearchCV
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score, mean_squared_error
from sklearn.preprocessing import OrdinalEncoder
import joblib
import warnings
warnings.filterwarnings('ignore')

HISTORY_PATH = Path(__file__).parent / 'model_history.jsonl'

DB_PATH = 'ground_control.db'

MODEL_PARAMS = dict(
    max_iter=500, max_depth=8, learning_rate=0.05,
    min_samples_leaf=10, l2_regularization=0.5, random_state=42
)

# ── helpers ──────────────────────────────────────────────────────────────

def parse_floor_num(s):
    """'3e woonlaag' → 3, 'Begane grond' → 0"""
    if pd.isna(s):
        return np.nan
    s = s.lower().strip()
    if 'begane' in s:
        return 0
    m = re.search(r'(\d+)', s)
    return int(m.group(1)) if m else np.nan


def parse_vve_amount(s):
    """Extract €amount from messy VvE text, cap at 5000."""
    if pd.isna(s):
        return np.nan
    # Match € followed by digits with optional . and , separators
    m = re.search(r'€\s*([\d]+(?:[.,]\d+)*)', s)
    if not m:
        return np.nan
    raw = m.group(1).rstrip('.,')
    if not raw:
        return np.nan
    try:
        if ',' in raw:
            val = float(raw.replace('.', '').replace(',', '.'))
        elif raw.count('.') == 1 and len(raw.split('.')[-1]) <= 2:
            val = float(raw)
        else:
            val = float(raw.replace('.', ''))
    except ValueError:
        return np.nan
    return min(val, 5000)


def parse_erfpacht_flag(s):
    """1 if erfpacht exists and isn't 'afgekocht', else 0."""
    if pd.isna(s):
        return 0
    s_lower = s.lower()
    if 'afgekocht' in s_lower or 'eigen grond' in s_lower:
        return 0
    return 1


def contains(text, keyword):
    """Case-insensitive substring check, NaN-safe."""
    if pd.isna(text):
        return 0
    return int(keyword.lower() in text.lower())


def _haversine(lat1, lon1, lat2, lon2):
    """Haversine distance in km between two points."""
    R = 6371
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = np.sin(dlat / 2) ** 2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2
    return R * 2 * np.arcsin(np.sqrt(a))


def build_features(df):
    """Add all shared parsed features to df in-place."""
    # ── spatial (from neighbourhood_coords.json) ──
    coords_path = Path(__file__).parent / 'neighbourhood_coords.json'
    with open(coords_path) as f:
        coords = json.load(f)
    coord_df = pd.DataFrame(
        {k: {'lat': v[0], 'lon': v[1]} for k, v in coords.items()}
    ).T
    coord_df.index.name = 'neighbourhood'
    coord_df = coord_df.reset_index()
    coord_df['lat'] = pd.to_numeric(coord_df['lat'])
    coord_df['lon'] = pd.to_numeric(coord_df['lon'])

    df = df.merge(coord_df, on='neighbourhood', how='left')
    # Amsterdam Centraal
    df['distance_to_center'] = _haversine(df['lat'], df['lon'], 52.3791, 4.9003)
    # Zuidas business district
    df['distance_to_zuidas'] = _haversine(df['lat'], df['lon'], 52.3380, 4.8737)

    # ── structural ──
    df['building_age'] = 2026 - pd.to_numeric(df['year_built'], errors='coerce')

    energy_map = {'A++++': 12, 'A+++': 11, 'A++': 10, 'A+': 9, 'A': 8,
                  'B': 7, 'C': 6, 'D': 5, 'E': 4, 'F': 3, 'G': 2}
    df['energy_score'] = df['energy_label'].map(energy_map)

    # ── derived / interaction ──
    df['area_per_room'] = df['living_area'] / df['num_rooms'].replace(0, np.nan)
    df['price_per_m2_proxy'] = np.where(
        (df['living_area'] > 0) & (df['volume_m3'] > 0),
        df['living_area'] / df['volume_m3'],
        np.nan
    )
    df['size_x_age'] = df['living_area'] * df['building_age']
    df['size_x_energy'] = df['living_area'] * df['energy_score']
    df['rooms_per_m2'] = df['num_rooms'] / df['living_area'].replace(0, np.nan)

    # ── location_type flags ──
    lt = df['location_type'].fillna('')
    df['loc_centrum'] = lt.str.contains('centrum', case=False).astype(int)
    df['loc_water'] = lt.str.contains('water', case=False).astype(int)
    df['loc_vrij_uitzicht'] = lt.str.contains('vrij uitzicht', case=False).astype(int)
    df['loc_woonwijk'] = lt.str.contains('woonwijk', case=False).astype(int)
    df['loc_drukke_weg'] = lt.str.contains('drukke weg', case=False).astype(int)
    df['loc_rustige_weg'] = lt.str.contains('rustige weg', case=False).astype(int)
    df['loc_park'] = lt.str.contains('park', case=False).astype(int)

    # ── amenities flags ──
    am = df['amenities'].fillna('')
    df['has_alarminstallatie'] = am.str.contains('alarm', case=False).astype(int)
    df['has_airconditioning'] = am.str.contains('airco', case=False).astype(int)
    df['has_lift'] = am.str.contains('lift', case=False).astype(int)
    df['has_mechanische_ventilatie'] = am.str.contains('mechanische ventilatie', case=False).astype(int)
    df['has_zonnepanelen'] = am.str.contains('zonnepanelen', case=False).astype(int)

    # ── heating flags ──
    ht = df['heating'].fillna('')
    df['has_vloerverwarming'] = ht.str.contains('vloerverwarming', case=False).astype(int)
    df['has_warmtepomp'] = ht.str.contains('warmtepomp', case=False).astype(int)
    df['has_blokverwarming'] = ht.str.contains('blokverwarming', case=False).astype(int)
    df['has_stadsverwarming'] = ht.str.contains('stadsverwarming', case=False).astype(int)

    # ── parking flags ──
    pt = df['parking_type'].fillna('')
    df['has_eigen_terrein'] = pt.str.contains('eigen terrein', case=False).astype(int)
    df['has_parkeergarage'] = pt.str.contains('parkeergarage', case=False).astype(int)

    # ── insulation flags ──
    ins = df['insulation'].fillna('')
    df['is_volledig_geisoleerd'] = ins.str.contains('volledig', case=False).astype(int)
    df['has_dubbel_glas'] = ins.str.contains('dubbel glas', case=False).astype(int)

    # ── description text features ──
    desc = df['description'].fillna('').str.lower()
    df['desc_renovated'] = desc.str.contains('gerenoveerd|verbouwd|vernieuwd|gemoderniseerd', regex=True).astype(int)
    df['desc_luxury'] = desc.str.contains('luxe|luxueus|high-end|premium', regex=True).astype(int)
    df['desc_garden'] = desc.str.contains('tuin|garden', regex=True).astype(int)
    df['desc_monument'] = desc.str.contains('monument|rijksmonument', regex=True).astype(int)
    df['desc_new_build'] = desc.str.contains('nieuwbouw|new build|oplevering', regex=True).astype(int)
    df['desc_length'] = desc.str.len()

    # ── postcode (ordinal-encoded) ──
    df['pc4_code'] = pd.to_numeric(df['postcode'].str[:4], errors='coerce')

    # ── tenure ──
    df['is_erfpacht'] = df['erfpacht'].apply(parse_erfpacht_flag)

    return df


SHARED_FEATURES = [
    # structural
    'living_area', 'volume_m3', 'num_rooms', 'bedrooms', 'num_bathrooms',
    'building_age', 'outdoor_area_m2', 'energy_score',
    # derived / interaction
    'area_per_room', 'price_per_m2_proxy',
    'size_x_age', 'size_x_energy', 'rooms_per_m2',
    # spatial
    'lat', 'lon', 'distance_to_center', 'distance_to_zuidas',
    # location flags
    'loc_centrum', 'loc_water', 'loc_vrij_uitzicht', 'loc_woonwijk',
    'loc_drukke_weg', 'loc_rustige_weg', 'loc_park',
    # amenity flags
    'has_alarminstallatie', 'has_airconditioning', 'has_lift',
    'has_mechanische_ventilatie', 'has_zonnepanelen',
    # heating flags
    'has_vloerverwarming', 'has_warmtepomp', 'has_blokverwarming', 'has_stadsverwarming',
    # parking flags
    'has_eigen_terrein', 'has_parkeergarage',
    # insulation flags
    'is_volledig_geisoleerd', 'has_dubbel_glas',
    # description text
    'desc_renovated', 'desc_luxury', 'desc_garden', 'desc_monument',
    'desc_new_build', 'desc_length',
    # location
    'pc4_code',
    # tenure
    'is_erfpacht',
]

APT_EXTRA_FEATURES = ['floor_num', 'vve_amount', 'has_balcony', 'balcony_ordinal']
HOUSE_EXTRA_FEATURES = ['num_floors']


def compute_feature_importances(model):
    """Compute split-based feature importances from HistGBR's internal tree structure.

    sklearn's HistGBR doesn't expose feature_importances_ directly,
    so we walk the _predictors tree nodes and sum gain * count per feature.
    """
    importances = np.zeros(model.n_features_in_)

    for predictors_for_iter in model._predictors:
        for predictor in predictors_for_iter:
            nodes = predictor.nodes
            for node in nodes:
                feature_idx = node['feature_idx']
                if feature_idx >= 0:  # internal node (not leaf)
                    importances[feature_idx] += node['gain'] * node['count']

    total = importances.sum()
    if total > 0:
        importances /= total
    return importances.tolist()


def evaluate_and_train(X, y, label):
    """Run 5-fold CV with rich metrics, train final model, return (model, cv_predictions, metrics)."""
    kf = KFold(n_splits=5, shuffle=True, random_state=42)
    X_arr = X.values if hasattr(X, 'values') else X
    y_arr = y.values if hasattr(y, 'values') else y

    # ── Per-fold metrics + collect OOF predictions ──
    cv_pred_log = np.empty_like(y_arr)
    fold_metrics = []

    for fold_i, (train_idx, val_idx) in enumerate(kf.split(X_arr), 1):
        fold_model = HistGradientBoostingRegressor(**MODEL_PARAMS)
        fold_model.fit(X_arr[train_idx], y_arr[train_idx])
        pred_log = fold_model.predict(X_arr[val_idx])
        cv_pred_log[val_idx] = pred_log

        pred_euros = np.exp(pred_log)
        actual_euros = np.exp(y_arr[val_idx])
        fold_metrics.append({
            'fold': fold_i,
            'r2': round(float(r2_score(y_arr[val_idx], pred_log)), 4),
            'mae': round(float(mean_absolute_error(actual_euros, pred_euros)), 0),
            'mdape': round(float(np.median(np.abs(actual_euros - pred_euros) / actual_euros) * 100), 2),
        })

    # ── Aggregate CV metrics ──
    cv_pred_euros = np.exp(cv_pred_log)
    y_euros = np.exp(y_arr)
    abs_pct_error = np.abs(y_euros - cv_pred_euros) / y_euros * 100

    r2_log = r2_score(y_arr, cv_pred_log)
    mae = mean_absolute_error(y_euros, cv_pred_euros)
    rmse = float(np.sqrt(mean_squared_error(y_euros, cv_pred_euros)))
    mdape = float(np.median(abs_pct_error))
    mape = float(np.mean(abs_pct_error))

    # Accuracy bands
    accuracy_bands = {
        str(t): round(float(np.mean(abs_pct_error <= t) * 100), 1)
        for t in [5, 10, 15, 20]
    }

    # Error percentiles
    error_percentiles = {
        f'p{p}': round(float(np.percentile(abs_pct_error, p)), 2)
        for p in [10, 25, 50, 75, 90]
    }

    # Error by price band
    price_bands = [
        ('200-300k', 200_000, 300_000),
        ('300-500k', 300_000, 500_000),
        ('500-750k', 500_000, 750_000),
        ('750k-1M', 750_000, 1_000_001),
    ]
    error_by_price_band = []
    for band_label, lo, hi in price_bands:
        mask = (y_euros >= lo) & (y_euros < hi)
        if mask.sum() >= 3:
            band_errors = abs_pct_error[mask]
            error_by_price_band.append({
                'band': band_label,
                'count': int(mask.sum()),
                'median_error': round(float(np.median(band_errors)), 2),
                'p90_error': round(float(np.percentile(band_errors, 90)), 2),
            })

    # Residual vs predicted (sampled for scatter plot)
    residual_pct = (y_euros - cv_pred_euros) / cv_pred_euros * 100
    n_sample = min(2000, len(cv_pred_euros))
    rng = np.random.RandomState(42)
    sample_idx = rng.choice(len(cv_pred_euros), n_sample, replace=False)
    residual_vs_predicted = {
        'predicted': [round(float(v)) for v in cv_pred_euros[sample_idx]],
        'residual_pct': [round(float(v), 2) for v in residual_pct[sample_idx]],
    }

    print(f'\n{"="*50}')
    print(f'{label} model  (n={len(y_arr)})')
    print(f'{"="*50}')
    print(f'  CV R² (log-price): {r2_log:.3f}')
    print(f'  CV MAE:            €{mae:,.0f}')
    print(f'  CV RMSE:           €{rmse:,.0f}')
    print(f'  CV MdAPE:          {mdape:.1f}%')
    print(f'  CV MAPE:           {mape:.1f}%')
    print(f'  Within 10%:        {accuracy_bands["10"]}%')
    print(f'  Within 20%:        {accuracy_bands["20"]}%')

    # Train final model on all data
    model = HistGradientBoostingRegressor(**MODEL_PARAMS)
    model.fit(X_arr, y_arr)

    metrics = {
        'r2': r2_log, 'mae': mae, 'rmse': rmse,
        'mdape': mdape, 'mape': mape,
        'accuracy_bands': accuracy_bands,
        'error_percentiles': error_percentiles,
        'fold_metrics': fold_metrics,
        'error_by_price_band': error_by_price_band,
        'residual_vs_predicted': residual_vs_predicted,
    }

    return model, cv_pred_log, metrics


def tune_hyperparams(X, y, label):
    """Run randomized search to find better hyperparams."""
    param_dist = {
        'max_iter': [300, 500, 800],
        'max_depth': [6, 8, 10, 12],
        'learning_rate': [0.03, 0.05, 0.08, 0.1],
        'min_samples_leaf': [5, 10, 20, 30],
        'l2_regularization': [0.1, 0.5, 1.0, 2.0],
        'max_bins': [128, 255],
    }
    base = HistGradientBoostingRegressor(random_state=42)
    search = RandomizedSearchCV(
        base, param_dist, n_iter=50, cv=5,
        scoring='neg_mean_absolute_error',
        random_state=42, n_jobs=-1, verbose=1
    )
    print(f'\n  Tuning {label} ({50} iterations, 5-fold CV)...')
    search.fit(X, y)
    print(f'  Best score: {search.best_score_:.4f}')
    print(f'  Best params: {search.best_params_}')
    return search.best_params_


# ── main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--tune', action='store_true', help='Run hyperparameter search')
    args = parser.parse_args()

    print('Loading data...')
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query('SELECT * FROM listings', conn)
    print(f'Loaded {len(df)} listings')

    # ── filter non-residential + tighten price band ──
    df = df[~df['detail_url'].str.contains('parkeergelegenheid', na=False)]
    df = df[df['price_numeric'].notna() & (df['price_numeric'] >= 200_000) & (df['price_numeric'] <= 1_000_000)]
    df = df[df['living_area'].notna() & (df['living_area'] > 0)]

    # ── classify property type from URL ──
    df['property_type'] = df['detail_url'].str.extract(r'/detail/koop/[^/]+/(\w+)-')[0]
    df = df[df['property_type'].isin(['appartement', 'huis'])]
    print(f'After filtering: {len(df)} ({(df.property_type=="appartement").sum()} apt, {(df.property_type=="huis").sum()} house)')

    # ── log target ──
    df['log_price'] = np.log(df['price_numeric'])

    # ── build shared features ──
    df = build_features(df)

    # ── apartment-specific features ──
    df['floor_num'] = df['floor_level'].apply(parse_floor_num)
    df['vve_amount'] = df['vve_contribution'].apply(parse_vve_amount)
    df['balcony_ordinal'] = 0
    df.loc[df['balcony_type'] == 'balcony', 'balcony_ordinal'] = 1
    df.loc[df['balcony_type'] == 'rooftop', 'balcony_ordinal'] = 2
    # both balcony + rooftop
    both_mask = df['balcony_type'].fillna('').str.contains('balcony', case=False) & \
                df['balcony_type'].fillna('').str.contains('rooftop', case=False)
    df.loc[both_mask, 'balcony_ordinal'] = 3

    # ── split ──
    apt_df = df[df['property_type'] == 'appartement'].copy()
    house_df = df[df['property_type'] == 'huis'].copy()

    apt_features = SHARED_FEATURES + APT_EXTRA_FEATURES
    house_features = SHARED_FEATURES + HOUSE_EXTRA_FEATURES

    X_apt = apt_df[apt_features]
    y_apt = apt_df['log_price']
    X_house = house_df[house_features]
    y_house = house_df['log_price']

    # ── optional hyperparameter tuning ──
    global MODEL_PARAMS
    if args.tune:
        print('\n' + '=' * 50)
        print('HYPERPARAMETER TUNING')
        print('=' * 50)
        best_apt = tune_hyperparams(X_apt.values, y_apt.values, 'Apartment')
        best_house = tune_hyperparams(X_house.values, y_house.values, 'House')
        # Use apartment params as unified (larger dataset)
        MODEL_PARAMS = {**best_apt, 'random_state': 42}
        print(f'\nUsing tuned params: {MODEL_PARAMS}')

    # ── train both models ──
    apt_model, apt_cv_pred, apt_metrics = evaluate_and_train(X_apt, y_apt, 'Apartment')
    house_model, house_cv_pred, house_metrics = evaluate_and_train(X_house, y_house, 'House')

    # ── compute feature importances from final models ──
    apt_importances = compute_feature_importances(apt_model)
    house_importances = compute_feature_importances(house_model)

    trained_at = datetime.now(timezone.utc).isoformat()

    # ── save models ──
    apt_pkl = {
        'model': apt_model,
        'features': apt_features,
        'target': 'log_price',
        'metrics': apt_metrics,
        'hyperparams': MODEL_PARAMS,
        'trained_at': trained_at,
        'n_samples': len(y_apt),
        'cv_folds': 5,
        'feature_importances': apt_importances,
    }
    house_pkl = {
        'model': house_model,
        'features': house_features,
        'target': 'log_price',
        'metrics': house_metrics,
        'hyperparams': MODEL_PARAMS,
        'trained_at': trained_at,
        'n_samples': len(y_house),
        'cv_folds': 5,
        'feature_importances': house_importances,
    }
    joblib.dump(apt_pkl, 'apartment_model.pkl')
    joblib.dump(house_pkl, 'house_model.pkl')
    print('\nModels saved: apartment_model.pkl, house_model.pkl')

    # ── append to model history ──
    history_entry = {
        'trained_at': trained_at,
        'hyperparams': MODEL_PARAMS,
        'apartment': {
            'n_samples': len(y_apt),
            'features': apt_features,
            'feature_importances': apt_importances,
            'metrics': {k: v for k, v in apt_metrics.items()
                        if k != 'residual_vs_predicted'},
        },
        'house': {
            'n_samples': len(y_house),
            'features': house_features,
            'feature_importances': house_importances,
            'metrics': {k: v for k, v in house_metrics.items()
                        if k != 'residual_vs_predicted'},
        },
    }
    with open(HISTORY_PATH, 'a') as f:
        f.write(json.dumps(history_entry, default=str) + '\n')
    print(f'Appended to model history: {HISTORY_PATH}')

    # ── write predictions to DB ──
    # Use CV out-of-fold predictions for residuals (no data leakage)
    apt_df = apt_df.copy()
    apt_df['predicted_price'] = np.exp(apt_cv_pred)
    apt_df['residual'] = apt_df['price_numeric'] - apt_df['predicted_price']

    house_df = house_df.copy()
    house_df['predicted_price'] = np.exp(house_cv_pred)
    house_df['residual'] = house_df['price_numeric'] - house_df['predicted_price']

    all_pred = pd.concat([
        apt_df[['global_id', 'predicted_price', 'residual']],
        house_df[['global_id', 'predicted_price', 'residual']],
    ])

    cursor = conn.cursor()
    # Ensure columns exist
    for col in ['predicted_price', 'residual']:
        try:
            cursor.execute(f"ALTER TABLE listings ADD COLUMN {col} REAL")
        except sqlite3.OperationalError:
            pass

    # Reset all predictions first (parking spots etc. should have NULL)
    cursor.execute("UPDATE listings SET predicted_price = NULL, residual = NULL")

    for _, row in all_pred.iterrows():
        cursor.execute(
            "UPDATE listings SET predicted_price = ?, residual = ? WHERE global_id = ?",
            (row['predicted_price'], row['residual'], row['global_id'])
        )

    conn.commit()
    print(f'Updated {len(all_pred)} listings with predictions')

    # ── top 20 undervalued apartments ──
    apt_df['residual_pct'] = (apt_df['residual'] / apt_df['predicted_price']) * 100
    undervalued = apt_df.nsmallest(20, 'residual_pct')

    print(f'\n{"="*80}')
    print('TOP 20 UNDERVALUED APARTMENTS (largest negative residual %)')
    print(f'{"="*80}')
    print(f'{"Address":40s} {"Price":>12s} {"Predicted":>12s} {"Diff%":>7s} {"Area":>6s}')
    print('-' * 80)
    for _, r in undervalued.iterrows():
        if isinstance(r['address'], str) and r['address'].strip():
            addr = r['address'][:38]
        else:
            # Fall back to URL slug
            slug = re.search(r'/([^/]+)/\d+/?$', str(r.get('detail_url', '')))
            addr = slug.group(1)[:38] if slug else '?'
        area = f'{r["living_area"]:.0f}m²' if pd.notna(r['living_area']) else '  n/a'
        print(f'{addr:40s} €{r["price_numeric"]:>10,.0f} €{r["predicted_price"]:>10,.0f} {r["residual_pct"]:>+6.1f}% {area:>6s}')

    conn.close()

    # ── summary ──
    print(f'\n{"="*50}')
    print('SUMMARY')
    print(f'{"="*50}')
    print(f'Apartment:  CV R² = {apt_metrics["r2"]:.3f}  |  MdAPE = {apt_metrics["mdape"]:.1f}%  |  MAE = €{apt_metrics["mae"]:,.0f}')
    print(f'House:      CV R² = {house_metrics["r2"]:.3f}  |  MdAPE = {house_metrics["mdape"]:.1f}%  |  MAE = €{house_metrics["mae"]:,.0f}')


if __name__ == '__main__':
    main()
