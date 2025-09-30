
'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useUser } from '@/lib/auth/UserProvider';
import { AuthService } from '@/lib/auth/AuthService';
import { useRouter } from 'next/navigation';
import Aurora from '@/components/Aurora';

export default function SignUpPage() {
  const router = useRouter();
  const { user, login, isLoading } = useUser();
  const [username, setUsername] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    if (user) {
      router.push('/');
    }
  }, [user, router]);

  // Memoize Aurora props to prevent unnecessary re-renders
  const auroraProps = useMemo(() => ({
    className: "w-full h-full",
    colorStops: ['#059669', '#0D9488', '#0F766E'],
    blend: 0.4,
    amplitude: 1.0,
    speed: 0.6,
  }), []);

  // Use useCallback for event handlers to prevent Aurora re-renders
  const handleUsernameChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setUsername(e.target.value);
  }, []);

  const handleEmailChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setEmail(e.target.value);
  }, []);

  const handlePasswordChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setPassword(e.target.value);
  }, []);

  const handleSubmit = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setSuccess('');

    if (!username || !email || !password) {
      setError('All fields are required.');
      return;
    }

    try {
      const token = await AuthService.signup(username, email, password);
      await login(token);
      setSuccess('Signup successful!');
      router.push('/');
    } catch (err: any) {
      setError(err.message || 'Signup failed.');
    }
  }, [username, email, password, login, router]);

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
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm flex items-center justify-center">
      <div className="w-full max-w-md p-8 space-y-6 bg-gray-800/80 backdrop-blur-sm rounded-lg shadow-md">
        <h1 className="text-2xl font-bold text-center text-white">Sign Up</h1>
        <form onSubmit={handleSubmit} className="space-y-6">
          <div>
            <label htmlFor="username" className="text-white">Username</label>
            <Input
              id="username"
              type="text"
              value={username}
              onChange={handleUsernameChange}
              required
              className="bg-gray-700 text-white border-gray-600"
            />
          </div>
          <div>
            <label htmlFor="email" className="text-white">Email</label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={handleEmailChange}
              required
              className="bg-gray-700 text-white border-gray-600"
            />
          </div>
          <div>
            <label htmlFor="password" className="text-white">Password</label>
            <Input
              id="password"
              type="password"
              value={password}
              onChange={handlePasswordChange}
              required
              className="bg-gray-700 text-white border-gray-600"
            />
          </div>
          {error && <p className="text-red-500">{error}</p>}
          {success && <p className="text-green-500">{success}</p>}
          <Button type="submit" className="w-full">Sign Up</Button>
        </form>
      </div>
      </div>
    </div>
  );
}

