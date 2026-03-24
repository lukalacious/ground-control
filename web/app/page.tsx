'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { ListingData, ListingsResponse } from '@/app/lib/types'
import BottomNav from '@/app/components/BottomNav'
import ListingCard from '@/app/components/ListingCard'
import ListingModal from '@/app/components/ListingModal'
import Filters from '@/app/components/Filters'
import dynamic from 'next/dynamic'

const MapView = dynamic(() => import('@/app/components/MapView'), { ssr: false })

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

const defaultFilters: FilterState = {
  sort: 'score',
  minPrice: '',
  maxPrice: '',
  minArea: '',
  maxArea: '',
  bedrooms: '',
  neighbourhoods: [],
  status: ['available', 'negotiations'],
  erfpachtStatus: '',
  search: '',
  newOnly: false,
  priceDropOnly: false,
}

export default function Home() {
  const [view, setView] = useState<'list' | 'map' | 'favs'>('list')
  const [listings, setListings] = useState<ListingData[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [pages, setPages] = useState(1)
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [filters, setFilters] = useState<FilterState>(defaultFilters)
  const [filtersOpen, setFiltersOpen] = useState(false)
  const [selectedListing, setSelectedListing] = useState<number | null>(null)
  const [favourites, setFavourites] = useState<Set<number>>(new Set())
  const [statsBar, setStatsBar] = useState<{ total: number; avgM2: number; newToday: number }>({
    total: 0,
    avgM2: 0,
    newToday: 0,
  })
  const loadMoreRef = useRef<HTMLDivElement>(null)
  const searchTimeoutRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  // Load favourites from localStorage
  useEffect(() => {
    try {
      const saved = localStorage.getItem('gc_favourites')
      if (saved) {
        const arr = JSON.parse(saved) as number[]
        setFavourites(new Set(arr))
      }
    } catch {}
  }, [])

  const toggleFavourite = useCallback((id: number) => {
    setFavourites(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      localStorage.setItem('gc_favourites', JSON.stringify([...next]))
      return next
    })
  }, [])

  const buildQueryString = useCallback((f: FilterState, p: number) => {
    const params = new URLSearchParams()
    params.set('page', String(p))
    params.set('limit', '50')
    params.set('sort', f.sort)
    if (f.minPrice) params.set('minPrice', f.minPrice)
    if (f.maxPrice) params.set('maxPrice', f.maxPrice)
    if (f.minArea) params.set('minArea', f.minArea)
    if (f.maxArea) params.set('maxArea', f.maxArea)
    if (f.bedrooms) params.set('bedrooms', f.bedrooms)
    if (f.neighbourhoods.length > 0) params.set('neighbourhood', f.neighbourhoods.join(','))
    if (f.status.length > 0) params.set('status', f.status.join(','))
    if (f.erfpachtStatus) params.set('erfpachtStatus', f.erfpachtStatus)
    if (f.search) params.set('search', f.search)
    if (f.newOnly) params.set('newOnly', 'true')
    if (f.priceDropOnly) params.set('priceDropOnly', 'true')
    return params.toString()
  }, [])

  const fetchListings = useCallback(async (f: FilterState, p: number, append: boolean = false) => {
    if (append) setLoadingMore(true)
    else setLoading(true)

    try {
      const qs = buildQueryString(f, p)
      const res = await fetch(`/api/listings?${qs}`)
      const data: ListingsResponse = await res.json()

      if (append) {
        setListings(prev => [...prev, ...data.listings])
      } else {
        setListings(data.listings)
      }
      setTotal(data.total)
      setPage(data.page)
      setPages(data.pages)

      // Stats
      if (!append) {
        const newToday = data.listings.filter(l => {
          if (!l.first_seen) return false
          return Date.now() - new Date(l.first_seen).getTime() < 86400000
        }).length
        const avgM2 = data.listings.length > 0
          ? Math.round(data.listings.reduce((s, l) => s + (l.price_m2 || 0), 0) / data.listings.filter(l => l.price_m2).length)
          : 0
        setStatsBar({ total: data.total, avgM2, newToday })
      }
    } catch (err) {
      console.error('Failed to fetch listings:', err)
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [buildQueryString])

  // Initial load
  useEffect(() => {
    fetchListings(filters, 1)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Apply filters
  const applyFilters = useCallback((newFilters: FilterState) => {
    setFilters(newFilters)
    fetchListings(newFilters, 1)
  }, [fetchListings])

  // Search with debounce
  const handleSearch = useCallback((search: string) => {
    if (searchTimeoutRef.current) clearTimeout(searchTimeoutRef.current)
    searchTimeoutRef.current = setTimeout(() => {
      const newFilters = { ...filters, search }
      setFilters(newFilters)
      fetchListings(newFilters, 1)
    }, 300)
  }, [filters, fetchListings])

  // Infinite scroll
  useEffect(() => {
    if (!loadMoreRef.current) return
    const observer = new IntersectionObserver(
      entries => {
        if (entries[0].isIntersecting && !loadingMore && page < pages) {
          fetchListings(filters, page + 1, true)
        }
      },
      { rootMargin: '400px' }
    )
    observer.observe(loadMoreRef.current)
    return () => observer.disconnect()
  }, [page, pages, loadingMore, filters, fetchListings])

  // Get fav listings
  const favListings = listings.filter(l => favourites.has(l.global_id))

  const activeFilterCount = [
    filters.minPrice, filters.maxPrice, filters.minArea, filters.maxArea,
    filters.bedrooms, filters.erfpachtStatus,
  ].filter(Boolean).length
    + (filters.newOnly ? 1 : 0)
    + (filters.priceDropOnly ? 1 : 0)
    + (filters.status.length !== 2 || filters.status.includes('sold') ? 1 : 0)
    + (filters.neighbourhoods.length > 0 ? 1 : 0)

  return (
    <div className="min-h-screen">
      {/* Loading screen */}
      {loading && listings.length === 0 && (
        <div className="fixed inset-0 bg-[var(--bg)] z-[9999] flex flex-col items-center justify-center gap-4">
          <div className="w-9 h-9 border-3 border-[var(--card-border)] border-t-[var(--gold)] rounded-full animate-spin" />
          <h2 className="text-[var(--gold)] text-xl font-semibold">Ground Control</h2>
          <div className="text-[var(--muted)] text-xs">Loading listings...</div>
        </div>
      )}

      {/* List View */}
      {view === 'list' && (
        <div>
          {/* Header */}
          <div className="px-4 pt-3 flex items-center gap-2.5">
            <h1 className="text-[var(--gold)] text-lg font-bold tracking-wide whitespace-nowrap">
              Ground Control
            </h1>
          </div>

          {/* Search */}
          <div className="px-4 py-2.5">
            <input
              type="text"
              placeholder="Search address, postcode, neighbourhood..."
              defaultValue={filters.search}
              onChange={e => handleSearch(e.target.value)}
              className="w-full px-3.5 py-2.5 border border-[var(--input-border)] rounded-[10px] bg-[var(--card)] text-[var(--text)] text-[15px] placeholder-[#4a4640] focus:outline-none focus:border-[var(--gold)]"
            />
          </div>

          {/* Stats bar */}
          <div className="flex gap-2 px-4 pb-2.5 overflow-x-auto scrollbar-hide">
            <div className="bg-[var(--card)] px-3.5 py-2.5 rounded-[10px] min-w-[90px] text-center shrink-0 border border-[var(--card-border)]">
              <div className="text-[17px] font-bold text-[var(--gold)]">{statsBar.total}</div>
              <div className="text-[9px] text-[var(--muted)] mt-0.5 uppercase tracking-wide">Total</div>
            </div>
            <div className="bg-[var(--card)] px-3.5 py-2.5 rounded-[10px] min-w-[90px] text-center shrink-0 border border-[var(--card-border)]">
              <div className="text-[17px] font-bold text-[var(--gold)]">{statsBar.newToday}</div>
              <div className="text-[9px] text-[var(--muted)] mt-0.5 uppercase tracking-wide">New 24h</div>
            </div>
            <div className="bg-[var(--card)] px-3.5 py-2.5 rounded-[10px] min-w-[90px] text-center shrink-0 border border-[var(--card-border)]">
              <div className="text-[17px] font-bold text-[var(--gold)]">
                {statsBar.avgM2 ? `€${statsBar.avgM2.toLocaleString()}` : '--'}
              </div>
              <div className="text-[9px] text-[var(--muted)] mt-0.5 uppercase tracking-wide">Avg /m²</div>
            </div>
          </div>

          {/* Quick filter chips */}
          <div className="flex gap-1.5 px-4 pb-2 overflow-x-auto scrollbar-hide">
            {['available', 'negotiations', 'sold'].map(s => (
              <button
                key={s}
                onClick={() => {
                  const newStatus = filters.status.includes(s)
                    ? filters.status.filter(x => x !== s)
                    : [...filters.status, s]
                  applyFilters({ ...filters, status: newStatus })
                }}
                className={`px-3 py-1.5 rounded-[14px] text-xs font-semibold border whitespace-nowrap shrink-0 transition-all ${
                  filters.status.includes(s)
                    ? s === 'sold'
                      ? 'bg-[var(--red)] text-gray-200 border-[var(--red)]'
                      : 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                    : 'bg-transparent text-[var(--muted2)] border-[#252530]'
                }`}
              >
                {s === 'available' ? 'Available' : s === 'negotiations' ? 'Under Offer' : 'Sold'}
              </button>
            ))}
            <button
              onClick={() => applyFilters({ ...filters, newOnly: !filters.newOnly })}
              className={`px-3 py-1.5 rounded-[14px] text-xs font-semibold border whitespace-nowrap shrink-0 transition-all ${
                filters.newOnly
                  ? 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                  : 'bg-transparent text-[var(--muted2)] border-[#252530]'
              }`}
            >
              New 24h
            </button>
            <button
              onClick={() => applyFilters({ ...filters, priceDropOnly: !filters.priceDropOnly })}
              className={`px-3 py-1.5 rounded-[14px] text-xs font-semibold border whitespace-nowrap shrink-0 transition-all ${
                filters.priceDropOnly
                  ? 'bg-[var(--gold)] text-[#0a0b10] border-[var(--gold)]'
                  : 'bg-transparent text-[var(--muted2)] border-[#252530]'
              }`}
            >
              Price Drops
            </button>
            <select
              value={filters.sort}
              onChange={e => applyFilters({ ...filters, sort: e.target.value })}
              className="px-2.5 py-1.5 rounded-[14px] text-xs font-semibold border border-[#252530] bg-[var(--card)] text-[var(--text)] shrink-0 focus:outline-none focus:border-[var(--gold)]"
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

          {/* Result count */}
          <div className="px-4 pb-2 text-[13px] text-[var(--muted)] flex justify-between items-center">
            <span>Showing <strong className="text-[var(--text)]">{listings.length}</strong> of <strong className="text-[var(--text)]">{total}</strong></span>
          </div>

          {/* Listing grid */}
          <div className="px-4 flex flex-col gap-3 md:grid md:grid-cols-[repeat(auto-fill,minmax(340px,1fr))] md:gap-3.5">
            {listings.map(listing => (
              <ListingCard
                key={listing.global_id}
                listing={listing}
                isFavourite={favourites.has(listing.global_id)}
                onToggleFavourite={toggleFavourite}
                onClick={() => setSelectedListing(listing.global_id)}
              />
            ))}
          </div>

          {listings.length === 0 && !loading && (
            <div className="text-center py-16 px-5 text-[var(--muted)]">
              <h3 className="text-[var(--muted2)] mb-2 font-semibold">No properties match</h3>
              <p className="text-[13px]">Try adjusting your filters.</p>
            </div>
          )}

          {/* Load more sentinel */}
          <div ref={loadMoreRef} className="h-px" />
          {loadingMore && (
            <div className="flex justify-center py-6">
              <div className="w-6 h-6 border-2 border-[var(--card-border)] border-t-[var(--gold)] rounded-full animate-spin" />
            </div>
          )}
        </div>
      )}

      {/* Map View */}
      {view === 'map' && (
        <MapView
          listings={listings}
          onListingClick={id => setSelectedListing(id)}
        />
      )}

      {/* Favourites View */}
      {view === 'favs' && (
        <div>
          <div className="px-4 pt-3">
            <h1 className="text-[var(--gold)] text-lg font-bold">Saved Properties</h1>
          </div>
          <div className="px-4 pt-3 pb-2 text-[13px] text-[var(--muted)]">
            <strong className="text-[var(--text)]">{favListings.length}</strong> saved
          </div>
          {favListings.length > 0 ? (
            <div className="px-4 flex flex-col gap-3 md:grid md:grid-cols-[repeat(auto-fill,minmax(340px,1fr))] md:gap-3.5">
              {favListings.map(listing => (
                <ListingCard
                  key={listing.global_id}
                  listing={listing}
                  isFavourite={true}
                  onToggleFavourite={toggleFavourite}
                  onClick={() => setSelectedListing(listing.global_id)}
                />
              ))}
            </div>
          ) : (
            <div className="text-center py-16 px-5 text-[var(--muted)]">
              <h3 className="text-[var(--muted2)] mb-2 font-semibold">No saved properties</h3>
              <p className="text-[13px]">Tap the heart on any listing to save it here.</p>
            </div>
          )}
        </div>
      )}

      {/* Bottom Nav */}
      <BottomNav
        view={view}
        onViewChange={setView}
        favCount={favourites.size}
        filterCount={activeFilterCount}
        onFilterClick={() => setFiltersOpen(true)}
      />

      {/* Filter Drawer */}
      <Filters
        open={filtersOpen}
        filters={filters}
        onClose={() => setFiltersOpen(false)}
        onApply={(f) => {
          applyFilters(f)
          setFiltersOpen(false)
        }}
        onReset={() => {
          applyFilters(defaultFilters)
          setFiltersOpen(false)
        }}
      />

      {/* Listing Modal */}
      {selectedListing !== null && (
        <ListingModal
          listingId={selectedListing}
          isFavourite={favourites.has(selectedListing)}
          onToggleFavourite={toggleFavourite}
          onClose={() => setSelectedListing(null)}
          onListingClick={id => setSelectedListing(id)}
        />
      )}
    </div>
  )
}
