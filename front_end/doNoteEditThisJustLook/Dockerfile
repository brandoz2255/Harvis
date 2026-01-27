# 1. Install dependencies
FROM node:20-alpine AS deps
WORKDIR /app

# Copy package files
COPY package.json package-lock.json* pnpm-lock.yaml* ./

# Install dependencies with optimizations
RUN \
  if [ -f package-lock.json ]; then \
    npm ci --only=production && \
    npm cache clean --force; \
  elif [ -f pnpm-lock.yaml ]; then \
    npm install -g pnpm && \
    pnpm install --frozen-lockfile --prod && \
    pnpm store prune; \
  else \
    npm install --only=production && \
    npm cache clean --force; \
  fi

# Install dev dependencies in separate stage for building
FROM node:20-alpine AS deps-dev
WORKDIR /app

COPY package.json package-lock.json* pnpm-lock.yaml* ./

RUN \
  if [ -f package-lock.json ]; then \
    npm ci && \
    npm cache clean --force; \
  elif [ -f pnpm-lock.yaml ]; then \
    npm install -g pnpm && \
    pnpm install --frozen-lockfile && \
    pnpm store prune; \
  else \
    npm install && \
    npm cache clean --force; \
  fi

# 2. Build app
FROM node:20-alpine AS builder
WORKDIR /app

# Copy dev dependencies for building
COPY --from=deps-dev /app/node_modules ./node_modules
COPY . .

# Build the application
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build

# 3. Run app
FROM node:20-alpine AS runner
WORKDIR /app

# Create non-root user for security
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# Set environment variables
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

# Copy only production dependencies
COPY --from=deps /app/node_modules ./node_modules

# Copy built application
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

# Copy package.json for start script
COPY --from=builder /app/package.json ./package.json

# Set permissions for .next directory (already exists from standalone build)
RUN chown -R nextjs:nodejs .next

# Switch to non-root user
USER nextjs

EXPOSE 3000

ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

# Use node directly for better performance
CMD ["node", "server.js"]

