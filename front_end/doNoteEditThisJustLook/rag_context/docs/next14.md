Next.js 14 Overview

Last updated 2025-07-07
Table of Contents

    Why Next 14?

    New Core Features
    2.1 App Router (/app)
    2.2 React Server Components (RSC)
    2.3 Server Actions
    2.4 Partial Prerendering (PPR)
    2.5 Turbopack Stable
    2.6 Edge-First Runtime

    Quality-of-Life Improvements

    Breaking Changes & Migration Guide

    FAQ

    Resources

Why Next14?

Next 14 focuses on performance-at-scale and a dramatically simpler DX for full-stack React. Production benchmarks show:
Metric	Next 13.5	Next 14	Δ
TTI (ms, median)	1350 ms	890 ms	-34%
Server build time (large repo, s)	72 s	19 s	-73%
Cold start (AWS Lambda Edge, ms)	380 ms	115 ms	-70%
Bundle size (hydrated JS, kB gzip)	178 kB	92 kB	-48%

(Measurements from the reference e-commerce app, 2025-05.)
New Core Features
2.1 App Router <a id="21-app-router"></a>

    /app/** is now the only recommended routing layer.

    File-system-based nested layouts, streaming, and route groups ((marketing)/, (dashboard)/) remain.

    Co-located loading.tsx, error.tsx, not-found.tsx, and route middleware continue unchanged.

    Client components are opt-in via 'use client'; everything else is a server component by default.

2.2 React Server Components (RSC)

    Ships with React 19 RC baked in.

    No double-fetch: server functions run exactly once per request.

    Automatic flight-data caching with fetch('...', { next: { revalidate } }).

    Streaming boundaries controlled with <Suspense /> plus the new <Defer /> tag.

2.3 Server Actions

    Replace API routes for most mutations:

    // app/profile/[id]/action.ts
    "use server";
    import { z } from "zod";
    import { db } from "@/lib/db";

    export async function updateProfile(prev: any, formData: FormData) {
      const schema = z.object({ name: z.string().min(2) });
      const input = schema.parse({
        name: formData.get("name"),
      });
      await db.user.update({ where: { id: prev.id }, data: input });
      return { success: true };
    }

    Optimistic UI baked in via the new useFormState helper.

2.4 Partial Prerendering (PPR)

    Mark sub-trees with export const dynamic = "auto" to let Next prerender the shell at build-time and defer data-heavy parts to runtime.

    Dramatically lowers FCP on high-traffic marketing pages.

2.5 Turbopack Stable

    Rust-powered bundler now production-ready.

    10–20× faster incremental rebuilds than Webpack 5.

    Config lives in turbopack.config.ts. Common tweaks provided in performance_tips.md.

2.6 Edge-First Runtime

    runtime = "edge" in route segment configs now targets V8 isolates by default (Vercel/Cloudflare/Deno).

    Streaming supported; binary Responses up to 4 MiB.

Quality-of-Life Improvements

    next dev --turbo mirrors production HMR for RSC.

    Built-in Sentry source-map upload when SENTRY_DSN env var is present.

    Font fallbacks auto-injected: next/font/google?display=swap.

    Type-safe env access with process.env.NEXT_PUBLIC_* autocompletion (TS 5.5).

Breaking Changes & Migration Guide

    Webpack 5→Turbopack: custom webpack config is ignored. Migrate loaders/plugins or ship them as turbopack.module.rules.

    pages/ dir is deprecated in new projects; legacy support removed in v15.

    next.config.js → next.config.mjs (ESM default).

    Image component: unoptimized prop removed; use priority & proper sizes.

    Middleware must export a matcher array, not regex strings.

See ./migration/13-to-14.md for step-by-step commands.
FAQ
<details> <summary>Can I still deploy to Netlify?</summary>

Yes. Install @netlify/next v6 which adds Turbopack support, or pin to Webpack via experimental.turbo = false.
</details> <details> <summary>What Node.js version is required?</summary> Node 18.19+ (LTS) or Node 20.7+. Turbopack uses the Bun hashing algorithm built into Node 18.18+. </details>
Resources

    Release blog: “Next.js 14 — Fast by Default”

    RFCs: [#420 Server Actions], [#414 Partial Prerendering], [#399 Edge Runtime]

    Conference talk (React Summit 2025): Streaming All the Things.

docs/project_style_guide.md

Project Style Guide

    Goal: Enforce a consistent codebase that scales to 50+ contributors without bikeshedding.

1. Repository Layout

/
├─ app/                # App router tree (server-first)
│  ├─ (public)/        # Marketing routes, static-heavy
│  └─ (dashboard)/     # Auth-gated UI
├─ components/         # Reusable UI (client & server)
│  └─ ui/              # “shadcn/ui” wrapped primitives
├─ lib/                # Framework-agnostic utilities
├─ db/                 # Drizzle schema + migrations
├─ styles/             # Global CSS + tailwind layers
├─ scripts/            # One-off CLIs (`ts-node`/zx)
├─ tests/              # Vitest + React Testing Library
└─ .github/            # CI, workflows, ISSUE_TEMPLATE

Naming Conventions
Area	Rule	Example
Files	camelCase for React, kebab for misc	userAvatar.tsx, sentry-loader.ts
Components	PascalCase dirs + files	AvatarGroup/AvatarGroup.tsx
CSS vars	--color-<context>-<scale>	--color-primary-600
Env vars	NEXT_PUBLIC_ for browser needed	NEXT_PUBLIC_SUPABASE_URL
Git branches	type/short-slug	feat/payments-upgrades
2. Linting & Formatting
Tool	Config file	Notes
ESLint	.eslintrc.json	next/core-web-vitals, unicorn, no-only-tests
Prettier	.prettierrc.json	Width = 100, semi = true, singleQuote = true
Stylelint	.stylelintrc.json	Tailwind plugin, BEM rules off
Husky	.husky/	Pre-commit: pnpm lint:fatal

Run all locally:

pnpm lint         # eslint + stylelint
pnpm format       # prettier write

CI rejects anything with error-level offenses.
3. Commit Messages (Conventional Commits)

<type>(scope): <subject>

body (optional, 72-char lines)

BREAKING CHANGE: ...

Valid types: feat, fix, docs, refactor, perf, test, ci, build, chore.
4. TypeScript Strictness

    strict: true, noUncheckedIndexedAccess: true, exactOptionalPropertyTypes: true.

    Never use any; fall back to unknown + refinement.

    Shared types live in /types/*.ts.

5. CSS/Tailwind

    Prefer utility-first. Extract a component class only after ≥ 3 duplications.

    Stacking context: every new z-index must appear in /styles/zindex.css.

    Dark mode via class='dark' (no OS media query).

6. Testing
Scope	Tool	Guideline
Unit	Vitest	Should mock network & db
Component	RTL + JSDOM	Cover ARIA roles, keyboard paths
E2E	Cypress 14	Run per PR with stubbed payments

Coverage target: 80 % lines, 100 % on critical business logic (/app/(dashboard)/billing).
7. Documentation

    MDX for long-form docs under /docs/**.

    Every exported component in /components/ui/** must have /** @component */ JSDoc and Storybook story.





