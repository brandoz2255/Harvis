
'use client';

import Link from 'next/link';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { useUser } from '@/lib/auth/UserProvider';
import { useState } from 'react';

export default function Header() {
  const { user, logout, isLoading } = useUser();
  const [dropdownOpen, setDropdownOpen] = useState(false);

  console.log('Header: user state:', user);
  console.log('Header: isLoading state:', isLoading);

  const handleLogout = () => {
    logout();
    setDropdownOpen(false);
  };

  if (isLoading) {
    return null; // Or a loading spinner
  }

  return (
    <header className="w-full border-b border-slate-700 bg-[#111827]/80 backdrop-blur-sm">
      <div className="container mx-auto flex items-center justify-between px-4 py-3">
        <h1 className="text-xl font-bold">JARVIS AI</h1>
        <nav className="flex items-center space-x-4">
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

          {user ? (
            <div className="relative">
              <button
                onClick={() => setDropdownOpen(!dropdownOpen)}
                className="relative w-10 h-10 rounded-full overflow-hidden focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500"
              >
                <Image
                  src={user.avatar || 'https://api.dicebear.com/7.x/initials/svg?seed=Default'}
                  alt="User Avatar"
                  className="w-full h-full object-cover"
                  width={40}
                  height={40}
                />
              </button>
              {dropdownOpen && (
                <div className="absolute right-0 mt-2 w-48 bg-gray-800 rounded-md shadow-lg py-1 z-50">
                  <Link href="/profile" className="block px-4 py-2 text-sm text-gray-200 hover:bg-gray-700">
                    Profile
                  </Link>
                  <button
                    onClick={handleLogout}
                    className="block w-full text-left px-4 py-2 text-sm text-gray-200 hover:bg-gray-700"
                  >
                    Log out
                  </button>
                </div>
              )}
            </div>
          ) : (
            <>
              <Link href="/login">
                <Button variant="ghost" className="text-slate-300 hover:text-white">
                  Login
                </Button>
              </Link>
              <Link href="/signup">
                <Button variant="ghost" className="text-slate-300 hover:text-white">
                  Sign Up
                </Button>
              </Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
