'use client'

import { parseErfpacht } from '@/app/lib/erfpacht'

interface ErfpachtBadgeProps {
  erfpacht: string | null
  compact?: boolean
}

export default function ErfpachtBadge({ erfpacht, compact = false }: ErfpachtBadgeProps) {
  const info = parseErfpacht(erfpacht)

  if (info.status === 'unknown' && compact) return null

  const colorMap = {
    green: 'bg-[rgba(106,173,122,0.15)] text-[var(--green)] border-[rgba(106,173,122,0.3)]',
    amber: 'bg-[rgba(196,154,108,0.15)] text-[var(--gold)] border-[rgba(196,154,108,0.3)]',
    red: 'bg-[rgba(122,48,48,0.15)] text-[#c05050] border-[rgba(122,48,48,0.3)]',
    gray: 'bg-[rgba(90,86,80,0.15)] text-[var(--muted)] border-[rgba(90,86,80,0.3)]',
  }

  return (
    <span
      className={`inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold border ${colorMap[info.color]} ${compact ? '' : 'text-[11px] px-2 py-1'}`}
    >
      {info.label}
    </span>
  )
}
