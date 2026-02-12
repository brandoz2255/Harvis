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
}

export function SandpackPreview({
  files,
  entryFile = "App.tsx",
  dependencies = {},
  showEditor = false,
  className = "",
}: SandpackPreviewProps) {
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

  // Default index file that imports the entry component
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

  // Build final files object
  const sandpackFiles = useMemo(() => {
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
  }, [normalizedFiles, normalizedEntryFile, indexFile])

  // Visible files for the editor
  const visibleFiles = useMemo(() => {
    return Object.keys(normalizedFiles)
  }, [normalizedFiles])

  // Default safe dependencies
  const safeDependencies = useMemo(() => {
    // Allow only safe, commonly used packages
    const allowedPackages = new Set([
      "react",
      "react-dom",
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
    ])

    const filtered: Record<string, string> = {
      react: "^18.2.0",
      "react-dom": "^18.2.0",
    }

    Object.entries(dependencies).forEach(([pkg, version]) => {
      if (allowedPackages.has(pkg)) {
        filtered[pkg] = version
      }
    })

    return filtered
  }, [dependencies])

  return (
    <div className={`rounded-lg overflow-hidden border border-violet-500/20 ${className}`}>
      <SandpackProvider
        template="react-ts"
        files={sandpackFiles}
        customSetup={{
          dependencies: safeDependencies,
        }}
        options={{
          activeFile: normalizedEntryFile,
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
