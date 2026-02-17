"use client"

import React, { useMemo } from "react"
import {
  SandpackProvider,
  SandpackLayout,
  SandpackPreview as SandpackPreviewPanel,
  SandpackCodeEditor,
} from "@codesandbox/sandpack-react"

// Night Owl theme inline to avoid extra dependency
const nightOwlTheme = {
  colors: {
    surface1: "#011627",
    surface2: "#1d3b53",
    surface3: "#1d3b53",
    clickable: "#6988a1",
    base: "#d6deeb",
    disabled: "#4f6479",
    hover: "#7eb5d6",
    accent: "#82aaff",
    error: "#ef5350",
    errorSurface: "#feebee",
  },
  syntax: {
    plain: "#d6deeb",
    comment: { color: "#637777", fontStyle: "italic" },
    keyword: "#c792ea",
    tag: "#7fdbca",
    punctuation: "#c792ea",
    definition: "#82aaff",
    property: "#addb67",
    static: "#f78c6c",
    string: "#ecc48d",
  },
  font: {
    body: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    mono: '"Fira Code", "Fira Mono", Menlo, Consolas, "DejaVu Sans Mono", monospace',
    size: "13px",
    lineHeight: "20px",
  },
}

interface SandpackPreviewProps {
  files: Record<string, string>
  entryFile?: string
  dependencies?: Record<string, string>
  showEditor?: boolean
  className?: string
  framework?: string // 'react' | 'nextjs' | 'vue' etc.
}

export function SandpackPreview({
  files,
  entryFile = "App.tsx",
  dependencies = {},
  showEditor = false,
  className = "",
  framework,
}: SandpackPreviewProps) {
  // Detect if this is a Next.js app based on file structure
  const isNextJs = useMemo(() => {
    if (framework === "nextjs") return true
    const fileKeys = Object.keys(files).map(k => k.toLowerCase())
    return (
      fileKeys.some(k => k.includes("/pages/") || k.includes("/app/") || k === "next.config") ||
      dependencies?.["next"] !== undefined
    )
  }, [files, dependencies, framework])

  // Normalize file paths to have leading slashes
  const normalizedFiles = useMemo(() => {
    const result: Record<string, string> = {}

    Object.entries(files).forEach(([key, value]) => {
      const path = key.startsWith("/") ? key : `/${key}`
      result[path] = value
    })

    return result
  }, [files])

  // Determine the entry file path
  const normalizedEntryFile = entryFile.startsWith("/") ? entryFile : `/${entryFile}`

  // Build final files object based on framework
  const sandpackFiles = useMemo(() => {
    if (isNextJs) {
      // For Next.js, just use the files as-is (Sandpack handles the setup)
      const result: Record<string, string> = { ...normalizedFiles }

      // Ensure we have a page file
      const hasPageFile =
        result["/pages/index.tsx"] ||
        result["/pages/index.js"] ||
        result["/app/page.tsx"] ||
        result["/app/page.js"]

      if (!hasPageFile) {
        // Check if there's an App component we can use as the index page
        if (result["/App.tsx"] || result[normalizedEntryFile]) {
          const appContent = result["/App.tsx"] || result[normalizedEntryFile]
          result["/pages/index.tsx"] = appContent
        } else {
          // Create a default page
          result["/pages/index.tsx"] = `
export default function Home() {
  return (
    <div style={{ padding: "20px", fontFamily: "system-ui, sans-serif" }}>
      <h1>Next.js App</h1>
      <p>Add your pages to /pages or /app directory.</p>
    </div>
  );
}
`.trim()
        }
      }

      return result
    }

    // For React apps, create the bootstrap index file
    const indexFile = `
import React from "react";
import { createRoot } from "react-dom/client";
import App from "${normalizedEntryFile.replace(/\.(tsx|ts|jsx|js)$/, "")}";

const root = createRoot(document.getElementById("root")!);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
`.trim()

    const result: Record<string, string> = {
      "/index.tsx": indexFile,
      ...normalizedFiles,
    }

    // Ensure we have an App file
    if (!result[normalizedEntryFile] && !result["/App.tsx"]) {
      result["/App.tsx"] = `
export default function App() {
  return (
    <div style={{ padding: "20px", fontFamily: "system-ui, sans-serif" }}>
      <h1>Preview</h1>
      <p>No entry component found.</p>
    </div>
  );
}
`.trim()
    }

    return result
  }, [normalizedFiles, normalizedEntryFile, isNextJs])

  // Visible files for the editor
  const visibleFiles = useMemo(() => {
    return Object.keys(sandpackFiles).filter(
      (f) => !f.includes("node_modules") && f !== "/index.tsx"
    )
  }, [sandpackFiles])

  // Determine the active file based on framework
  const activeFile = useMemo(() => {
    if (isNextJs) {
      // Prefer pages/index or app/page for Next.js
      const pageFiles = [
        "/pages/index.tsx",
        "/pages/index.js",
        "/app/page.tsx",
        "/app/page.js",
      ]
      for (const pf of pageFiles) {
        if (sandpackFiles[pf]) return pf
      }
    }
    return normalizedEntryFile
  }, [isNextJs, sandpackFiles, normalizedEntryFile])

  // Default safe dependencies
  const safeDependencies = useMemo(() => {
    // Allow only safe, commonly used packages
    const allowedPackages = new Set([
      "react",
      "react-dom",
      "next",
      "lucide-react",
      "tailwindcss",
      "clsx",
      "class-variance-authority",
      "date-fns",
      "recharts",
      "framer-motion",
      "zustand",
      "@radix-ui/react-dialog",
      "@radix-ui/react-popover",
      "@radix-ui/react-select",
      "@radix-ui/react-tabs",
      "@radix-ui/react-tooltip",
      "@radix-ui/react-slot",
      "tailwind-merge",
    ])

    // Base dependencies based on framework
    const filtered: Record<string, string> = isNextJs
      ? {
          next: "^14.0.0",
          react: "^18.2.0",
          "react-dom": "^18.2.0",
        }
      : {
          react: "^18.2.0",
          "react-dom": "^18.2.0",
        }

    Object.entries(dependencies).forEach(([pkg, version]) => {
      if (allowedPackages.has(pkg)) {
        filtered[pkg] = version
      }
    })

    return filtered
  }, [dependencies, isNextJs])

  // Select template based on framework
  const template = isNextJs ? "nextjs" : "react-ts"

  return (
    <div className={`rounded-lg overflow-hidden border border-violet-500/20 ${className}`}>
      <SandpackProvider
        template={template as "react-ts" | "nextjs"}
        files={sandpackFiles}
        customSetup={{
          dependencies: safeDependencies,
        }}
        options={{
          activeFile: activeFile,
          visibleFiles: visibleFiles.length > 0 ? visibleFiles : undefined,
          recompileMode: "delayed",
          recompileDelay: 500,
        }}
        theme={nightOwlTheme}
      >
        <SandpackLayout>
          {showEditor && (
            <SandpackCodeEditor
              style={{ height: "300px" }}
              showTabs
              showLineNumbers
              showInlineErrors
              wrapContent
            />
          )}
          <SandpackPreviewPanel
            style={{ height: showEditor ? "300px" : "400px" }}
            showOpenInCodeSandbox={false}
            showRefreshButton={true}
          />
        </SandpackLayout>
      </SandpackProvider>
    </div>
  )
}

export default SandpackPreview
