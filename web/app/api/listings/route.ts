import { NextRequest } from 'next/server'
import { prisma } from '@/app/lib/prisma'
import { Prisma } from '@prisma/client'
import { scoreListing } from '@/app/lib/scoring'

export async function GET(request: NextRequest) {
  const sp = request.nextUrl.searchParams

  const page = Math.max(1, parseInt(sp.get('page') || '1'))
  const limit = Math.min(100, Math.max(1, parseInt(sp.get('limit') || '50')))
  const sort = sp.get('sort') || 'score'
  const minPrice = sp.get('minPrice') ? parseInt(sp.get('minPrice')!) : undefined
  const maxPrice = sp.get('maxPrice') ? parseInt(sp.get('maxPrice')!) : undefined
  const minArea = sp.get('minArea') ? parseInt(sp.get('minArea')!) : undefined
  const maxArea = sp.get('maxArea') ? parseInt(sp.get('maxArea')!) : undefined
  const bedrooms = sp.get('bedrooms') ? parseInt(sp.get('bedrooms')!) : undefined
  const neighbourhoods = sp.get('neighbourhood')?.split(',').filter(Boolean)
  const status = sp.get('status')
  const erfpachtStatus = sp.get('erfpachtStatus')
  const search = sp.get('search')
  const newOnly = sp.get('newOnly') === 'true'
  const priceDropOnly = sp.get('priceDropOnly') === 'true'

  // Build where clause
  const where: Prisma.ListingWhereInput = {
    priceNumeric: { gt: 0 },
    livingArea: { gt: 0 },
    detailUrl: { not: { contains: 'parkeergelegenheid' } },
  }

  if (minPrice || maxPrice) {
    where.priceNumeric = {
      ...((where.priceNumeric as Prisma.IntNullableFilter) || {}),
      ...(minPrice ? { gte: minPrice } : {}),
      ...(maxPrice ? { lte: maxPrice } : {}),
    }
  }

  if (minArea || maxArea) {
    where.livingArea = {
      ...((where.livingArea as Prisma.IntNullableFilter) || {}),
      ...(minArea ? { gte: minArea } : {}),
      ...(maxArea ? { lte: maxArea } : {}),
    }
  }

  if (bedrooms) {
    where.bedrooms = { gte: bedrooms }
  }

  if (neighbourhoods && neighbourhoods.length > 0) {
    where.neighbourhood = { in: neighbourhoods }
  }

  if (status) {
    const statuses = status.split(',').filter(Boolean)
    where.availabilityStatus = { in: statuses }
  }

  if (erfpachtStatus) {
    if (erfpachtStatus === 'freehold') {
      where.OR = [
        { erfpacht: { contains: 'Eigen grond' } },
        { erfpacht: { contains: 'eigen grond' } },
        { erfpacht: { contains: 'Afgekocht' } },
        { erfpacht: { contains: 'afgekocht' } },
      ]
    } else if (erfpachtStatus === 'leasehold') {
      where.erfpacht = { not: null }
      where.NOT = [
        { erfpacht: { contains: 'Eigen grond' } },
      ]
    }
  }

  if (search) {
    where.OR = [
      { address: { contains: search, mode: 'insensitive' } },
      { postcode: { contains: search, mode: 'insensitive' } },
      { neighbourhood: { contains: search, mode: 'insensitive' } },
    ]
  }

  if (newOnly) {
    const yesterday = new Date(Date.now() - 86400000)
    where.firstSeen = { gte: yesterday }
  }

  if (priceDropOnly) {
    where.previousPrice = { not: null, gt: 0 }
  }

  // Get totals
  const total = await prisma.listing.count({ where })

  // Get neighbourhood stats for scoring
  const hoodStats = await prisma.neighbourhoodStats.findMany({
    orderBy: { calculatedAt: 'desc' },
    distinct: ['neighbourhood'],
  })
  const hoodMap = new Map(hoodStats.map(h => [h.neighbourhood, h.avgPriceM2]))

  const cityStats = await prisma.cityStats.findFirst({
    orderBy: { calculatedAt: 'desc' },
  })
  const cityAvgM2 = cityStats?.avgPriceM2 ?? null

  // Get listings — for score-based sorts, we need all listings to sort in-memory
  const dbSortable = ['price_asc', 'price_desc', 'newest', 'area']
  const useDbSort = dbSortable.includes(sort)

  let orderBy: Prisma.ListingOrderByWithRelationInput | undefined
  if (sort === 'price_asc') orderBy = { priceNumeric: 'asc' }
  else if (sort === 'price_desc') orderBy = { priceNumeric: 'desc' }
  else if (sort === 'newest') orderBy = { firstSeen: 'desc' }
  else if (sort === 'area') orderBy = { livingArea: 'desc' }

  let rawListings
  if (useDbSort) {
    rawListings = await prisma.listing.findMany({
      where,
      orderBy,
      skip: (page - 1) * limit,
      take: limit,
      include: { priceHistory: true },
    })
  } else {
    rawListings = await prisma.listing.findMany({
      where,
      include: { priceHistory: true },
    })
  }

  // Score and enrich
  const enriched = rawListings.map(listing => {
    const hoodAvg = listing.neighbourhood ? hoodMap.get(listing.neighbourhood) ?? null : null
    const scored = scoreListing(
      listing.priceNumeric ?? 0,
      listing.livingArea,
      hoodAvg,
      cityAvgM2,
      listing.firstSeen,
    )

    let photoUrls: string[] = []
    if (listing.photoUrls) {
      try {
        photoUrls = JSON.parse(listing.photoUrls)
      } catch {
        photoUrls = []
      }
    }

    return {
      ...listing,
      photoUrls,
      priceM2: scored.price_m2,
      score: scored.score,
      scoreDetails: scored.score_details,
      daysOnMarket: scored.days_on_market,
    }
  })

  // In-memory sorting for computed fields
  if (!useDbSort) {
    if (sort === 'score') enriched.sort((a, b) => b.score - a.score)
    else if (sort === 'price_m2') enriched.sort((a, b) => (a.priceM2 ?? 99999) - (b.priceM2 ?? 99999))
    else if (sort === 'days_on_market') enriched.sort((a, b) => b.daysOnMarket - a.daysOnMarket)
  }

  // Paginate if sorted in-memory
  const paginated = useDbSort ? enriched : enriched.slice((page - 1) * limit, page * limit)

  return Response.json({
    listings: paginated,
    total,
    page,
    pages: Math.ceil(total / limit),
  })
}
