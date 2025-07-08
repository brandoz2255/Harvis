
"use client"

import { useState, useEffect } from "react"
import { useRouter } from "next/navigation"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import { useUser } from "@/lib/auth/UserProvider";
import { AuthService } from "@/lib/auth/AuthService"

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

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError("")

    try {
      const token = await AuthService.login(email, password);
      await login(token);
      router.push("/"); // go to home
    } catch (err: any) {
      setError(err.message || "Login failed.");
    }
  }

  if (isLoading) {
    return <div className="min-h-screen flex items-center justify-center">Loading...</div>
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-black via-gray-900 to-blue-900 px-4">
      <div className="max-w-md w-full bg-[#111827] p-8 rounded-lg shadow-lg border border-slate-700">
        <h2 className="text-2xl font-bold text-white mb-6 text-center">Sign in to Jarvis</h2>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="text-sm text-slate-300 block mb-1">Email</label>
            <Input
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="bg-slate-800 border-slate-600 text-white"
              required
            />
          </div>

          <div>
            <label className="text-sm text-slate-300 block mb-1">Password</label>
            <Input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
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
  )
}

