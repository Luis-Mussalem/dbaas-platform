import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Build "standalone": empacota só o necessário (server.js + deps traçadas) numa
  // imagem Docker mínima, sem copiar node_modules inteiro. Ver frontend/Dockerfile.
  output: "standalone",
};

export default nextConfig;
