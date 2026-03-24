'use client'

interface BottomNavProps {
  view: 'list' | 'map' | 'favs'
  onViewChange: (view: 'list' | 'map' | 'favs') => void
  favCount: number
  filterCount: number
  onFilterClick: () => void
}

export default function BottomNav({ view, onViewChange, favCount, filterCount, onFilterClick }: BottomNavProps) {
  const navClass = (v: string) =>
    `flex-1 flex flex-col md:flex-row items-center justify-center gap-0.5 md:gap-1.5 text-[10px] md:text-[13px] font-semibold cursor-pointer border-none bg-none relative transition-colors ${
      view === v ? 'text-[var(--gold)]' : 'text-[var(--muted)]'
    }`

  return (
    <nav className="fixed bottom-0 md:bottom-auto md:top-0 left-0 right-0 h-[calc(var(--nav-h)+var(--safe-b))] md:h-[52px] pb-[var(--safe-b)] md:pb-0 bg-[#0c0d12] border-t md:border-t-0 md:border-b border-[var(--card-border)] flex z-[900]">
      <button className={navClass('list')} onClick={() => onViewChange('list')}>
        <svg className="w-[22px] h-[22px] md:w-[18px] md:h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <rect x="3" y="3" width="7" height="7" rx="1" />
          <rect x="14" y="3" width="7" height="7" rx="1" />
          <rect x="3" y="14" width="7" height="7" rx="1" />
          <rect x="14" y="14" width="7" height="7" rx="1" />
        </svg>
        <span>List</span>
      </button>
      <button className={navClass('map')} onClick={() => onViewChange('map')}>
        <svg className="w-[22px] h-[22px] md:w-[18px] md:h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M1 6v16l7-4 8 4 7-4V2l-7 4-8-4-7 4z" />
          <path d="M8 2v16" />
          <path d="M16 6v16" />
        </svg>
        <span>Map</span>
      </button>
      <button className={navClass('favs')} onClick={() => onViewChange('favs')}>
        <svg className="w-[22px] h-[22px] md:w-[18px] md:h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M20.84 4.61a5.5 5.5 0 00-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 00-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 000-7.78z" />
        </svg>
        <span>Saved</span>
        {favCount > 0 && (
          <span className="absolute top-1 right-[calc(50%-18px)] bg-[var(--gold)] text-[#0a0b10] text-[9px] font-bold min-w-[16px] h-4 rounded-full px-1 flex items-center justify-center">
            {favCount}
          </span>
        )}
      </button>
      <button
        className={`flex-1 flex flex-col md:flex-row items-center justify-center gap-0.5 md:gap-1.5 text-[10px] md:text-[13px] font-semibold cursor-pointer border-none bg-none relative transition-colors text-[var(--muted)]`}
        onClick={onFilterClick}
      >
        <svg className="w-[22px] h-[22px] md:w-[18px] md:h-[18px]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <line x1="4" y1="21" x2="4" y2="14" />
          <line x1="4" y1="10" x2="4" y2="3" />
          <line x1="12" y1="21" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12" y2="3" />
          <line x1="20" y1="21" x2="20" y2="16" />
          <line x1="20" y1="12" x2="20" y2="3" />
          <line x1="1" y1="14" x2="7" y2="14" />
          <line x1="9" y1="8" x2="15" y2="8" />
          <line x1="17" y1="16" x2="23" y2="16" />
        </svg>
        <span>Filters</span>
        {filterCount > 0 && (
          <span className="absolute top-1 right-[calc(50%-18px)] bg-[var(--gold)] text-[#0a0b10] text-[9px] font-bold min-w-[16px] h-4 rounded-full px-1 flex items-center justify-center">
            {filterCount}
          </span>
        )}
      </button>
    </nav>
  )
}
