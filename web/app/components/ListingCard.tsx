'use client'

import { ListingData } from '@/app/lib/types'
import ErfpachtBadge from './ErfpachtBadge'

interface ListingCardProps {
  listing: ListingData
  isFavourite: boolean
  onToggleFavourite: (id: number) => void
  onClick: () => void
}

function energyLabelColor(label: string | null): string {
  if (!label) return ''
  const base = label.replace(/[+]/g, '')
  const map: Record<string, string> = {
    A: 'text-[var(--green)]',
    B: 'text-[#94a86a]',
    C: 'text-[var(--gold)]',
    D: 'text-[#c47a50]',
    E: 'text-[#a04040]',
    F: 'text-[var(--red)]',
    G: 'text-[var(--red)]',
  }
  return map[base] || ''
}

export default function ListingCard({ listing, isFavourite, onToggleFavourite, onClick }: ListingCardProps) {
  const l = listing
  const isSold = l.availability_status === 'sold'
  const isOffer = l.availability_status === 'negotiations'
  const isNew = l.first_seen ? Date.now() - new Date(l.first_seen).getTime() < 86400000 : false
  const isJustListed = l.first_seen ? Date.now() - new Date(l.first_seen).getTime() < 3600000 : false
  const hasDrop = l.previous_price && l.previous_price > (l.price_numeric ?? 0)
  const dropPct = hasDrop ? Math.round((1 - (l.price_numeric ?? 0) / l.previous_price!) * 100) : 0

  let scoreClass = 'bg-[var(--input-border)] text-[var(--muted)]'
  if (l.score >= 15) scoreClass = 'bg-[var(--gold)] text-[#0a0b10]'
  else if (l.score >= 5) scoreClass = 'bg-[rgba(196,154,108,0.6)] text-[#111]'

  const imgUrl = l.image_url || (l.photo_urls?.length > 0 ? l.photo_urls[0] : '')

  // Prediction badge
  let predBadge = null
  if (l.predicted_price) {
    const diff = (l.price_numeric ?? 0) - l.predicted_price
    const absDiff = Math.abs(Math.round(diff / 1000))
    if (diff < 0) {
      predBadge = (
        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] font-bold bg-[rgba(106,173,122,0.15)] text-[var(--green)]">
          ↓ €{absDiff}k under
        </span>
      )
    } else {
      predBadge = (
        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[11px] font-bold bg-[rgba(122,48,48,0.15)] text-[var(--red)]">
          ↑ €{absDiff}k over
        </span>
      )
    }
  }

  return (
    <div
      className={`bg-[var(--card)] rounded-xl overflow-hidden relative border border-[var(--card-border)] transition-transform active:scale-[0.98] md:cursor-pointer md:hover:-translate-y-0.5 md:hover:shadow-[0_8px_24px_rgba(0,0,0,0.5)] md:hover:border-[#252530] ${
        isSold ? 'opacity-60' : ''
      }`}
      onClick={onClick}
    >
      {/* Badges */}
      <div className="absolute top-2 left-2 flex gap-1 z-[2]">
        {isSold && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[var(--red)] text-gray-200">Sold</span>}
        {isOffer && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[rgba(196,154,108,0.8)] text-[#0a0b10]">Offer</span>}
        {isJustListed && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[#e25555] text-white">Just Listed</span>}
        {!isJustListed && isNew && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[var(--gold)] text-[#0a0b10]">New</span>}
        {hasDrop && <span className="px-1.5 py-0.5 rounded text-[10px] font-bold uppercase bg-[var(--red)] text-gray-200">-{dropPct}%</span>}
      </div>

      {/* Score + Fav */}
      <div className="absolute top-2 right-2 flex gap-1 z-[2]">
        <span className={`px-1.5 py-0.5 rounded text-[11px] font-bold ${scoreClass}`}>
          {l.score?.toFixed(1) ?? '--'}
        </span>
        <button
          className={`bg-[rgba(0,0,0,0.5)] border-none cursor-pointer w-7 h-7 rounded-full flex items-center justify-center text-base ${
            isFavourite ? 'text-[#e25555]' : 'text-[#555]'
          }`}
          onClick={e => {
            e.stopPropagation()
            onToggleFavourite(l.global_id)
          }}
        >
          {isFavourite ? '♥' : '♡'}
        </button>
      </div>

      {/* Card content */}
      <div className="flex gap-0">
        <div className="w-[120px] md:w-[160px] min-h-[100px] md:min-h-[130px] bg-[#0c0d12] overflow-hidden shrink-0">
          {imgUrl && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={imgUrl}
              alt=""
              loading="lazy"
              referrerPolicy="no-referrer"
              className="w-full h-full object-cover block"
            />
          )}
        </div>
        <div className="px-3 py-2.5 flex-1 min-w-0">
          <div className="flex items-baseline gap-1.5 flex-wrap">
            <span className="text-lg font-bold text-[var(--gold)]">
              €{(l.price_numeric ?? 0).toLocaleString()}
            </span>
            {hasDrop && (
              <span className="text-xs text-[var(--red)] line-through">
                €{l.previous_price!.toLocaleString()}
              </span>
            )}
            {predBadge}
          </div>
          <div className="text-[13px] text-[var(--text)] mt-0.5 whitespace-nowrap overflow-hidden text-ellipsis">
            {l.address || 'Unknown'}
          </div>
          <div className="flex gap-2 text-[11px] text-[var(--muted)] mt-1 flex-wrap">
            {l.living_area && <span>{l.living_area}m²</span>}
            {l.bedrooms != null && <span>{l.bedrooms} bed</span>}
            {l.energy_label && <span className={energyLabelColor(l.energy_label)}>{l.energy_label}</span>}
            {l.year_built && <span>{l.year_built}</span>}
            {l.price_m2 && <span>€{Math.round(l.price_m2).toLocaleString()}/m²</span>}
          </div>
          <div className="flex gap-1.5 mt-1.5">
            <ErfpachtBadge erfpacht={l.erfpacht} compact />
          </div>
        </div>
      </div>
    </div>
  )
}
