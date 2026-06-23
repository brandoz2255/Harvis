# Vendored open-notebook Next.js frontend, served inside Harvis under /onb.
# Talks to the Harvis backend's onb_compat facade (/onb-api) via Next rewrites.
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Baked: API base = /onb → axios baseURL /onb/api → Next rewrite → backend /onb-api/*
ENV NEXT_PUBLIC_API_URL=/onb
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=8502
ENV HOSTNAME=0.0.0.0
# Next standalone output + static assets + public.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 8502
CMD ["node", "server.js"]
