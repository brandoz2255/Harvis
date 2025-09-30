
"use client"

import { useState, useEffect, useCallback, useMemo } from "react"
import { useRouter } from "next/navigation"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { useUser } from "@/lib/auth/UserProvider";
import { AuthService } from "@/lib/auth/AuthService"
import Aurora from "@/components/Aurora"

export default function LoginPage() {
  const router = useRouter()
  const { user, login, isLoading } = useUser();
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState("")

  useEffect(() => {
    if (user) {
      router.push("/");
    }
  }, [user, router]);

  // Memoize Aurora props to prevent unnecessary re-renders
  const auroraProps = useMemo(() => ({
    className: "w-full h-full",
    colorStops: ['#3B82F6', '#1D4ED8', '#1E40AF'],
    blend: 0.4,
    amplitude: 1.0,
    speed: 0.6,
  }), []);

  // Use useCallback for event handlers to prevent Aurora re-renders
  const handleEmailChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setEmail(e.target.value);
  }, []);

  const handlePasswordChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setPassword(e.target.value);
  }, []);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    try {
      const token = await AuthService.login(email, password);
      await login(token);
      router.push("/"); // go to home
    } catch (err: any) {
      setError(err.message || "Login failed.");
    }
  }, [email, password, login, router])

  if (isLoading) {
    return <div className="min-h-screen flex items-center justify-center">Loading...</div>
  }

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora {...auroraProps} />
        <div className="absolute inset-0 bg-black/20 pointer-events-none [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]" />
      </div>

      {/* Content */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm flex items-center justify-center px-4">
      <div className="max-w-md w-full bg-[#111827] p-8 rounded-lg shadow-lg border border-slate-700">
        <h2 className="text-2xl font-bold text-white mb-6 text-center">Sign in to Jarvis</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm text-slate-300 block mb-1">Email</label>
            <Input
              type="email"
              value={email}
              onChange={handleEmailChange}
              className="bg-slate-800 border-slate-600 text-white"
              required
            />
          </div>

          <div>
            <label className="text-sm text-slate-300 block mb-1">Password</label>
            <Input
              type="password"
              value={password}
              onChange={handlePasswordChange}
              className="bg-slate-800 border-slate-600 text-white"
              required
            />
          </div>

          {error && <p className="text-sm text-red-500">{error}</p>}

          <Button
            type="submit"
            className="w-full bg-blue-600 hover:bg-blue-700 text-white"
          >
            Sign In
          </Button>
        </form>
      </div>
      </div>
    </div>
  )
}

