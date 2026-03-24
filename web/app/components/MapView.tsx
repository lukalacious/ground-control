'use client'

import { useEffect, useRef, useMemo } from 'react'
import { ListingData } from '@/app/lib/types'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'

interface MapViewProps {
  listings: ListingData[]
  onListingClick: (id: number) => void
}

function priceToColor(priceM2: number): string {
  const min = 3500, max = 11500
  const t = Math.max(0, Math.min(1, (priceM2 - min) / (max - min)))
  let r: number, g: number, b: number
  if (t < 0.5) {
    const s = t * 2
    r = Math.round(42 + s * 154)
    g = Math.round(110 + s * 44)
    b = Math.round(74 - s * 30)
  } else {
    const s = (t - 0.5) * 2
    r = Math.round(196 + s * 16)
    g = Math.round(154 - s * 96)
    b = Math.round(44 - s * 12)
  }
  return `rgb(${r},${g},${b})`
}

function bubbleRadius(count: number): number {
  return Math.max(8, Math.min(40, 8 + Math.sqrt(count) * 5.75))
}

export default function MapView({ listings, onListingClick }: MapViewProps) {
  const mapContainerRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const markersRef = useRef<L.Layer[]>([])

  // Aggregate listings by neighbourhood
  const aggregated = useMemo(() => {
    const agg: Record<string, { listings: ListingData[]; totalPm2: number; count: number }> = {}
    listings.forEach(l => {
      const hood = l.neighbourhood
      if (!hood) return
      if (!agg[hood]) agg[hood] = { listings: [], totalPm2: 0, count: 0 }
      agg[hood].listings.push(l)
      if (l.price_m2) {
        agg[hood].totalPm2 += l.price_m2
        agg[hood].count++
      }
    })
    return agg
  }, [listings])

  // Init map
  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return

    const map = L.map(mapContainerRef.current).setView([52.3676, 4.9041], 12)
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(map)

    mapRef.current = map

    return () => {
      map.remove()
      mapRef.current = null
    }
  }, [])

  // Update markers
  useEffect(() => {
    const map = mapRef.current
    if (!map) return

    // Clear old markers
    markersRef.current.forEach(m => map.removeLayer(m))
    markersRef.current = []

    // We need lat/lng for neighbourhoods. Since we don't have them from the API,
    // we'll compute the center from listing postcodes as a fallback.
    // For now, use a simplified approach: aggregate by neighbourhood and show bubbles.
    // Without coordinates in the DB, we'll use individual listing markers instead.

    // Individual marker approach for now
    listings.forEach(l => {
      // We don't have lat/lng in the listing data. Skip individual markers.
      // The original dashboard used MAP_DATA which had pre-computed coordinates.
    })

    // Neighbourhood bubbles — we need the neighbourhood_coords.json
    // For now, show a message if no coordinates available
    // This will be connected when neighbourhood coords are available via API

    // Invalidate size after rendering
    setTimeout(() => map.invalidateSize(), 100)
  }, [aggregated, listings])

  return (
    <div className="flex flex-col h-[calc(100dvh-var(--nav-h)-var(--safe-b))] md:h-[calc(100vh-52px)] relative z-[1]">
      <div ref={mapContainerRef} className="flex-1 z-[1]" />
      <div className="bg-[var(--card)] px-4 py-2.5 flex items-center gap-2.5 text-[11px] text-[var(--muted)] border-t border-[var(--card-border)]">
        <span className="whitespace-nowrap">€3.5k/m²</span>
        <div className="flex-1 h-2.5 rounded-[5px] bg-gradient-to-r from-[#2a6e4a] via-[#c49a6c] to-[#8b2020]" />
        <span className="whitespace-nowrap">€11.5k/m²</span>
      </div>
    </div>
  )
}
