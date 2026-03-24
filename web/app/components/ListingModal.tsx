'use client'

import { useState, useEffect, useRef, useCallback } from 'react'
import { ListingData } from '@/app/lib/types'
import ErfpachtBadge from './ErfpachtBadge'
import NeighbourhoodStats from './NeighbourhoodStats'
import Lightbox from './Lightbox'

interface ListingModalProps {
  listingId: number
  isFavourite: boolean
  onToggleFavourite: (id: number) => void
  onClose: () => void
  onListingClick: (id: number) => void
}

interface DetailData extends ListingData {
  neighbourhood_analytics: {
    neighbourhood: string
    avg_price_m2: number | null
    median_price: number | null
    listing_count: number | null
  } | null
  comparables: Array<{
    global_id: number
    address: string | null
    price_numeric: number | null
    living_area: number | null
    price_m2: number
    image_url: string | null
  }>
}

export default function ListingModal({ listingId, isFavourite, onToggleFavourite, onClose, onListingClick }: ListingModalProps) {
  const [data, setData] = useState<DetailData | null>(null)
  const [loading, setLoading] = useState(true)
  const [galleryIdx, setGalleryIdx] = useState(0)
  const [lightboxOpen, setLightboxOpen] = useState(false)
  const [descExpanded, setDescExpanded] = useState(false)
  const [showOriginal, setShowOriginal] = useState(false)
  const galleryRef = useRef<HTMLDivElement>(null)
  const touchRef = useRef({ startX: 0, currentX: 0 })

  useEffect(() => {
    setLoading(true)
    setGalleryIdx(0)
    fetch(`/api/listings/${listingId}`)
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [listingId])

  // Close on escape
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', handleKey)
      document.body.style.overflow = ''
    }
  }, [onClose])

  const goToSlide = useCallback((idx: number) => {
    const photos = data?.photo_urls || []
    setGalleryIdx(Math.max(0, Math.min(photos.length - 1, idx)))
  }, [data])

  if (loading) {
    return (
      <div className="fixed inset-0 bg-[rgba(0,0,0,0.9)] z-[1000] flex items-center justify-center">
        <div className="w-8 h-8 border-2 border-[var(--card-border)] border-t-[var(--gold)] rounded-full animate-spin" />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="fixed inset-0 bg-[rgba(0,0,0,0.9)] z-[1000] flex items-center justify-center">
        <p className="text-[var(--muted)]">Failed to load listing.</p>
        <button className="text-[var(--gold)] ml-4" onClick={onClose}>Close</button>
      </div>
    )
  }

  const l = data
  const photos = l.photo_urls || []
  const hasDrop = l.previous_price && l.previous_price > (l.price_numeric ?? 0)
  const dropPct = hasDrop ? Math.round((1 - (l.price_numeric ?? 0) / l.previous_price!) * 100) : 0
  const elBase = (l.energy_label || '').replace(/[+]/g, '')

  const elColorMap: Record<string, string> = {
    A: 'text-[var(--green)]', B: 'text-[#94a86a]', C: 'text-[var(--gold)]',
    D: 'text-[#c47a50]', E: 'text-[#a04040]', F: 'text-[var(--red)]', G: 'text-[var(--red)]',
  }

  return (
    <>
      <div className="fixed inset-0 bg-[rgba(0,0,0,0.9)] z-[1000] overflow-y-auto">
        <div className="bg-[var(--card)] min-h-screen md:min-h-0 md:max-w-[700px] md:mx-auto md:my-10 md:rounded-xl md:border md:border-[#252530] animate-[slideUp_0.25s_ease]">
          {/* Close button */}
          <button
            className="fixed md:absolute top-3 right-3 bg-[rgba(0,0,0,0.6)] border-none text-[#ccc] text-[28px] cursor-pointer w-10 h-10 rounded-full z-[1001] flex items-center justify-center active:bg-[rgba(0,0,0,0.9)]"
            onClick={onClose}
          >
            ×
          </button>

          {/* Photo Gallery */}
          {photos.length > 0 && (
            <div
              className="relative w-full h-[280px] md:h-[400px] bg-[#0c0d12] overflow-hidden"
              ref={galleryRef}
              onTouchStart={e => { touchRef.current.startX = e.touches[0].clientX }}
              onTouchMove={e => { touchRef.current.currentX = e.touches[0].clientX }}
              onTouchEnd={() => {
                const diff = touchRef.current.currentX - touchRef.current.startX
                if (Math.abs(diff) > 50) goToSlide(diff > 0 ? galleryIdx - 1 : galleryIdx + 1)
              }}
              onClick={() => setLightboxOpen(true)}
            >
              <div
                className="flex h-full transition-transform duration-300 ease-out will-change-transform"
                style={{ transform: `translateX(-${galleryIdx * 100}%)` }}
              >
                {photos.slice(0, 20).map((url, i) => (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    key={i}
                    src={url}
                    alt=""
                    referrerPolicy="no-referrer"
                    className="w-full h-full object-cover shrink-0"
                  />
                ))}
              </div>
              <div className="absolute bottom-2.5 right-3 bg-[rgba(0,0,0,0.6)] px-2 py-0.5 rounded-[10px] text-[11px] text-[#ccc]">
                {galleryIdx + 1}/{Math.min(photos.length, 20)}
              </div>
              <div className="absolute bottom-2.5 left-1/2 -translate-x-1/2 flex gap-1.5">
                {photos.slice(0, 20).map((_, i) => (
                  <div
                    key={i}
                    className={`w-1.5 h-1.5 rounded-full ${i === galleryIdx ? 'bg-[var(--gold)]' : 'bg-[rgba(255,255,255,0.3)]'}`}
                    onClick={e => { e.stopPropagation(); goToSlide(i) }}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Modal Body */}
          <div className="p-4">
            {/* Price + Address */}
            <div className="text-2xl font-bold text-[var(--gold)]">
              €{(l.price_numeric ?? 0).toLocaleString()}
              {hasDrop && (
                <span className="text-sm text-[var(--red)] line-through ml-2">
                  €{l.previous_price!.toLocaleString()} (-{dropPct}%)
                </span>
              )}
            </div>
            <div className="text-[15px] text-[var(--text)] mt-1">{l.address || 'Unknown'}</div>
            <div className="text-[var(--muted)] text-[13px] mb-3">
              {l.neighbourhood || ''}{l.postcode ? ` · ${l.postcode}` : ''}{l.city ? ` · ${l.city}` : ''}
            </div>

            {/* ML Prediction */}
            {l.predicted_price && (
              <div className="bg-[var(--input-bg)] rounded-[10px] p-3 mb-3.5 border border-[var(--card-border)]">
                <div className="flex justify-between items-center my-1 text-sm">
                  <span>ML Predicted</span>
                  <span className="font-semibold text-[var(--gold)] text-base">
                    €{Math.round(l.predicted_price).toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between items-center my-1 text-sm">
                  <span>Asking Price</span>
                  <span className="font-semibold">€{(l.price_numeric ?? 0).toLocaleString()}</span>
                </div>
                <div className="flex justify-between items-center my-1 text-sm">
                  <span>Difference</span>
                  {(() => {
                    const diff = (l.price_numeric ?? 0) - l.predicted_price!
                    const diffPct = ((diff / l.predicted_price!) * 100).toFixed(1)
                    const cls = diff > 0 ? 'text-[var(--red)]' : 'text-[var(--green)]'
                    const label = diff > 0 ? 'overpriced' : 'underpriced'
                    return (
                      <span className={`font-bold text-base ${cls}`}>
                        €{Math.abs(Math.round(diff)).toLocaleString()} ({Math.abs(parseFloat(diffPct))}% {label})
                      </span>
                    )
                  })()}
                </div>
              </div>
            )}

            {/* Key Facts Grid */}
            <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-3.5">
              {[
                ['Area', l.living_area ? `${l.living_area} m²` : '--'],
                ['Bedrooms', l.bedrooms?.toString() ?? '--'],
                ['Rooms', l.num_rooms?.toString() ?? '--'],
                ['Bathrooms', l.num_bathrooms?.toString() ?? '--'],
                ['Floors', l.num_floors?.toString() ?? '--'],
                ['Floor', l.floor_level || '--'],
                ['Year Built', l.year_built || '--'],
                ['Type', l.object_type || '--'],
                ['Energy', l.energy_label || '--', elColorMap[elBase]],
                ['€/m²', l.price_m2 ? `€${Math.round(l.price_m2).toLocaleString()}` : '--'],
                ['Outdoor', l.outdoor_area_m2 ? `${l.outdoor_area_m2} m²` : '--'],
                ['Volume', l.volume_m3 ? `${l.volume_m3} m³` : '--'],
                ['Balcony', l.has_balcony ? (l.balcony_type || 'Yes') : '--'],
                ['Parking', l.parking_type || '--'],
                ['Construction', l.construction_type || '--'],
                ['Plot', l.plot_area ? `${l.plot_area} m²` : '--'],
              ].map(([label, value, colorClass]) => (
                <div key={label as string} className="bg-[var(--input-bg)] p-2.5 rounded-lg text-center">
                  <div className="text-[10px] text-[var(--muted)] uppercase tracking-wide">{label}</div>
                  <div className={`font-semibold text-sm ${(colorClass as string) || 'text-[var(--gold)]'}`}>
                    {value}
                  </div>
                </div>
              ))}
            </div>

            {/* Financial */}
            {(l.erfpacht || l.vve_contribution || l.acceptance) && (
              <div className="mt-4 pt-3.5 border-t border-[var(--input-border)]">
                <h4 className="text-[var(--gold)] mb-2 text-[13px] uppercase tracking-wide font-semibold">Financial</h4>
                {l.erfpacht && (
                  <div className="flex justify-between items-center my-1.5 text-[13px]">
                    <span>Erfpacht</span>
                    <ErfpachtBadge erfpacht={l.erfpacht} />
                  </div>
                )}
                {l.vve_contribution && (
                  <div className="flex justify-between items-center my-1.5 text-[13px]">
                    <span>VvE</span>
                    <span className="font-semibold text-xs max-w-[200px] text-right">
                      {l.vve_contribution.length > 60 ? l.vve_contribution.slice(0, 60) + '...' : l.vve_contribution}
                    </span>
                  </div>
                )}
                {l.acceptance && (
                  <div className="flex justify-between items-center my-1.5 text-[13px]">
                    <span>Acceptance</span>
                    <span className="font-semibold">{l.acceptance}</span>
                  </div>
                )}
              </div>
            )}

            {/* Neighbourhood Analysis */}
            {l.neighbourhood && (
              <NeighbourhoodStats
                neighbourhood={l.neighbourhood}
                currentPriceM2={l.price_m2}
              />
            )}

            {/* Score Breakdown */}
            {l.score_details && (
              <div className="mt-4 pt-3.5 border-t border-[var(--input-border)]">
                <h4 className="text-[var(--gold)] mb-2 text-[13px] uppercase tracking-wide font-semibold">Deal Score</h4>
                <div className="flex justify-between items-center my-1.5 text-[13px]">
                  <span>vs Neighbourhood</span>
                  <span className="font-semibold">{l.score_details.vs_neighbourhood_pct != null ? `${l.score_details.vs_neighbourhood_pct}%` : 'n/a'}</span>
                </div>
                <div className="flex justify-between items-center my-1.5 text-[13px]">
                  <span>vs City avg</span>
                  <span className="font-semibold">{l.score_details.vs_city_pct != null ? `${l.score_details.vs_city_pct}%` : 'n/a'}</span>
                </div>
                <div className="flex justify-between items-center my-1.5 text-[13px]">
                  <span>Days on market</span>
                  <span className="font-semibold">{l.score_details.days_on_market}</span>
                </div>
                <div className="flex justify-between items-center my-1.5 text-[13px]">
                  <span className="font-bold">Total</span>
                  <span className="font-bold text-[var(--gold)]">{l.score?.toFixed(1) ?? '--'}</span>
                </div>
              </div>
            )}

            {/* Price History */}
            {l.price_history && l.price_history.length > 0 && (
              <div className="mt-4 pt-3.5 border-t border-[var(--input-border)]">
                <h4 className="text-[var(--gold)] mb-2 text-[13px] uppercase tracking-wide font-semibold">Price History</h4>
                {l.price_history.map((h, i) => (
                  <div key={i} className="flex justify-between items-center my-1.5 text-[13px]">
                    <span>{new Date(h.recorded_at).toLocaleDateString()}</span>
                    <span>€{h.old_price.toLocaleString()} → €{h.new_price.toLocaleString()}</span>
                  </div>
                ))}
              </div>
            )}

            {/* Comparables */}
            {l.comparables && l.comparables.length > 0 && (
              <div className="mt-4 pt-3.5 border-t border-[var(--input-border)]">
                <h4 className="text-[var(--gold)] mb-2 text-[13px] uppercase tracking-wide font-semibold">
                  Similar in {l.neighbourhood}
                </h4>
                <div className="flex gap-2 overflow-x-auto scrollbar-hide pb-2">
                  {l.comparables.map(c => (
                    <div
                      key={c.global_id}
                      className="bg-[var(--input-bg)] rounded-lg p-2.5 min-w-[150px] shrink-0 cursor-pointer border border-[var(--card-border)] hover:border-[var(--gold)] transition-colors"
                      onClick={() => onListingClick(c.global_id)}
                    >
                      <div className="text-sm font-bold text-[var(--gold)]">
                        €{(c.price_numeric ?? 0).toLocaleString()}
                      </div>
                      <div className="text-[11px] text-[var(--text)] mt-0.5 whitespace-nowrap overflow-hidden text-ellipsis">
                        {c.address || 'Unknown'}
                      </div>
                      <div className="text-[10px] text-[var(--muted)] mt-1">
                        {c.living_area}m² · €{Math.round(c.price_m2).toLocaleString()}/m²
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Description */}
            {l.description && (
              <div className="mt-4 pt-3.5 border-t border-[var(--input-border)]">
                <h4 className="text-[var(--gold)] mb-2 text-[13px] uppercase tracking-wide font-semibold">
                  Description
                  <button
                    className="ml-3 text-[11px] text-[var(--muted)] font-normal underline"
                    onClick={() => setShowOriginal(!showOriginal)}
                  >
                    {showOriginal ? 'Show translated' : 'Show original Dutch'}
                  </button>
                </h4>
                <div
                  className={`text-[13px] text-[var(--muted)] leading-relaxed relative ${
                    descExpanded ? '' : 'max-h-[120px] overflow-hidden'
                  }`}
                >
                  {l.description}
                </div>
                <button
                  className="text-[var(--gold)] text-xs font-semibold cursor-pointer mt-1"
                  onClick={() => setDescExpanded(!descExpanded)}
                >
                  {descExpanded ? 'Show less' : 'Show more'}
                </button>
              </div>
            )}

            {/* Features */}
            {(() => {
              const features: [string, string | null][] = [
                ['Amenities', l.amenities],
                ['Insulation', l.insulation],
                ['Heating', l.heating],
                ['Location', l.location_type],
                ['Bathroom', l.bathroom_features],
              ].filter(([, v]) => v) as [string, string][]
              if (features.length === 0) return null
              return (
                <div className="mt-4 pt-3.5 border-t border-[var(--input-border)]">
                  <h4 className="text-[var(--gold)] mb-2 text-[13px] uppercase tracking-wide font-semibold">Features</h4>
                  {features.map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center my-1.5 text-[13px]">
                      <span>{k}</span>
                      <span className="font-semibold text-xs max-w-[200px] text-right">{v}</span>
                    </div>
                  ))}
                </div>
              )
            })()}

            {/* Actions */}
            <div className="mt-4 pt-4 border-t border-[var(--input-border)] flex gap-2.5">
              <a
                href={l.detail_url || '#'}
                target="_blank"
                rel="noopener noreferrer"
                className="flex-1 py-3 bg-[var(--gold)] text-[#0a0b10] border-none rounded-[10px] cursor-pointer font-bold text-sm text-center no-underline flex items-center justify-center active:opacity-80"
              >
                View on Funda →
              </a>
              <button
                className="flex-1 py-3 bg-transparent border border-[#252530] text-[var(--muted2)] rounded-[10px] cursor-pointer font-bold text-sm active:opacity-80"
                onClick={() => onToggleFavourite(l.global_id)}
              >
                {isFavourite ? '♥ Saved' : '♡ Save'}
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Lightbox */}
      {lightboxOpen && photos.length > 0 && (
        <Lightbox
          photos={photos}
          initialIndex={galleryIdx}
          onClose={() => setLightboxOpen(false)}
        />
      )}
    </>
  )
}
