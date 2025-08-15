'use client';

import Link from 'next/link';
import Image from 'next/image';
import { Button } from '@/components/ui/button';
import { useUser } from '@/lib/auth/UserProvider';
import { useState } from 'react';

export default function AuthStatus() {
  const { user, logout, isLoading } = useUser();
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const handleLogout = () => {
    logout();
    setDropdownOpen(false);
  };

  if (isLoading) {
    return null;
  }

  return (
    <div className="flex items-center space-x-4">
      {user ? (
        <div className="relative">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="relative w-10 h-10 rounded-full overflow-hidden focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 hover:ring-2 hover:ring-blue-400 bg-gray-800 border border-gray-600"
          >
            <Image
              src={user.avatar || 'https://api.dicebear.com/7.x/initials/svg?seed=' + user.name}
              alt="User Avatar"
              className="w-full h-full object-cover"
              width={40}
              height={40}
            />
          </button>
          {dropdownOpen && (
            <>
              <div 
                className="fixed inset-0 z-[9998]" 
                onClick={() => setDropdownOpen(false)}
              />
              <div className="absolute right-0 mt-2 w-48 bg-gray-800 border border-gray-600 rounded-md shadow-xl py-1 z-[9999]">
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
            <Button variant="ghost" className="text-slate-300 hover:text-white bg-gray-800/50 border border-gray-600">
              Login
            </Button>
          </Link>
          <Link href="/signup">
            <Button variant="ghost" className="text-slate-300 hover:text-white bg-gray-800/50 border border-gray-600">
              Sign Up
            </Button>
          </Link>
        </>
      )}
    </div>
  );
}