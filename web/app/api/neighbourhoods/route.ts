import { prisma } from '@/app/lib/prisma'

export async function GET() {
  const stats = await prisma.neighbourhoodStats.findMany({
    orderBy: { calculatedAt: 'desc' },
    distinct: ['neighbourhood'],
  })

  stats.sort((a, b) => (b.listingCount ?? 0) - (a.listingCount ?? 0))

  const neighbourhoods = stats.map(s => ({
    name: s.neighbourhood,
    listingCount: s.listingCount,
    avgPriceM2: s.avgPriceM2,
    medianPrice: s.medianPrice,
  }))

  return Response.json({ neighbourhoods })
}
