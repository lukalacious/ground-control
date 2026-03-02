#!/usr/bin/env python3
"""Train housing price model and add predictions to database"""
import pandas as pd
import numpy as np
import sqlite3
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, r2_score
import joblib
import warnings
warnings.filterwarnings('ignore')

# Load data
print('Loading data...')
conn = sqlite3.connect('ground_control.db')
listings = pd.read_sql_query('SELECT * FROM listings', conn)
neighbourhood_stats = pd.read_sql_query('SELECT * FROM neighbourhood_stats', conn)
print(f'Loaded {len(listings)} listings')

# Feature engineering
cols_to_drop = ['address', 'city', 'listing_url', 'detail_url', 'agent_name', 'agent_url', 
                'image_url', 'plot_area', 'previous_price', 'labels', 'listing_type', 
                'is_active', 'availability_status', 'price', 'global_id']
df = listings.drop(columns=[c for c in cols_to_drop if c in listings.columns])
df = df.dropna(subset=['price_numeric'])
print(f'After cleaning: {len(df)} rows')

df['first_seen'] = pd.to_datetime(df['first_seen'], format='mixed', utc=True)
df['last_seen'] = pd.to_datetime(df['last_seen'], format='mixed', utc=True)
df['days_on_market'] = (df['last_seen'] - df['first_seen']).dt.days
df['postcode_prefix'] = df['postcode'].str[:4]

energy_map = {'A++++': 12, 'A+++': 11, 'A++': 10, 'A+': 9, 'A': 8, 
              'B': 7, 'C': 6, 'D': 5, 'E': 4, 'F': 3, 'G': 2, 'unknown': 0}
df['energy_score'] = df['energy_label'].map(energy_map).fillna(0)

df = df.merge(neighbourhood_stats[['neighbourhood', 'avg_price_m2', 'median_price']], 
              on='neighbourhood', how='left')
df['avg_price_m2'] = df['avg_price_m2'].fillna(neighbourhood_stats['avg_price_m2'].mean())
df['median_price'] = df['median_price'].fillna(df['median_price'].median())

numeric_features = ['living_area', 'bedrooms', 'days_on_market', 'energy_score', 
                   'avg_price_m2', 'median_price']
categorical_features = ['construction_type', 'postcode_prefix', 'is_project']
X = df[numeric_features + categorical_features].copy()
y = df['price_numeric']
X[numeric_features] = X[numeric_features].fillna(X[numeric_features].median())
X[categorical_features] = X[categorical_features].fillna('unknown')

X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
print(f'Train: {len(X_train)}, Test: {len(X_test)}')

preprocessor = ColumnTransformer(
    transformers=[
        ('num', StandardScaler(), numeric_features),
        ('cat', OneHotEncoder(handle_unknown='ignore'), categorical_features)
    ])
X_train_t = preprocessor.fit_transform(X_train)
X_test_t = preprocessor.transform(X_test)
print(f'Transformed shape: {X_train_t.shape}')

print('Training Gradient Boosting...')
gb = GradientBoostingRegressor(n_estimators=200, max_depth=5, learning_rate=0.1, random_state=42)
gb.fit(X_train_t, y_train)
gb_pred = gb.predict(X_test_t)
mae = mean_absolute_error(y_test, gb_pred)
r2 = r2_score(y_test, gb_pred)
print(f'Gradient Boosting - MAE: €{mae:,.0f}, R2: {r2:.3f}')

print('Saving model...')
full_pipeline = Pipeline([
    ('preprocessor', preprocessor),
    ('regressor', GradientBoostingRegressor(n_estimators=200, max_depth=5, learning_rate=0.1, random_state=42))
])
full_pipeline.fit(X, y)
joblib.dump(full_pipeline, 'housing_price_model.pkl')
print('Model saved to housing_price_model.pkl')

# Add predictions to original dataframe (for all listings in our feature df)
df['predicted_price'] = gb.predict(preprocessor.transform(X))
df['residual'] = df['price_numeric'] - df['predicted_price']  # positive = underpriced

# Get the global_ids for updating
predictions = df[['global_id', 'predicted_price', 'residual']].copy()

# Add columns to database if they don't exist
cursor = conn.cursor()
try:
    cursor.execute("ALTER TABLE listings ADD COLUMN predicted_price REAL")
except:
    pass
try:
    cursor.execute("ALTER TABLE listings ADD COLUMN residual REAL")  
except:
    pass

# Update records
for _, row in predictions.iterrows():
    cursor.execute(
        "UPDATE listings SET predicted_price = ?, residual = ? WHERE global_id = ?",
        (row['predicted_price'], row['residual'], row['global_id'])
    )

conn.commit()
print(f'Updated {len(predictions)} listings with predictions')
conn.close()

print('\n=== DONE ===')
print(f'Model MAE: €{mae:,.0f}')
print(f'Model R2: {r2:.3f}')
print('Model saved: housing_price_model.pkl')
print('Predictions added to database!')
