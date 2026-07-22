# syntax=docker/dockerfile:1

# =============================================================================
# Stage 1 — deps: instala as dependências com o lockfile (cache estável).
# =============================================================================
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


# =============================================================================
# Stage 2 — builder: compila o Next em modo standalone.
# NEXT_PUBLIC_* é baked no bundle do cliente em build time — por isso são ARGs.
# NEXT_PUBLIC_API_URL: o navegador (no host) fala com o backend em localhost:8001.
# NEXT_PUBLIC_DEMO_MODE: liga a faixa "Sobre esta demo" (default: portfólio = on).
# =============================================================================
FROM node:20-slim AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL=http://localhost:8001/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_DEMO_MODE=true
ENV NEXT_PUBLIC_DEMO_MODE=$NEXT_PUBLIC_DEMO_MODE
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build


# =============================================================================
# Stage 3 — runner: imagem final mínima que roda o server standalone.
# =============================================================================
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Usuário não-root (defesa em profundidade).
RUN useradd --create-home --uid 10001 nextjs

# O output standalone traz server.js + só as deps traçadas; estáticos e /public
# são copiados à parte (o standalone não os inclui).
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
