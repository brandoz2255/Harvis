# 1. Install dependencies
FROM node:20-alpine AS deps
WORKDIR /app

COPY package.json package-lock.json* pnpm-lock.yaml* ./

RUN \
  if [ -f package-lock.json ]; then npm ci; \
  elif [ -f pnpm-lock.yaml ]; then \
    npm install -g pnpm && pnpm install --frozen-lockfile; \
  else npm install; fi

# 2. Build app
FROM node:20-alpine AS builder
WORKDIR /app

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# 3. Run app
FROM node:20-alpine AS runner
WORKDIR /app

# Optional: reduce image size
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Copy from builder
COPY --from=builder /app/.next .next
COPY --from=builder /app/public ./public
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json
# updated

EXPOSE 3000

CMD ["npm", "run", "start", "--", "-p", "3000"]

