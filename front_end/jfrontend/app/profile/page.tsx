'use client';

import { useUser } from '@/lib/auth/UserProvider';
import { useRouter } from 'next/navigation';
import { useEffect } from 'react';
import { Button } from '@/components/ui/button';
import Image from 'next/image';
import Link from 'next/link';
import Aurora from '@/components/Aurora';

export default function ProfilePage() {
  const { user, logout, isLoading } = useUser();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !user) {
      router.push('/login');
    }
  }, [user, isLoading, router]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-black via-gray-900 to-blue-900">
        <div className="text-white text-lg">Loading...</div>
      </div>
    );
  }

  if (!user) {
    return null; // Will redirect to login
  }

  const handleLogout = () => {
    logout();
    router.push('/');
  };

  return (
    <div className="relative min-h-screen overflow-hidden">
      {/* Aurora Background */}
      <div className="fixed inset-0 -z-10 pointer-events-none select-none">
        <Aurora
          className="w-full h-full"
          colorStops={['#3B82F6', '#8B5CF6', '#06B6D4']}
          blend={0.4}
          amplitude={1.0}
          speed={0.6}
        />
        <div className="absolute inset-0 bg-black/20 pointer-events-none [mask-image:radial-gradient(ellipse_at_center,white,transparent_80%)]" />
      </div>

      {/* Content */}
      <div className="relative z-10 min-h-screen bg-black/40 backdrop-blur-sm text-white">
        <div className="container mx-auto px-4 py-8 max-w-2xl">
        {/* Back to Home */}
        <div className="mb-6">
          <Link href="/">
            <Button variant="ghost" className="text-slate-300 hover:text-white">
              ← Back to Home
            </Button>
          </Link>
        </div>

        {/* Profile Card */}
        <div className="bg-gray-800/80 backdrop-blur-sm rounded-lg shadow-xl p-8">
          <div className="text-center mb-8">
            <h1 className="text-3xl font-bold mb-2">User Profile</h1>
            <p className="text-gray-400">Manage your account information</p>
          </div>

          {/* Avatar and Basic Info */}
          <div className="flex flex-col items-center mb-8">
            <div className="w-24 h-24 rounded-full overflow-hidden mb-4 ring-4 ring-blue-500/20">
              <Image
                src={user.avatar || 'https://api.dicebear.com/7.x/initials/svg?seed=' + user.name}
                alt="User Avatar"
                className="w-full h-full object-cover bg-gray-600"
                width={96}
                height={96}
              />
            </div>
            <h2 className="text-2xl font-semibold mb-2">{user.name}</h2>
            <p className="text-gray-400">{user.email}</p>
          </div>

          {/* Profile Details */}
          <div className="space-y-6">
            <div>
              <h3 className="text-lg font-semibold mb-4">Account Information</h3>
              <div className="grid gap-4">
                <div className="flex justify-between items-center p-4 bg-gray-700/50 rounded-lg">
                  <span className="text-gray-300">User ID</span>
                  <span className="font-mono text-sm">{user.id}</span>
                </div>
                <div className="flex justify-between items-center p-4 bg-gray-700/50 rounded-lg">
                  <span className="text-gray-300">Username</span>
                  <span>{user.name}</span>
                </div>
                <div className="flex justify-between items-center p-4 bg-gray-700/50 rounded-lg">
                  <span className="text-gray-300">Email</span>
                  <span>{user.email}</span>
                </div>
              </div>
            </div>

            {/* Actions */}
            <div className="pt-6 border-t border-gray-700">
              <h3 className="text-lg font-semibold mb-4">Account Actions</h3>
              <div className="flex gap-4">
                <Button 
                  onClick={handleLogout}
                  variant="outline"
                  className="border-red-600 text-red-400 hover:bg-red-600/10"
                >
                  Sign Out
                </Button>
              </div>
            </div>
          </div>
        </div>
        </div>
      </div>
    </div>
  );
}