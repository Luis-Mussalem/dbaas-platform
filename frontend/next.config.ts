import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const nextConfig: NextConfig = {
  // Build "standalone": empacota só o necessário (server.js + deps traçadas) numa
  // imagem Docker mínima, sem copiar node_modules inteiro. Ver frontend/Dockerfile.
  output: "standalone",
};

// Aponta o Next para i18n/request.ts (locale por cookie, sem i18n routing).
export default createNextIntlPlugin()(nextConfig);
