/**
 * Undervalue scorer — replicated from scorer.py
 *
 * Weights:
 *   40% price/m2 vs neighbourhood avg
 *   30% price/m2 vs city avg
 *   30% days on market (capped at 90)
 */

const WEIGHTS = {
  vs_neighbourhood: 0.40,
  vs_city: 0.30,
  days_on_market: 0.30,
}

export interface ScoreDetails {
  vs_neighbourhood_pct: number | null
  vs_city_pct: number | null
  days_on_market: number
}

export interface ScoredFields {
  price_m2: number | null
  score: number
  score_details: ScoreDetails
  days_on_market: number
}

export function scoreListing(
  price_numeric: number,
  living_area: number | null,
  neighbourhood_avg_m2: number | null,
  city_avg_m2: number | null,
  first_seen: Date | null,
): ScoredFields {
  let score = 0
  const details: ScoreDetails = {
    vs_neighbourhood_pct: null,
    vs_city_pct: null,
    days_on_market: 0,
  }

  let price_m2: number | null = null
  if (living_area && living_area > 0) {
    price_m2 = price_numeric / living_area
  }

  if (price_m2 !== null) {
    // vs neighbourhood
    if (neighbourhood_avg_m2 && neighbourhood_avg_m2 > 0) {
      const diff = (neighbourhood_avg_m2 - price_m2) / neighbourhood_avg_m2
      score += diff * WEIGHTS.vs_neighbourhood * 100
      details.vs_neighbourhood_pct = Math.round(diff * 1000) / 10
    }

    // vs city
    if (city_avg_m2 && city_avg_m2 > 0) {
      const diff = (city_avg_m2 - price_m2) / city_avg_m2
      score += diff * WEIGHTS.vs_city * 100
      details.vs_city_pct = Math.round(diff * 1000) / 10
    }
  }

  // Days on market
  let days_on_market = 0
  if (first_seen) {
    const now = new Date()
    days_on_market = Math.max(0, Math.floor((now.getTime() - first_seen.getTime()) / 86400000))
  }
  const days_score = (Math.min(days_on_market, 90) / 90) * WEIGHTS.days_on_market * 100
  score += days_score
  details.days_on_market = days_on_market

  return {
    price_m2: price_m2 !== null ? Math.round(price_m2 * 10) / 10 : null,
    score: Math.round(score * 100) / 100,
    score_details: details,
    days_on_market,
  }
}
