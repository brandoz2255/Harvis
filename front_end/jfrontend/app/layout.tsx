// app/layout.tsx
import "./globals.css"
import { Inter } from "next/font/google"
import { UserProvider } from "@/lib/auth/UserProvider";
import Sidebar from "@/components/Sidebar"
import AuthStatus from "@/components/AuthStatus"

const inter = Inter({ subsets: ["latin"] })

export const metadata = {
  title: "HARVIS AI",
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
          <div className="flex h-screen">
            <Sidebar />
            <div className="flex-1 flex flex-col lg:ml-64 transition-all duration-300"
                 id="main-content">
              {/* Auth buttons in top-right */}
              <div className="fixed top-4 right-4 z-50">
                <AuthStatus />
              </div>
              {/* ──────── PAGE BODY ────────── */}
              <main className="flex-1 overflow-auto pt-16">
                <div className="container mx-auto px-4 py-8">
                  {children}
                </div>
              </main>
            </div>
          </div>
        </UserProvider>
      </body>
    </html>
  )
}
// This code defines the root layout for a Next.js application, including a header with navigation links and a main content area.