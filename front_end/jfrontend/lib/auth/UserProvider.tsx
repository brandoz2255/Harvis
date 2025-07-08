
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

  useEffect(() => {
    const checkUser = async () => {
      console.log('UserProvider: Checking for existing token...');
      const token = localStorage.getItem('jwt_token');
      if (token) {
        try {
          const userData = await AuthService.fetchUser(token);
          setUser(userData);
          console.log('UserProvider: User data restored from token:', userData);
        } catch (error) {
          console.error('UserProvider: Token validation failed:', error);
          localStorage.removeItem('jwt_token'); // Token is invalid, remove it
        }
      }
      setIsLoading(false);
      console.log('UserProvider: Initial auth check complete.');
    };
    checkUser();
  }, []);

  const login = async (token: string) => {
    localStorage.setItem('jwt_token', token);
    console.log('UserProvider: New token stored. Fetching user data...');
    try {
      const userData = await AuthService.fetchUser(token);
      setUser(userData);
      console.log('UserProvider: User logged in successfully:', userData);
    } catch (error) {
      console.error('UserProvider: Failed to fetch user data after login:', error);
      localStorage.removeItem('jwt_token');
      setUser(null);
      throw error; // Re-throw to be caught by the UI
    }
  };

  const logout = () => {
    localStorage.removeItem('jwt_token');
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
