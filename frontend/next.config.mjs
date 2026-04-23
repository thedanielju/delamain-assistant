/** @type {import('next').NextConfig} */
const devApiProxy = process.env.DELAMAIN_DEV_API_PROXY

const nextConfig = {
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
  devIndicators: false,
  async rewrites() {
    if (!devApiProxy) return []
    return [
      {
        source: '/api/:path*',
        destination: `${devApiProxy.replace(/\/$/, '')}/api/:path*`,
      },
    ]
  },
}

export default nextConfig
