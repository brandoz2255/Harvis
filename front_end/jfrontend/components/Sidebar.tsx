'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState } from 'react';
import * as React from 'react';
import { 
  MessageSquare, 
  Zap, 
  Users, 
  Gamepad2, 
  Search, 
  Shield, 
  Menu,
  X,
  Home,
  Code2,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';

const navigationItems = [
  {
    name: 'Home',
    href: '/',
    icon: Home,
    description: 'Main chat interface'
  },
  {
    name: 'Vibe Coding',
    href: '/vibe-coding',
    icon: Code2,
    description: 'AI-powered development environment'
  },
  {
    name: 'Versus Mode',
    href: '/versus-mode',
    icon: Zap,
    description: 'Competitive AI challenges'
  },
  {
    name: 'AI Agents',
    href: '/ai-agents',
    icon: Users,
    description: 'Specialized AI assistants'
  },
  {
    name: 'AI Games',
    href: '/ai-games',
    icon: Gamepad2,
    description: 'Interactive AI-powered games'
  },
  {
    name: 'Research Assistant',
    href: '/research-assistant',
    icon: Search,
    description: 'Advanced research capabilities'
  },
  {
    name: 'Adversary Emulation',
    href: '/adversary-emulation',
    icon: Shield,
    description: 'Security testing and emulation'
  }
];

export default function Sidebar() {
  const pathname = usePathname();
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isCollapsed, setIsCollapsed] = useState(false);

  const toggleMobile = () => setIsMobileOpen(!isMobileOpen);
  const toggleCollapse = () => {
    setIsCollapsed(!isCollapsed);
    // Update main content margin directly
    const mainContent = document.getElementById('main-content');
    if (mainContent) {
      if (!isCollapsed) {
        mainContent.classList.remove('lg:ml-64');
        mainContent.classList.add('lg:ml-16');
      } else {
        mainContent.classList.remove('lg:ml-16');
        mainContent.classList.add('lg:ml-64');
      }
    }
  };

  // Set initial main content margin
  React.useEffect(() => {
    const mainContent = document.getElementById('main-content');
    if (mainContent) {
      if (isCollapsed) {
        mainContent.classList.remove('lg:ml-64');
        mainContent.classList.add('lg:ml-16');
      } else {
        mainContent.classList.remove('lg:ml-16');
        mainContent.classList.add('lg:ml-64');
      }
    }
  }, [isCollapsed]);

  return (
    <>
      {/* Mobile menu button */}
      <button
        onClick={toggleMobile}
        className="lg:hidden fixed top-4 left-4 z-50 p-2 rounded-md bg-gray-800 text-white hover:bg-gray-700 transition-colors"
        aria-label="Toggle menu"
      >
        {isMobileOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
      </button>

      {/* Mobile backdrop */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-30 lg:hidden"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside className={`
        fixed top-0 left-0 z-40 h-full bg-gray-900 border-r border-gray-700 transition-all duration-300 ease-in-out
        ${isMobileOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        ${isCollapsed ? 'w-16' : 'w-64'}
      `}>
        <div className="flex flex-col h-full">
          {/* Header */}
          <div className="p-6 border-b border-gray-700 flex items-center justify-between">
            <Link href="/" onClick={() => setIsMobileOpen(false)}>
              <h1 className={`font-bold text-blue-400 hover:text-blue-300 transition-colors cursor-pointer ${isCollapsed ? 'text-sm' : 'text-xl'}`}>
                {isCollapsed ? 'HA' : 'HARVIS AI'}
              </h1>
            </Link>
            {/* Collapse toggle - only show on desktop */}
            <button
              onClick={toggleCollapse}
              className="hidden lg:block p-1 rounded-md text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
              aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            >
              {isCollapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
            </button>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-4 space-y-2">
            {navigationItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  onClick={() => setIsMobileOpen(false)}
                  className={`
                    group flex items-center rounded-lg transition-all duration-200 relative
                    ${isCollapsed ? 'justify-center px-3 py-3' : 'space-x-3 px-3 py-2.5'}
                    ${isActive 
                      ? 'bg-blue-600 text-white shadow-lg' 
                      : 'text-gray-300 hover:bg-gray-800 hover:text-white'
                    }
                  `}
                  title={isCollapsed ? item.name : undefined}
                >
                  <Icon className={`w-5 h-5 flex-shrink-0 ${isActive ? 'text-white' : 'text-gray-400 group-hover:text-white'}`} />
                  {!isCollapsed && (
                    <div className="flex-1 min-w-0">
                      <div className="text-sm font-medium truncate">
                        {item.name}
                      </div>
                      <div className={`text-xs truncate ${isActive ? 'text-blue-100' : 'text-gray-500 group-hover:text-gray-400'}`}>
                        {item.description}
                      </div>
                    </div>
                  )}
                  {/* Tooltip for collapsed state */}
                  {isCollapsed && (
                    <div className="absolute left-full ml-2 px-2 py-1 bg-gray-800 text-white text-sm rounded-md opacity-0 group-hover:opacity-100 transition-opacity duration-200 pointer-events-none whitespace-nowrap z-50">
                      {item.name}
                    </div>
                  )}
                </Link>
              );
            })}
          </nav>

          {/* Footer */}
          <div className="p-4 border-t border-gray-700">
            <div className={`text-xs text-gray-500 ${isCollapsed ? 'text-center' : 'text-center'}`}>
              {isCollapsed ? 'v0.1.1' : 'Harvis AI v0.1.1'}
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}