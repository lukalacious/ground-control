import { NextRequest } from 'next/server'
import { prisma } from '@/app/lib/prisma'

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ name: string }> }
) {
  const { name } = await params
  const decodedName = decodeURIComponent(name)

  const stats = await prisma.neighbourhoodStats.findFirst({
    where: { neighbourhood: decodedName },
    orderBy: { calculatedAt: 'desc' },
  })

  if (!stats) {
    return Response.json({ error: 'Neighbourhood not found' }, { status: 404 })
  }

  // Get listings in this neighbourhood for percentile calculations
  const listings = await prisma.listing.findMany({
    where: {
      neighbourhood: decodedName,
      priceNumeric: { gt: 0 },
      livingArea: { gt: 0 },
    },
    select: { priceNumeric: true, livingArea: true },
  })

  const pricesM2 = listings
    .map(l => (l.priceNumeric ?? 0) / (l.livingArea ?? 1))
    .sort((a, b) => a - b)

  const percentile = (arr: number[], p: number) => {
    const idx = Math.ceil((p / 100) * arr.length) - 1
    return arr[Math.max(0, idx)] ?? null
  }

  return Response.json({
    neighbourhood: stats.neighbourhood,
    avgPriceM2: stats.avgPriceM2,
    medianPrice: stats.medianPrice,
    listingCount: stats.listingCount,
    percentiles: pricesM2.length > 0
      ? {
          p10: Math.round(percentile(pricesM2, 10)!),
          p25: Math.round(percentile(pricesM2, 25)!),
          p50: Math.round(percentile(pricesM2, 50)!),
          p75: Math.round(percentile(pricesM2, 75)!),
          p90: Math.round(percentile(pricesM2, 90)!),
        }
      : null,
  })
}
