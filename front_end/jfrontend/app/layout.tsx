// app/layout.tsx
import "./globals.css"
import { Inter } from "next/font/google"
import Link from "next/link"
import { Button } from "@/components/ui/button"

const inter = Inter({ subsets: ["latin"] })

export const metadata = {
  title: "JARVIS AI",
  description: "Advanced AI Assistant",
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={`${inter.className} bg-gradient-to-br from-black via-gray-900 to-blue-900 text-white`}>
        {/* ──────── SITE HEADER ────────── */}
        <header className="w-full border-b border-slate-700 bg-[#111827]/80 backdrop-blur-sm">
          <div className="container mx-auto flex items-center justify-between px-4 py-3">
            <h1 className="text-xl font-bold">JARVIS AI</h1>
            <nav className="flex items-center space-x-4">
              {/* Example other nav links */}
              <Link href="/versus-mode">
                <Button variant="ghost" className="text-slate-300 hover:text-white">
                  Versus
                </Button>
              </Link>
              <Link href="/ai-agents">
                <Button variant="ghost" className="text-slate-300 hover:text-white">
                  Agents
                </Button>
              </Link>

              {/* ← Your new Login button goes here → */}
              <Link href="/login">
                <Button variant="ghost" className="text-slate-300 hover:text-white">
                  Login
                </Button>
              </Link>
            </nav>
          </div>
        </header>

        {/* ──────── PAGE BODY ────────── */}
        <main className="container mx-auto px-4 py-8">{children}</main>
      </body>
    </html>
  )
}
// This code defines the root layout for a Next.js application, including a header with navigation links and a main content area.