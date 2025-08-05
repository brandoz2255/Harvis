
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
  console.log('Header: Should show auth buttons:', !user && !isLoading);

  const handleLogout = () => {
    logout();
    setDropdownOpen(false);
  };

  if (isLoading) {
    return null; // Or a loading spinner
  }

  return (
    <header className="w-full border-b border-slate-700 bg-[#111827]/80 backdrop-blur-sm relative z-50">
      <div className="container mx-auto flex items-center justify-end px-4 py-3">
        <nav className="flex items-center space-x-4">
          {user ? (
            <div className="relative">
              <button
                onClick={() => setDropdownOpen(!dropdownOpen)}
                className="relative w-10 h-10 rounded-full overflow-hidden focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 hover:ring-2 hover:ring-blue-400"
              >
                <Image
                  src={user.avatar || 'https://api.dicebear.com/7.x/initials/svg?seed=' + user.name}
                  alt="User Avatar"
                  className="w-full h-full object-cover bg-gray-600"
                  width={40}
                  height={40}
                />
              </button>
              {dropdownOpen && (
                <>
                  {/* Backdrop to close dropdown when clicking outside */}
                  <div 
                    className="fixed inset-0 z-[9998]" 
                    onClick={() => setDropdownOpen(false)}
                  />
                  <div className="absolute right-0 mt-2 w-48 bg-gray-800 border border-gray-700 rounded-md shadow-xl py-1 z-[9999]">
                    <div className="px-4 py-2 text-xs text-gray-400 border-b border-gray-700">
                      {user.name}
                    </div>
                    <Link 
                      href="/profile" 
                      className="block px-4 py-2 text-sm text-gray-200 hover:bg-gray-700 transition-colors"
                      onClick={() => setDropdownOpen(false)}
                    >
                      Profile
                    </Link>
                    <button
                      onClick={handleLogout}
                      className="block w-full text-left px-4 py-2 text-sm text-gray-200 hover:bg-gray-700 transition-colors"
                    >
                      Log out
                    </button>
                  </div>
                </>
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
