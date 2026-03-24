'use client'

import { useState, useEffect } from 'react'
import { NeighbourhoodData } from '@/app/lib/types'

interface FilterState {
  sort: string
  minPrice: string
  maxPrice: string
  minArea: string
  maxArea: string
  bedrooms: string
  neighbourhoods: string[]
  status: string[]
  erfpachtStatus: string
  search: string
  newOnly: boolean
  priceDropOnly: boolean
}

interface FiltersProps {
  open: boolean
  filters: FilterState
  onClose: () => void
  onApply: (filters: FilterState) => void
  onReset: () => void
}

export default function Filters({ open, filters, onClose, onApply, onReset }: FiltersProps) {
  const [local, setLocal] = useState<FilterState>(filters)
  const [neighbourhoods, setNeighbourhoods] = useState<NeighbourhoodData[]>([])

  useEffect(() => {
    setLocal(filters)
  }, [filters])

  useEffect(() => {
    fetch('/api/neighbourhoods')
      .then(r => r.json())
      .then(d => setNeighbourhoods(d.neighbourhoods || []))
      .catch(() => {})
  }, [])

  const update = (partial: Partial<FilterState>) => {
    setLocal(prev => ({ ...prev, ...partial }))
  }

  const toggleStatus = (s: string) => {
    update({
      status: local.status.includes(s)
        ? local.status.filter(x => x !== s)
        : [...local.status, s],
    })
  }

  const toggleNeighbourhood = (name: string) => {
    update({
      neighbourhoods: local.neighbourhoods.includes(name)
        ? local.neighbourhoods.filter(x => x !== name)
        : [...local.neighbourhoods, name],
    })
  }

  if (!open) return null

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 bg-[rgba(0,0,0,0.6)] z-[950]"
        onClick={onClose}
      />

      {/* Drawer */}
      <div className="fixed bottom-0 left-0 right-0 md:left-auto md:right-0 md:max-w-[420px] md:rounded-tl-2xl bg-[var(--card)] rounded-t-2xl max-h-[85vh] md:max-h-[calc(100vh-52px)] overflow-y-auto z-[960] pb-[calc(16px+var(--safe-b))]">
        {/* Handle */}
        <div className="w-9 h-1 bg-[#333] rounded-full mx-auto mt-2.5 mb-1.5" />

        {/* Header */}
        <div className="flex justify-between items-center px-5 pt-1 pb-3 border-b border-[var(--card-border)]">
          <h3 className="text-[var(--gold)] text-base font-semibold">Filters</h3>
          <button
            className="px-3 py-1.5 bg-transparent border border-[#252530] text-[var(--muted2)] rounded-[10px] text-sm font-bold"
            onClick={onReset}
          >
            Reset
          </button>
        </div>

        {/* Price Range */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Price Range</h4>
          <div className="flex gap-2">
            <input
              type="number"
              placeholder="Min €"
              value={local.minPrice}
              onChange={e => update({ minPrice: e.target.value })}
              step="10000"
              className="flex-1 px-3 py-2.5 border border-[var(--input-border)] rounded-lg bg-[var(--input-bg)] text-[var(--text)] text-sm focus:outline-none focus:border-[var(--gold)]"
            />
            <input
              type="number"
              placeholder="Max €"
              value={local.maxPrice}
              onChange={e => update({ maxPrice: e.target.value })}
              step="10000"
              className="flex-1 px-3 py-2.5 border border-[var(--input-border)] rounded-lg bg-[var(--input-bg)] text-[var(--text)] text-sm focus:outline-none focus:border-[var(--gold)]"
            />
          </div>
        </div>

        {/* Living Area */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Living Area (m²)</h4>
          <div className="flex gap-2">
            <input
              type="number"
              placeholder="Min"
              value={local.minArea}
              onChange={e => update({ minArea: e.target.value })}
              step="5"
              className="flex-1 px-3 py-2.5 border border-[var(--input-border)] rounded-lg bg-[var(--input-bg)] text-[var(--text)] text-sm focus:outline-none focus:border-[var(--gold)]"
            />
            <input
              type="number"
              placeholder="Max"
              value={local.maxArea}
              onChange={e => update({ maxArea: e.target.value })}
              step="5"
              className="flex-1 px-3 py-2.5 border border-[var(--input-border)] rounded-lg bg-[var(--input-bg)] text-[var(--text)] text-sm focus:outline-none focus:border-[var(--gold)]"
            />
          </div>
        </div>

        {/* Bedrooms */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Bedrooms</h4>
          <div className="flex gap-2">
            <input
              type="number"
              placeholder="Min"
              value={local.bedrooms}
              onChange={e => update({ bedrooms: e.target.value })}
              min="0"
              max="10"
              className="flex-1 px-3 py-2.5 border border-[var(--input-border)] rounded-lg bg-[var(--input-bg)] text-[var(--text)] text-sm focus:outline-none focus:border-[var(--gold)]"
            />
          </div>
        </div>

        {/* Status */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Status</h4>
          <div className="flex flex-wrap gap-2">
            {[
              { key: 'available', label: 'Available' },
              { key: 'negotiations', label: 'Under Offer' },
              { key: 'sold', label: 'Sold' },
            ].map(s => (
              <button
                key={s.key}
                onClick={() => toggleStatus(s.key)}
                className={`px-3.5 py-2 rounded-lg text-[13px] font-semibold border cursor-pointer transition-all ${
                  local.status.includes(s.key)
                    ? s.key === 'sold'
                      ? 'bg-[var(--red)] text-gray-200 border-[var(--red)]'
                      : 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                    : 'bg-transparent text-[var(--muted2)] border-[#252530]'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Erfpacht */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Erfpacht Status</h4>
          <div className="flex flex-wrap gap-2">
            {[
              { key: '', label: 'All' },
              { key: 'freehold', label: 'Freehold' },
              { key: 'leasehold', label: 'Leasehold' },
            ].map(s => (
              <button
                key={s.key}
                onClick={() => update({ erfpachtStatus: s.key })}
                className={`px-3.5 py-2 rounded-lg text-[13px] font-semibold border cursor-pointer transition-all ${
                  local.erfpachtStatus === s.key
                    ? 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                    : 'bg-transparent text-[var(--muted2)] border-[#252530]'
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>
        </div>

        {/* Energy Label */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Energy Label</h4>
          <select
            value=""
            onChange={() => {}}
            className="w-full px-3 py-2.5 border border-[var(--input-border)] rounded-lg bg-[var(--input-bg)] text-[var(--text)] text-sm focus:outline-none focus:border-[var(--gold)]"
          >
            <option value="">All</option>
            <option value="A">A+</option>
            <option value="B">B</option>
            <option value="C">C</option>
            <option value="D">D</option>
            <option value="E">E+</option>
          </select>
        </div>

        {/* Quick Filters */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Quick Filters</h4>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => update({ newOnly: !local.newOnly })}
              className={`px-3.5 py-2 rounded-lg text-[13px] font-semibold border cursor-pointer transition-all ${
                local.newOnly
                  ? 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                  : 'bg-transparent text-[var(--muted2)] border-[#252530]'
              }`}
            >
              New (24h)
            </button>
            <button
              onClick={() => update({ priceDropOnly: !local.priceDropOnly })}
              className={`px-3.5 py-2 rounded-lg text-[13px] font-semibold border cursor-pointer transition-all ${
                local.priceDropOnly
                  ? 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                  : 'bg-transparent text-[var(--muted2)] border-[#252530]'
              }`}
            >
              Price Drops
            </button>
          </div>
        </div>

        {/* Sort */}
        <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
          <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">Sort By</h4>
          <select
            value={local.sort}
            onChange={e => update({ sort: e.target.value })}
            className="w-full px-3 py-2.5 border border-[var(--input-border)] rounded-lg bg-[var(--input-bg)] text-[var(--text)] text-sm focus:outline-none focus:border-[var(--gold)]"
          >
            <option value="score">Best deal</option>
            <option value="price_asc">Price ↑</option>
            <option value="price_desc">Price ↓</option>
            <option value="price_m2">€/m² ↑</option>
            <option value="area">Largest</option>
            <option value="newest">Newest</option>
            <option value="days_on_market">Longest listed</option>
          </select>
        </div>

        {/* Neighbourhoods */}
        {neighbourhoods.length > 0 && (
          <div className="px-5 py-3.5 border-b border-[var(--card-border)]">
            <h4 className="text-xs text-[var(--muted2)] uppercase tracking-wide mb-2.5 font-semibold">
              Neighbourhoods
              {local.neighbourhoods.length > 0 && (
                <span className="text-[var(--muted)] ml-2 font-normal">
                  ({local.neighbourhoods.length} selected)
                </span>
              )}
            </h4>
            <div className="flex flex-wrap gap-1 max-h-[200px] overflow-y-auto">
              {neighbourhoods.map(n => (
                <button
                  key={n.name}
                  onClick={() => toggleNeighbourhood(n.name)}
                  className={`px-2 py-1 rounded-[10px] text-[10px] font-semibold border whitespace-nowrap cursor-pointer transition-all ${
                    local.neighbourhoods.includes(n.name)
                      ? 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                      : 'bg-transparent text-[var(--muted2)] border-[#252530]'
                  }`}
                >
                  {n.name} ({n.listing_count ?? 0})
                </button>
              ))}
            </div>
            <div className="flex gap-1.5 mt-2">
              <button
                className="flex-1 px-2.5 py-1.5 bg-transparent border border-[#252530] text-[var(--muted2)] rounded-lg text-[11px] font-bold"
                onClick={() => update({ neighbourhoods: neighbourhoods.map(n => n.name) })}
              >
                Select All
              </button>
              <button
                className="flex-1 px-2.5 py-1.5 bg-transparent border border-[#252530] text-[var(--muted2)] rounded-lg text-[11px] font-bold"
                onClick={() => update({ neighbourhoods: [] })}
              >
                Deselect All
              </button>
            </div>
          </div>
        )}

        {/* Apply button */}
        <div className="px-5 py-3.5 flex gap-2.5">
          <button
            className="flex-1 py-3 bg-[var(--gold)] text-[#0a0b10] border-none rounded-[10px] cursor-pointer font-bold text-sm text-center active:opacity-80"
            onClick={() => onApply(local)}
          >
            Apply Filters
          </button>
        </div>
      </div>
    </>
  )
}