Additional Best Practices

    Edge Functions run with a read-only filesystem; still validate payload sizes (body.size < 1 MiB).

    Database uses least-privileged role (app_user) with Row Level Security (Postgres).

    Logging strips PII by default (pino redaction config).

    Sentry sample rate ≤ 10 % for non-errors to avoid leakage.

    Third-Party Scripts must pass security-review.md and be hash-pinned in CSP.

docs/accessibility.md

Accessibility (A11y) Guidelines
1. Principles

    Perceivable – content visible to all senses.

    Operable – fully keyboard navigable.

    Understandable – predictable UI.

    Robust – works with assistive tech.

2. ARIA & Semantics
Use…	Instead of…	Notes
<button>	<div onClick>	Native focus + space/enter keys
role="dialog" + aria-modal="true"	Custom modal div	Provided by @radix-ui/react-dialog
aria-live="polite" regions	JS alerts only	For form error summaries
Landmark Order

    header

    nav

    main

    aside

    footer

3. Keyboard Navigation

    Tabbing order follows DOM order.

    Trap focus inside modals – see examples/components/Modal.tsx.

    Use skip links:

    <a href="#main" className="sr-only focus:not-sr-only">
      Skip to content
    </a>

4. Color & Contrast
WCAG Level	Text / BG contrast
AA	4.5:1 normal, 3:1 large
AAA	7:1 normal

Run pnpm a11y:colors (custom script) to test Tailwind palette.
5. Motion & Animation

    Respect prefers-reduced-motion.

    Avoid hue-shifted flashing > 3 Hz.

6. Testing
Tool	When
axe-playwright	per commit
VoiceOver / NVDA	monthly audit

Minimum score > 97 on Lighthouse A11y.

docs/performance_tips.md

Performance Tips
1. Images

    Use <Image> with sizes + priority for LCP hero.

    blurDataURL from @vercel/og for instant placeholder.

    Enable AVIF: images: { formats: ["image/avif", "image/webp"] }.

2. Code Splitting

    import("...") dynamic for heavy libs (charting, editor).

    Mark as client only with:

    const Monaco = dynamic(() => import("./Monaco"), { ssr: false });

3. Turbopack Tweaks

// turbopack.config.ts
export default {
  optimize: {
    // Always on in prod, but enable locally to mirror
    minify: true,
    moduleDeduplication: "node_modules",
  },
};

4. Resource-Intensive RSC

    Keep individual RSC payloads < 200 kB JSON.

    Cache with revalidate: 60 or revalidate: tag("product").

5. Edge Caching & PPR

    Combine dynamic = "auto" + revalidateTag("product") for stock updates without full re-render.

    Use headers() to add CDN-Cache-Control: public, max-age=31536000, stale-while-revalidate=60.

6. Fonts

    Self-host via next/font/local to avoid third-party latency.

    Preload variable fonts only:

    import { Inter } from "next/font/google";
    const inter = Inter({ subsets: ["latin"], display: "swap" });

7. RUM & Monitoring
Metric	Tool	Target
LCP, FID, CLS	@vercel/speed-insights	LCP < 2 s
TTFB	Sentry + custom filter	< 200 ms EU/US
Error Rate	Sentry	< 0.1 %