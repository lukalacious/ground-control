import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  images: {
    remotePatterns: [
      {
        protocol: 'https',
        hostname: 'cloud.funda.nl',
      },
      {
        protocol: 'https',
        hostname: '*.funda.nl',
      },
    ],
  },
}

export default nextConfig
