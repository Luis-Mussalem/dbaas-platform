# syntax=docker/dockerfile:1

# =============================================================================
# Stage 1 — deps: installs dependencies using the lockfile (stable cache).
# =============================================================================
FROM node:20-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


# =============================================================================
# Stage 2 — builder: compiles Next in standalone mode.
# NEXT_PUBLIC_* is baked into the client bundle at build time — hence the ARGs.
# NEXT_PUBLIC_API_URL: the browser (on the host) talks to the backend at localhost:8001.
# NEXT_PUBLIC_DEMO_MODE: turns on the "About this demo" banner (default: portfolio = on).
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
# Stage 3 — runner: minimal final image that runs the standalone server.
# =============================================================================
FROM node:20-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user (defense in depth).
RUN useradd --create-home --uid 10001 nextjs

# The standalone output brings server.js + only the traced deps; static assets and /public
# are copied separately (the standalone output doesn't include them).
COPY --from=builder --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nextjs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nextjs /app/public ./public

USER nextjs
EXPOSE 3000

CMD ["node", "server.js"]
