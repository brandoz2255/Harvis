# 1. Install dependencies
FROM node:20-alpine AS deps
WORKDIR /app

# Copy package files
COPY package.json package-lock.json* pnpm-lock.yaml* ./

# Install dependencies with optimizations
# Remove corrupted lock file and install fresh
RUN rm -f package-lock.json && \
    npm install --only=production --legacy-peer-deps && \
    npm cache clean --force

# Install dev dependencies in separate stage for building
FROM node:20-alpine AS deps-dev
WORKDIR /app

COPY package.json package-lock.json* pnpm-lock.yaml* ./

# Remove corrupted lock file and install all dependencies for building
RUN rm -f package-lock.json && \
    npm install --legacy-peer-deps && \
    npm cache clean --force

# 2. Build app
FROM node:20-alpine AS builder
WORKDIR /app

# Cache-busting ARG - change this value to force a complete rebuild
ARG BUILD_TIMESTAMP=unknown
ARG GIT_COMMIT=unknown

# Copy dev dependencies for building
COPY --from=deps-dev /app/node_modules ./node_modules

# Echo build info for debugging
RUN echo "Building frontend at ${BUILD_TIMESTAMP} commit ${GIT_COMMIT}"

# Copy source files individually for better cache invalidation
# This ensures any source code change invalidates the build
COPY app ./app
COPY components ./components
COPY hooks ./hooks
COPY lib ./lib
COPY stores ./stores
COPY types ./types
COPY public ./public
COPY *.json *.ts *.js *.mjs ./

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
