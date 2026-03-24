'use client'

import { useState, useEffect, useCallback, useRef } from 'react'

interface LightboxProps {
  photos: string[]
  initialIndex: number
  onClose: () => void
}

export default function Lightbox({ photos, initialIndex, onClose }: LightboxProps) {
  const [index, setIndex] = useState(initialIndex)
  const [scale, setScale] = useState(1)
  const touchStartRef = useRef<{ x: number; y: number; dist: number | null }>({ x: 0, y: 0, dist: null })

  const goTo = useCallback((i: number) => {
    setIndex(Math.max(0, Math.min(photos.length - 1, i)))
    setScale(1)
  }, [photos.length])

  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowLeft') goTo(index - 1)
      if (e.key === 'ArrowRight') goTo(index + 1)
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [index, goTo, onClose])

  const handleTouchStart = (e: React.TouchEvent) => {
    if (e.touches.length === 1) {
      touchStartRef.current = { x: e.touches[0].clientX, y: e.touches[0].clientY, dist: null }
    } else if (e.touches.length === 2) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      )
      touchStartRef.current.dist = dist
    }
  }

  const handleTouchMove = (e: React.TouchEvent) => {
    if (e.touches.length === 2 && touchStartRef.current.dist) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY
      )
      const newScale = Math.max(1, Math.min(4, scale * (dist / touchStartRef.current.dist)))
      setScale(newScale)
      touchStartRef.current.dist = dist
    }
  }

  const handleTouchEnd = (e: React.TouchEvent) => {
    if (e.changedTouches.length === 1 && !touchStartRef.current.dist) {
      const diff = e.changedTouches[0].clientX - touchStartRef.current.x
      if (Math.abs(diff) > 60 && scale <= 1) {
        goTo(diff > 0 ? index - 1 : index + 1)
      }
    }
    touchStartRef.current.dist = null
  }

  return (
    <div
      className="fixed inset-0 bg-black z-[2000] flex flex-col"
      onClick={onClose}
    >
      {/* Top bar */}
      <div className="flex items-center justify-between px-4 py-3 z-10">
        <span className="text-white/70 text-sm font-semibold">{index + 1}/{photos.length}</span>
        <button
          className="text-white/70 text-2xl w-10 h-10 flex items-center justify-center"
          onClick={onClose}
        >
          ×
        </button>
      </div>

      {/* Image */}
      <div
        className="flex-1 flex items-center justify-center overflow-hidden"
        onClick={e => e.stopPropagation()}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={photos[index]}
          alt=""
          referrerPolicy="no-referrer"
          className="max-w-full max-h-full object-contain transition-transform duration-100"
          style={{ transform: `scale(${scale})` }}
          draggable={false}
        />
      </div>

      {/* Nav arrows (desktop) */}
      {index > 0 && (
        <button
          className="hidden md:flex absolute left-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/50 items-center justify-center text-white text-xl"
          onClick={e => { e.stopPropagation(); goTo(index - 1) }}
        >
          ‹
        </button>
      )}
      {index < photos.length - 1 && (
        <button
          className="hidden md:flex absolute right-4 top-1/2 -translate-y-1/2 w-10 h-10 rounded-full bg-black/50 items-center justify-center text-white text-xl"
          onClick={e => { e.stopPropagation(); goTo(index + 1) }}
        >
          ›
        </button>
      )}
    </div>
  )
}
