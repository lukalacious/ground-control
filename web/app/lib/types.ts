export interface ScoreDetails {
  vs_neighbourhood_pct: number | null
  vs_city_pct: number | null
  days_on_market: number
}

export interface PriceHistoryEntry {
  id: number
  global_id: number
  old_price: number
  new_price: number
  recorded_at: string
}

export interface ListingData {
  global_id: number
  address: string | null
  city: string | null
  postcode: string | null
  neighbourhood: string | null
  price: string | null
  price_numeric: number | null
  listing_url: string | null
  detail_url: string | null
  agent_name: string | null
  image_url: string | null
  living_area: number | null
  plot_area: number | null
  bedrooms: number | null
  energy_label: string | null
  object_type: string | null
  construction_type: string | null
  first_seen: string | null
  last_seen: string | null
  is_active: boolean
  availability_status: string | null
  previous_price: number | null
  predicted_price: number | null
  residual: number | null
  description: string | null
  year_built: string | null
  num_rooms: number | null
  num_bathrooms: number | null
  bathroom_features: string | null
  num_floors: number | null
  floor_level: string | null
  outdoor_area_m2: number | null
  volume_m3: number | null
  amenities: string | null
  insulation: string | null
  heating: string | null
  location_type: string | null
  has_balcony: boolean
  balcony_type: string | null
  parking_type: string | null
  vve_contribution: string | null
  erfpacht: string | null
  acceptance: string | null
  photo_urls: string[]
  price_m2: number | null
  score: number
  score_details: ScoreDetails
  days_on_market: number
  price_history?: PriceHistoryEntry[]
}

export interface NeighbourhoodData {
  name: string
  listing_count: number | null
  avg_price_m2: number | null
  median_price: number | null
}

export interface NeighbourhoodDetail extends NeighbourhoodData {
  percentiles: {
    p10: number
    p25: number
    p50: number
    p75: number
    p90: number
  } | null
}

export interface ListingsResponse {
  listings: ListingData[]
  total: number
  page: number
  pages: number
}
