/** Next.js config: /api/backend/* is proxied to the FastAPI backend (staff page, booking, visitor). */
const backend = process.env.MIRA_BACKEND_URL || `http://127.0.0.1:${process.env.BACKEND_PORT || "8123"}`;

const nextConfig = {
  async rewrites() {
    return [{ source: "/api/backend/:path*", destination: `${backend}/api/:path*` }];
  },
};

export default nextConfig;
