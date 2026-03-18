# Build Troubleshooting Guide

**Date**: 2025-10-30  
**Purpose**: Document build issues encountered during IDE AI implementation and solutions for future reference

## Issues Encountered & Solutions

### 1. Missing Module: `Can't resolve '../lib/ide-api'`

**Error:**
```
Module not found: Can't resolve '../lib/ide-api'
Import trace for requested module:
./app/ide/components/RightPanel.tsx
./app/ide/page.tsx
```

**Cause:**  
The `app/ide/lib/ide-api.ts` file was deleted or not created.

**Solution:**  
Create the missing file at the correct path:
```bash
touch front_end/jfrontend/app/ide/lib/ide-api.ts
```

Ensure it exports the required APIs:
- `IDECopilotAPI`
- `IDEChatAPI`
- `IDEDiffAPI`

### 2. Missing UI Component: `Can't resolve '@/components/ui/scroll-area'`

**Error:**
```
Module not found: Can't resolve '@/components/ui/scroll-area'
```

**Cause:**  
Used a UI component that doesn't exist in the project's component library.

**Solution:**  
Replace with standard HTML/React elements:
```tsx
// Before:
import { ScrollArea } from '@/components/ui/scroll-area'
<ScrollArea className="flex-1 p-4">...</ScrollArea>

// After:
<div className="flex-1 p-4 overflow-auto">...</div>
```

**Prevention:**  
- Always check if UI components exist before using them
- Use `grep -r "ScrollArea" front_end/jfrontend/components/ui/` to verify
- Prefer standard HTML elements with Tailwind CSS for simple cases

### 3. SSR Error: `ReferenceError: window is not defined`

**Error:**
```
ReferenceError: window is not defined
Error occurred prerendering page "/ide"
```

**Cause:**  
Next.js attempts to statically pre-render pages during build. Code using browser APIs (`window`, `localStorage`, etc.) fails during SSR.

**Root Issue:**  
- The `ide-api.ts` file accesses `localStorage` at the top level
- Monaco editor and other client-side libraries don't support SSR
- The `/ide` page is heavily client-interactive and should never be statically generated

**Solution (3-part fix):**

#### A. Guard `localStorage` access:
```typescript
// front_end/jfrontend/app/ide/lib/ide-api.ts
function getAuthToken(): string {
  if (typeof window === 'undefined') return ''
  try {
    return localStorage.getItem('access_token') || ''
  } catch {
    return ''
  }
}
```

#### B. Create a layout file to force dynamic rendering:
```typescript
// front_end/jfrontend/app/ide/layout.tsx
export const dynamic = 'force-dynamic'
export const revalidate = 0

export default function IDELayout({ children }: { children: React.ReactNode }) {
  return children
}
```

**Why this works:**
- `dynamic = 'force-dynamic'` must be in a **server component** (layout.tsx)
- Putting it in a client component (page.tsx with `"use client"`) has no effect
- Next.js respects this export from layout files and skips static generation

#### C. Ensure client component directive:
```typescript
// front_end/jfrontend/app/ide/page.tsx
"use client"  // First line

import React from "react"
// ... rest of imports
```

**Verification:**
After build, check the route report:
```bash
npm run build | grep "/ide"
```

Should show:
```
ƒ  /ide    881 kB    1.09 MB
```

The `ƒ (Dynamic)` indicator confirms server-rendered on demand, not statically generated.

## Build Process Best Practices

### Before Implementing New Features

1. **Check dependencies first:**
   ```bash
   # Verify UI components exist
   ls -la front_end/jfrontend/components/ui/
   
   # Check if similar features already exist
   grep -r "ScrollArea" front_end/jfrontend/
   ```

2. **Verify API file structure:**
   ```bash
   # Ensure lib directories exist
   mkdir -p front_end/jfrontend/app/ide/lib
   mkdir -p front_end/jfrontend/app/ide/components
   ```

3. **Test imports before full implementation:**
   ```tsx
   // Create a minimal test component
   import { Button } from '@/components/ui/button'  // Will this work?
   ```

### During Implementation

1. **Use browser-only code guards:**
   ```typescript
   // Always guard browser APIs
   if (typeof window !== 'undefined') {
     localStorage.setItem('key', 'value')
   }
   ```

2. **Lazy-load heavy client libraries:**
   ```typescript
   // For Monaco, Chart.js, etc.
   const MonacoEditor = dynamic(() => import('./MonacoEditor'), { ssr: false })
   ```

3. **Mark client-interactive routes as dynamic:**
   ```typescript
   // In layout.tsx (server component)
   export const dynamic = 'force-dynamic'
   ```

### After Implementation

1. **Run build before committing:**
   ```bash
   cd front_end/jfrontend
   npm run build
   ```

2. **Check for warnings:**
   ```bash
   npm run build 2>&1 | grep -i "warn\|error"
   ```

