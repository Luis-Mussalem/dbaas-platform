import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const nextConfig: NextConfig = {
  // "standalone" build: bundles only what's needed (server.js + traced deps) into a
  // minimal Docker image, without copying all of node_modules. See frontend/Dockerfile.
  output: "standalone",
};

// Points Next at i18n/request.ts (cookie-based locale, no i18n routing).
export default createNextIntlPlugin()(nextConfig);
