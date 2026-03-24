'use client'

import { useEffect, useState } from 'react'
import { NeighbourhoodDetail } from '@/app/lib/types'

interface NeighbourhoodStatsProps {
  neighbourhood: string
  currentPriceM2: number | null
}

export default function NeighbourhoodStats({ neighbourhood, currentPriceM2 }: NeighbourhoodStatsProps) {
  const [data, setData] = useState<NeighbourhoodDetail | null>(null)

  useEffect(() => {
    fetch(`/api/neighbourhoods/${encodeURIComponent(neighbourhood)}`)
      .then(r => r.json())
      .then(d => { if (!d.error) setData(d) })
      .catch(() => {})
  }, [neighbourhood])

  if (!data) return null

  const p = data.percentiles
  const cheaperThan = currentPriceM2 && p
    ? (() => {
        const vals = [p.p10, p.p25, p.p50, p.p75, p.p90]
        const below = vals.filter(v => currentPriceM2 < v).length
        // Rough estimate: each percentile band is 15-20%
        return Math.round((below / vals.length) * 100)
      })()
    : null

  return (
    <div className="mt-4 pt-3.5 border-t border-[var(--input-border)]">
      <h4 className="text-[var(--gold)] mb-2 text-[13px] uppercase tracking-wide font-semibold">
        Neighbourhood Analysis
      </h4>

      {cheaperThan !== null && (
        <p className="text-sm text-[var(--text)] mb-3">
          Cheaper than <strong className="text-[var(--gold)]">{cheaperThan}%</strong> of listings in{' '}
          <strong>{neighbourhood}</strong>
        </p>
      )}

      {/* Price range bar */}
      {p && currentPriceM2 && (
        <div className="mb-4">
          <div className="flex justify-between text-[10px] text-[var(--muted)] mb-1">
            <span>€{p.p10.toLocaleString()}/m²</span>
            <span>€{p.p90.toLocaleString()}/m²</span>
          </div>
          <div className="relative h-3 bg-[var(--input-bg)] rounded-full overflow-hidden">
            {/* Range bar */}
            <div
              className="absolute h-full bg-gradient-to-r from-[var(--green)] via-[var(--gold)] to-[var(--red)] rounded-full opacity-40"
              style={{
                left: '0%',
                right: '0%',
              }}
            />
            {/* Position marker */}
            {(() => {
              const pos = Math.max(0, Math.min(100, ((currentPriceM2 - p.p10) / (p.p90 - p.p10)) * 100))
              return (
                <div
                  className="absolute top-0 w-3 h-3 bg-[var(--gold)] rounded-full border-2 border-[var(--bg)] shadow-md"
                  style={{ left: `calc(${pos}% - 6px)` }}
                />
              )
            })()}
          </div>
          <div className="flex justify-between text-[10px] text-[var(--muted)] mt-1">
            <span>p10</span>
            <span>p90</span>
          </div>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-2">
        <div className="bg-[var(--input-bg)] p-2.5 rounded-lg text-center">
          <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Avg €/m²</div>
          <div className="font-semibold text-[var(--gold)] text-sm">
            €{data.avg_price_m2 ? Math.round(data.avg_price_m2).toLocaleString() : '--'}
          </div>
        </div>
        <div className="bg-[var(--input-bg)] p-2.5 rounded-lg text-center">
          <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Median</div>
          <div className="font-semibold text-[var(--gold)] text-sm">
            €{data.median_price ? Math.round(data.median_price).toLocaleString() : '--'}
          </div>
        </div>
        <div className="bg-[var(--input-bg)] p-2.5 rounded-lg text-center">
          <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">Listings</div>
          <div className="font-semibold text-[var(--gold)] text-sm">{data.listing_count ?? '--'}</div>
        </div>
      </div>
    </div>
  )
}