3. **Verify route rendering mode:**
   ```bash
   npm run build | grep -E "○|λ|ƒ"
   ```
   - `○ (Static)` - Statically generated at build time
   - `ƒ (Dynamic)` - Server-rendered on demand
   - `λ (SSR)` - Server-side rendered on each request

4. **Test production build locally:**
   ```bash
   npm run build && npm run start
   ```

## Common Build Errors Reference

### Module Resolution Errors

**Pattern:** `Can't resolve 'X'`

**Checklist:**
- [ ] Does the file exist at the specified path?
- [ ] Is the import path correct (relative vs absolute)?
- [ ] Is the file extension correct (.ts vs .tsx)?
- [ ] Does tsconfig.json have the correct path mappings?

**Fix:**
```bash
# Verify file exists
find front_end/jfrontend -name "ide-api.ts"

# Check import paths
grep -r "from '../lib/ide-api'" front_end/jfrontend/app/ide/
```

### SSR/Prerendering Errors

**Pattern:** `ReferenceError: X is not defined` during build

**Checklist:**
- [ ] Is `X` a browser-only API (window, document, localStorage)?
- [ ] Is the component/page properly marked as client-side (`"use client"`)?
- [ ] Does the route need `dynamic = 'force-dynamic'` in layout.tsx?
- [ ] Are third-party libraries (Monaco, etc.) SSR-compatible?

**Fix:**
```typescript
// Option 1: Guard the code
if (typeof window !== 'undefined') {
  // browser-only code
}

// Option 2: Lazy load
const ClientComponent = dynamic(() => import('./Client'), { ssr: false })

// Option 3: Force dynamic rendering (in layout.tsx)
export const dynamic = 'force-dynamic'
```

### Type Errors

**Pattern:** `Type 'X' is not assignable to type 'Y'`

**Checklist:**
- [ ] Are interface definitions up to date?
- [ ] Are optional properties marked with `?`?
- [ ] Are union types correct?
- [ ] Is `strict` mode in tsconfig.json causing issues?

**Fix:**
```typescript
// Add proper typing
interface Props {
  sessionId: string | null  // null is valid
  onClose?: () => void      // optional callback
}
```

## Automated Build Verification Script

Create `scripts/verify-build.sh`:

```bash
#!/bin/bash
set -e

echo "🔍 Verifying build prerequisites..."

# Check for required files
FILES=(
  "front_end/jfrontend/app/ide/lib/ide-api.ts"
  "front_end/jfrontend/app/ide/layout.tsx"
  "front_end/jfrontend/app/ide/page.tsx"
)

for file in "${FILES[@]}"; do
  if [ ! -f "$file" ]; then
    echo "❌ Missing: $file"
    exit 1
  fi
done

echo "✅ All required files present"

# Run build
echo "🏗️  Building frontend..."
cd front_end/jfrontend
npm run build

# Check for errors
if [ $? -ne 0 ]; then
  echo "❌ Build failed"
  exit 1
fi

echo "✅ Build successful"

# Verify IDE route is dynamic
if npm run build | grep -q "ƒ  /ide"; then
  echo "✅ IDE route correctly marked as dynamic"
else
  echo "⚠️  Warning: IDE route may not be dynamic"
fi

echo "🎉 All checks passed!"
```

Usage:
```bash
chmod +x scripts/verify-build.sh
./scripts/verify-build.sh
```

## Future Prevention Checklist

When adding new features:

- [ ] Create all required files before importing them
- [ ] Verify UI components exist or use standard HTML
- [ ] Guard all browser API access with `typeof window !== 'undefined'`
- [ ] Add `dynamic = 'force-dynamic'` to layout.tsx for client-heavy routes
- [ ] Test build locally before pushing: `npm run build`
- [ ] Check build output for route rendering modes
- [ ] Document any new dependencies or UI components used
- [ ] Add error boundaries for client-side failures

## Summary

**Key Lessons:**
1. **Always create files before importing them** - Seems obvious, but easy to miss in multi-file implementations
2. **Verify UI components exist** - Don't assume components are available
3. **Guard browser APIs** - Check `typeof window !== 'undefined'` for SSR compatibility
4. **Use layout.tsx for route configuration** - Client components can't export route config
5. **Test builds frequently** - Catch issues early, don't wait until the end

**Build Success Indicators:**
- ✅ No compilation errors
- ✅ No module resolution errors
- ✅ No SSR/prerendering errors
- ✅ Route correctly marked as dynamic (ƒ) or static (○) as intended
- ✅ Bundle sizes reasonable (< 2MB for client pages)

**When in doubt:**
```bash
npm run build 2>&1 | tee build.log
grep -i "error\|warn" build.log
```

This ensures all future implementations follow a build-first methodology and catch issues early in the development process.







