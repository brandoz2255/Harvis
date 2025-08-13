
'use client';

import React, { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { AuthService } from './AuthService';

interface User {
  id: string;
  name: string;
  email: string;
  avatar?: string;
}

interface UserContextType {
  user: User | null;
  login: (token: string) => Promise<void>;
  logout: () => void;
  isLoading: boolean;
}

const UserContext = createContext<UserContextType | undefined>(undefined);

export const UserProvider = ({ children }: { children: ReactNode }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [lastAuthCheck, setLastAuthCheck] = useState<number>(0);
  const [cachedToken, setCachedToken] = useState<string | null>(null);

  useEffect(() => {
    const checkUser = async () => {
      console.log('UserProvider: Checking for existing token...');
      const token = localStorage.getItem('token');
      const now = Date.now();
      
      // Cache validation for 5 minutes to avoid repeated checks
      if (token && token === cachedToken && (now - lastAuthCheck) < 300000 && user) {
        console.log('UserProvider: Using cached user data');
        setIsLoading(false);
        return;
      }
      
      if (token) {
        try {
          const userData = await AuthService.fetchUser(token);
          setUser(userData);
          setCachedToken(token);
          setLastAuthCheck(now);
          console.log('UserProvider: User data restored from token:', userData);
        } catch (error) {
          console.error('UserProvider: Token validation failed:', error);
          localStorage.removeItem('token');
          setCachedToken(null);
          setUser(null);
        }
      } else {
        setUser(null);
        setCachedToken(null);
      }
      setIsLoading(false);
      console.log('UserProvider: Auth check complete.');
    };
    checkUser();
  }, [user, cachedToken, lastAuthCheck]);

  const login = async (token: string) => {
    localStorage.setItem('token', token);
    console.log('UserProvider: New token stored. Fetching user data...');
    try {
      const userData = await AuthService.fetchUser(token);
      setUser(userData);
      setCachedToken(token);
      setLastAuthCheck(Date.now());
      console.log('UserProvider: User logged in successfully:', userData);
    } catch (error) {
      console.error('UserProvider: Failed to fetch user data after login:', error);
      localStorage.removeItem('token');
      setCachedToken(null);
      setUser(null);
      throw error;
    }
  };

  const logout = () => {
    localStorage.removeItem('token');
    setCachedToken(null);
    setLastAuthCheck(0);
    setUser(null);
    console.log('UserProvider: User logged out.');
  };

  return (
    <UserContext.Provider value={{ user, login, logout, isLoading }}>
      {children}
    </UserContext.Provider>
  );
};

export const useUser = () => {
  const context = useContext(UserContext);
  if (context === undefined) {
    throw new Error('useUser must be used within a UserProvider');
  }
  return context;
};
