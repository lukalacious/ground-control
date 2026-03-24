import { NextRequest } from 'next/server'
import { prisma } from '@/app/lib/prisma'
import { scoreListing } from '@/app/lib/scoring'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { id } = await params
  const globalId = parseInt(id)

  if (isNaN(globalId)) {
    return Response.json({ error: 'Invalid listing ID' }, { status: 400 })
  }

  const listing = await prisma.listing.findUnique({
    where: { globalId },
    include: { priceHistory: { orderBy: { recordedAt: 'desc' } } },
  })

  if (!listing) {
    return Response.json({ error: 'Listing not found' }, { status: 404 })
  }

  // Get neighbourhood stats
  const hoodStats = listing.neighbourhood
    ? await prisma.neighbourhoodStats.findFirst({
        where: { neighbourhood: listing.neighbourhood },
        orderBy: { calculatedAt: 'desc' },
      })
    : null

  const cityStats = await prisma.cityStats.findFirst({
    orderBy: { calculatedAt: 'desc' },
  })

  // Score
  const scored = scoreListing(
    listing.priceNumeric ?? 0,
    listing.livingArea,
    hoodStats?.avgPriceM2 ?? null,
    cityStats?.avgPriceM2 ?? null,
    listing.firstSeen,
  )

  // Parse photoUrls
  let photoUrls: string[] = []
  if (listing.photoUrls) {
    try {
      photoUrls = JSON.parse(listing.photoUrls)
    } catch {
      photoUrls = []
    }
  }

  // Find comparables: same neighbourhood, similar price/m2 and living area
  let comparables: Array<Record<string, unknown>> = []

  if (listing.neighbourhood && listing.livingArea && listing.priceNumeric) {
    const priceM2 = listing.priceNumeric / listing.livingArea
    const rawComps = await prisma.listing.findMany({
      where: {
        neighbourhood: listing.neighbourhood,
        globalId: { not: globalId },
        priceNumeric: { gt: 0 },
        livingArea: { gt: 0 },
        isActive: true,
      },
      take: 20,
    })

    const scoredComps = rawComps.map(c => {
      const cM2 = (c.priceNumeric ?? 0) / (c.livingArea ?? 1)
      const m2Diff = Math.abs(cM2 - priceM2) / priceM2
      const areaDiff = Math.abs((c.livingArea ?? 0) - listing.livingArea!) / listing.livingArea!
      return { ...c, similarity: m2Diff + areaDiff, priceM2: Math.round(cM2 * 10) / 10 }
    })

    scoredComps.sort((a, b) => a.similarity - b.similarity)
    comparables = scoredComps.slice(0, 5)
  }

  // Neighbourhood analytics
  const neighbourhoodAnalytics = listing.neighbourhood
    ? await prisma.neighbourhoodAnalytics.findUnique({
        where: { neighbourhood: listing.neighbourhood },
      })
    : null

  return Response.json({
    ...listing,
    photoUrls,
    priceM2: scored.price_m2,
    score: scored.score,
    scoreDetails: scored.score_details,
    daysOnMarket: scored.days_on_market,
    neighbourhoodAnalytics,
    comparables,
  })
}
