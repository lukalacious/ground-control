export type ErfpachtStatus = 'freehold' | 'bought_off' | 'perpetual' | 'fixed_term' | 'unknown'

export interface ErfpachtInfo {
  status: ErfpachtStatus
  label: string
  amount: string | null
  color: 'green' | 'amber' | 'red' | 'gray'
}

export function parseErfpacht(erfpacht: string | null): ErfpachtInfo {
  if (!erfpacht) {
    return { status: 'unknown', label: 'Unknown', amount: null, color: 'gray' }
  }

  const lower = erfpacht.toLowerCase()

  if (lower.includes('eigen grond') || lower.includes('vol eigendom')) {
    return { status: 'freehold', label: 'Freehold', amount: null, color: 'green' }
  }

  if (lower.includes('afgekocht') || lower.includes('afgelost')) {
    return { status: 'bought_off', label: 'Bought Off', amount: null, color: 'green' }
  }

  // Extract amount if present
  const amountMatch = erfpacht.match(/€\s*([\d.,]+)/i) || erfpacht.match(/([\d.,]+)\s*(?:per|p\/)/i)
  const amount = amountMatch ? `€${amountMatch[1]}` : null

  if (lower.includes('eeuwigdurend') || lower.includes('perpetual')) {
    return {
      status: 'perpetual',
      label: amount ? `Perpetual ${amount}/yr` : 'Perpetual',
      amount,
      color: 'amber',
    }
  }

  if (lower.includes('erfpacht') || lower.includes('tijdelijk') || lower.includes('lease')) {
    return {
      status: 'fixed_term',
      label: amount ? `Leasehold ${amount}/yr` : 'Leasehold',
      amount,
      color: 'red',
    }
  }

  return { status: 'unknown', label: 'Unknown', amount: null, color: 'gray' }
}
