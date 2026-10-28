import type { NextConfig } from 'next';
const config: NextConfig = {
  devIndicators: false,
  async rewrites() {return [{source:'/api/demo/:path*',destination:'http://127.0.0.1:8008/:path*'}];},
};
export default config;
