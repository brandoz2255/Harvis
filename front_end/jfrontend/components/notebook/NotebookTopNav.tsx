"use client"

import Link from "next/link"
import { usePathname, useRouter } from "next/navigation"
import { BookOpen, Search, Mic, Bot, Settings } from "lucide-react"
import { useState } from "react"

const navItems = [
  { label: "Notebooks", href: "/notebooks", icon: BookOpen },
  { label: "Search", href: "/notebooks/search", icon: Search },
  { label: "Podcasts", href: "/notebooks/podcasts", icon: Mic },
  { label: "Models", href: "/notebooks/models", icon: Bot },
  { label: "Settings", href: "/notebooks/settings", icon: Settings },
] as const

export default function NotebookTopNav() {
  const pathname = usePathname()
  const router = useRouter()
  const [quickSearch, setQuickSearch] = useState("")

  return (
    <div className="border-b border-gray-800 bg-[#0a0a0a]">
      <div className="flex items-center gap-6 px-6 py-4">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-lg bg-blue-600/20 text-blue-400 flex items-center justify-center">
            <BookOpen className="h-5 w-5" />
          </div>
          <span className="text-lg font-semibold text-white">Open Notebook</span>
        </div>

        <div className="flex-1 max-w-xl">
          <div className="flex items-center gap-2 bg-gray-900 border border-gray-800 rounded-lg px-3 py-2">
            <Search className="h-4 w-4 text-gray-400" />
            <input
              value={quickSearch}
              onChange={(e) => setQuickSearch(e.target.value)}
              placeholder="Search across notebooks…"
              className="flex-1 bg-transparent text-sm text-white placeholder-gray-500 focus:outline-none"
              onKeyDown={(e) => {
                if (e.key === "Enter" && quickSearch.trim()) {
                  router.push(`/notebooks/search?q=${encodeURIComponent(quickSearch.trim())}`)
                }
              }}
            />
          </div>
        </div>

        <nav className="flex items-center gap-2">
          {navItems.map((item) => {
            const Icon = item.icon
            const isActive =
              pathname === item.href ||
              (item.href === "/notebooks" &&
                pathname?.startsWith("/notebooks/") &&
                !pathname?.startsWith("/notebooks/search") &&
                !pathname?.startsWith("/notebooks/podcasts") &&
                !pathname?.startsWith("/notebooks/models") &&
                !pathname?.startsWith("/notebooks/settings"))

            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-2 px-3 py-2 rounded-lg text-sm font-medium transition-colors ${
                  isActive
                    ? "bg-blue-600 text-white"
                    : "text-gray-400 hover:text-white hover:bg-gray-800"
                }`}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            )
          })}
        </nav>
      </div>
    </div>
  )
}

