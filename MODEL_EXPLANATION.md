# Housing Price Prediction Model — Plain English Explanation

This document explains the machine learning model that predicts Amsterdam apartment prices using data scraped from Ground Control.

---

## 1. The Data

The dataset contains **4,471 apartment listings** from Ground Control, stored in a SQLite database. Each listing has the following fields used by the model:

| Field | What it means |
|---|---|
| **living_area** | Size of the apartment in square metres |
| **bedrooms** | Number of bedrooms |
| **days_on_market** | How many days the listing has been active on the platform (calculated from first seen to last seen dates) |
| **energy_label** | Energy efficiency rating from A++++ (best) down to G (worst), converted to a numeric score of 0–12 |
| **construction_type** | The type of building — e.g. existing construction vs new build |
| **postcode_prefix** | The first four digits of the postcode, which captures the general area within Amsterdam |
| **is_project** | Whether the listing is part of a new development project |
| **avg_price_m2** | The average price per square metre in that neighbourhood (from pre-calculated neighbourhood statistics) |
| **median_price** | The median listing price in that neighbourhood |
| **price_numeric** | The actual asking price in euros — this is what the model tries to predict |

---

## 2. How the Model Works

The notebook tests four different models. In simple terms:

- **Linear Regression** — Draws a straight line through the data. Simple but limited; it assumes every feature has a constant, additive effect on price.
- **Ridge Regression** — Same idea as linear regression but with a penalty that prevents the model from over-relying on any single feature.
- **Random Forest** — Builds 200 decision trees, each trained on a random sample of the data. Each tree makes its own price guess, and the final prediction is the average of all 200 trees. This captures complex patterns that a straight line would miss (e.g. "big apartments in Oud-Zuid are worth disproportionately more").
- **Gradient Boosting** — Builds trees one at a time, where each new tree focuses on correcting the mistakes of the previous ones. This is the model that gets saved for production use.

Before training, the model transforms the data:
- Numeric features (like living area and bedrooms) are **scaled** so they're all on a comparable range.
- Categorical features (like postcode and construction type) are **one-hot encoded** — each category becomes its own yes/no column.

The data is split 80/20: 80% for training, 20% for testing on data the model has never seen.

---

## 3. The Results

Two key metrics tell us how well the model performs:

### MAE (Mean Absolute Error) — "How far off is the model, on average?"

- **Test MAE: ~€61,300**
- This means that on average, the model's prediction is about €61,000 away from the actual asking price.
- For a €500,000 apartment, the prediction would typically land somewhere between €439,000 and €561,000.

### R² (R-squared) — "How much of the price variation does the model explain?"

- **Test R²: 0.884**
- R² ranges from 0 (the model explains nothing) to 1 (the model explains everything perfectly).
- A score of 0.884 means the model explains about **88% of the variation** in apartment prices. The remaining 12% comes from factors the model doesn't capture — things like interior condition, floor level, view, renovation quality, or simply unusual listings.

---

## 4. Generalization Analysis (Train vs Test Gap)

| Metric | Training Data | Test Data | Gap |
|---|---|---|---|
| MAE | €24,727 | €61,303 | 2.5x worse on test |
| R² | 0.975 | 0.884 | 0.091 drop |

**What this means:** The model performs significantly better on data it was trained on than on new data it hasn't seen before. This is a sign of **overfitting** — the model has memorised some patterns in the training data that don't generalise to new listings.

Think of it like a student who scores 97% on practice exams but 88% on the real exam. They've learned the material well but have also memorised some specific practice questions rather than fully understanding the underlying concepts.

The 2.5x gap in MAE is notable. On training data the model is off by about €25,000, but on new listings it's off by about €61,000. This suggests the Random Forest (with max_depth=25 and 500 trees in the best configuration) is fitting too closely to the training data.

---

## 5. Recommendations for Improvement

### Reduce overfitting
- **Limit tree depth further** — the current max_depth of 25 lets trees grow very deep, memorising individual listings. Trying 10–15 would force the model to learn broader patterns.
- **Increase min_samples_leaf** — requiring each tree leaf to contain at least 5–10 listings (instead of just 1) prevents the model from creating rules that apply to only a single apartment.
- **Use cross-validation** — instead of one 80/20 split, test on 5 different splits and average the results. This gives a more honest picture of performance.

### Add more useful features
- **Floor level** — higher floors generally command premium prices in Amsterdam.
- **Balcony/garden/roof terrace** — outdoor space significantly affects price.
- **Year of construction** — older canal houses vs 1960s flats vs modern builds have very different pricing.
- **Interior photos or condition score** — a renovated apartment is worth far more than one needing work.
- **Distance to centre/transit** — proximity to Amsterdam Centraal or nearest metro station.

### Improve the target variable
- The model predicts the **asking price**, not the **sale price**. Asking prices can be unrealistic in either direction. If transaction data were available, the model would learn more grounded pricing patterns.

### Handle outliers
- Extremely expensive properties (€2M+) and very cheap ones can distort the model. Consider training separate models for different price segments, or capping extreme values.

### Try more advanced models
- **XGBoost or LightGBM** — these are optimised versions of gradient boosting that often perform better and train faster.
- **Stacking** — combine predictions from multiple models to get a more robust estimate.

---

## How the Model is Used

The trained model is saved as `housing_price_model.pkl` and predictions are written back to the database. Each listing gets:

- **predicted_price** — what the model thinks the apartment should cost based on its features.
- **residual** — the difference between the actual asking price and the predicted price. A positive residual means the apartment is listed below what the model expects (potentially a good deal). A negative residual means it's listed above the model's estimate (potentially overpriced).

This lets you sort listings by residual to find apartments that might be undervalued relative to their size, location, and features.
