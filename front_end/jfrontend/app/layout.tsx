// app/layout.tsx
import "./globals.css"
import { Inter } from "next/font/google"
import { UserProvider } from "@/lib/auth/UserProvider";
import Header from "@/components/Header"

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
        <UserProvider>
          <Header />
          {/* ──────── PAGE BODY ────────── */}
          <main className="container mx-auto px-4 py-8">{children}</main>
        </UserProvider>
      </body>
    </html>
  )
}
// This code defines the root layout for a Next.js application, including a header with navigation links and a main content area.