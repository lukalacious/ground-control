-- CreateTable
CREATE TABLE "listings" (
    "global_id" INTEGER NOT NULL,
    "address" TEXT,
    "city" TEXT,
    "postcode" TEXT,
    "neighbourhood" TEXT,
    "price" TEXT,
    "price_numeric" INTEGER,
    "listing_url" TEXT,
    "detail_url" TEXT,
    "image_url" TEXT,
    "photo_urls" TEXT,
    "floorplan_urls" TEXT,
    "agent_name" TEXT,
    "agent_url" TEXT,
    "living_area" INTEGER,
    "plot_area" INTEGER,
    "bedrooms" INTEGER,
    "num_rooms" INTEGER,
    "num_bathrooms" INTEGER,
    "bathroom_features" TEXT,
    "num_floors" INTEGER,
    "floor_level" TEXT,
    "outdoor_area_m2" INTEGER,
    "volume_m3" INTEGER,
    "energy_label" TEXT,
    "object_type" TEXT,
    "construction_type" TEXT,
    "is_project" BOOLEAN NOT NULL DEFAULT false,
    "labels" TEXT,
    "listing_type" TEXT,
    "amenities" TEXT,
    "insulation" TEXT,
    "heating" TEXT,
    "location_type" TEXT,
    "has_balcony" BOOLEAN NOT NULL DEFAULT false,
    "balcony_type" TEXT,
    "parking_type" TEXT,
    "vve_contribution" TEXT,
    "erfpacht" TEXT,
    "acceptance" TEXT,
    "year_built" TEXT,
    "erfpacht_status" TEXT,
    "erfpacht_amount" DOUBLE PRECISION,
    "erfpacht_end_year" INTEGER,
    "description" TEXT,
    "description_en" TEXT,
    "description_translated" BOOLEAN NOT NULL DEFAULT false,
    "predicted_price" DOUBLE PRECISION,
    "residual" DOUBLE PRECISION,
    "first_seen" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "last_seen" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "availability_status" TEXT NOT NULL DEFAULT 'available',
    "status_changed_at" TIMESTAMP(3),
    "detail_enriched" BOOLEAN NOT NULL DEFAULT false,
    "detail_enriched_at" TIMESTAMP(3),

    CONSTRAINT "listings_pkey" PRIMARY KEY ("global_id")
);

-- CreateTable
CREATE TABLE "price_history" (
    "id" SERIAL NOT NULL,
    "global_id" INTEGER NOT NULL,
    "old_price" INTEGER NOT NULL,
    "new_price" INTEGER NOT NULL,
    "recorded_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "price_history_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "neighbourhood_stats" (
    "id" SERIAL NOT NULL,
    "neighbourhood" TEXT NOT NULL,
    "avg_price_m2" DOUBLE PRECISION,
    "median_price" DOUBLE PRECISION,
    "listing_count" INTEGER,
    "calculated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "neighbourhood_stats_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "city_stats" (
    "id" SERIAL NOT NULL,
    "avg_price_m2" DOUBLE PRECISION,
    "median_price" DOUBLE PRECISION,
    "median_days_on_market" DOUBLE PRECISION,
    "listing_count" INTEGER,
    "calculated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "city_stats_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "neighbourhood_analytics" (
    "id" SERIAL NOT NULL,
    "neighbourhood" TEXT NOT NULL,
    "p10_price_m2" DOUBLE PRECISION,
    "p25_price_m2" DOUBLE PRECISION,
    "p50_price_m2" DOUBLE PRECISION,
    "p75_price_m2" DOUBLE PRECISION,
    "p90_price_m2" DOUBLE PRECISION,
    "avg_price_m2" DOUBLE PRECISION,
    "median_price" DOUBLE PRECISION,
    "min_price" DOUBLE PRECISION,
    "max_price" DOUBLE PRECISION,
    "listing_count" INTEGER,
    "trend_data" TEXT,
    "calculated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "neighbourhood_analytics_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "scrape_runs" (
    "id" SERIAL NOT NULL,
    "run_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "city" TEXT,
    "search_type" TEXT,
    "pages_scraped" INTEGER,
    "listings_found" INTEGER,
    "new_listings" INTEGER,
    "updated_listings" INTEGER,

    CONSTRAINT "scrape_runs_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "listings_city_idx" ON "listings"("city");

-- CreateIndex
CREATE INDEX "listings_is_active_idx" ON "listings"("is_active");

-- CreateIndex
CREATE INDEX "listings_first_seen_idx" ON "listings"("first_seen");

-- CreateIndex
CREATE INDEX "listings_neighbourhood_idx" ON "listings"("neighbourhood");

-- CreateIndex
CREATE INDEX "listings_availability_status_idx" ON "listings"("availability_status");

-- CreateIndex
CREATE INDEX "price_history_global_id_idx" ON "price_history"("global_id");

-- CreateIndex
CREATE UNIQUE INDEX "neighbourhood_analytics_neighbourhood_key" ON "neighbourhood_analytics"("neighbourhood");

-- AddForeignKey
ALTER TABLE "price_history" ADD CONSTRAINT "price_history_global_id_fkey" FOREIGN KEY ("global_id") REFERENCES "listings"("global_id") ON DELETE RESTRICT ON UPDATE CASCADE;
