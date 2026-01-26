'use client'

import { useState, useEffect } from 'react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'

import { cn } from '@/lib/utils'
import { Button } from '@/components/ui/button'
import { useOpenNotebookSidebarStore, useCreateDialogsStore } from '@/stores/openNotebookUiStore'
import { Tooltip } from '@/components/ui/tooltip'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from '@/components/ui/dropdown-menu'
import { Separator } from '@/components/ui/separator'
import {
  Book,
  Search,
  Mic,
  Bot,
  Shuffle,
  Settings,
  LogOut,
  ChevronLeft,
  Menu,
  FileText,
  Plus,
  Wrench,
  Command,
  Sun,
  Moon,
  Home,
} from 'lucide-react'
import { useTheme } from 'next-themes'

// Navigation structure matching Open Notebook
const navigation = [
  {
    title: 'Collect',
    items: [
      { name: 'Sources', href: '/open-notebook/sources', icon: FileText },
    ],
  },
  {
    title: 'Process',
    items: [
      { name: 'Notebooks', href: '/open-notebook/notebooks', icon: Book },
      { name: 'Ask and Search', href: '/open-notebook/search', icon: Search },
    ],
  },
  {
    title: 'Create',
    items: [
      { name: 'Podcasts', href: '/open-notebook/podcasts', icon: Mic },
    ],
  },
  {
    title: 'Manage',
    items: [
      { name: 'Models', href: '/open-notebook/models', icon: Bot },
      { name: 'Transformations', href: '/open-notebook/transformations', icon: Shuffle },
      { name: 'Settings', href: '/open-notebook/settings', icon: Settings },
      { name: 'Advanced', href: '/open-notebook/advanced', icon: Wrench },
    ],
  },
] as const

type CreateTarget = 'source' | 'notebook' | 'podcast'

export function OpenNotebookSidebar() {
  const pathname = usePathname()
  const router = useRouter()
  const { theme, setTheme } = useTheme()
  const { isCollapsed, toggleCollapse } = useOpenNotebookSidebarStore()
  const { openSourceDialog, openNotebookDialog, openPodcastDialog } = useCreateDialogsStore()

  const [createMenuOpen, setCreateMenuOpen] = useState(false)
  const [isMac, setIsMac] = useState(true) // Default to Mac for SSR

  // Detect platform for keyboard shortcut display
  useEffect(() => {
    setIsMac(navigator.platform.toLowerCase().includes('mac'))
  }, [])

  const handleCreateSelection = (target: CreateTarget) => {
    setCreateMenuOpen(false)

    if (target === 'source') {
      openSourceDialog()
    } else if (target === 'notebook') {
      openNotebookDialog()
    } else if (target === 'podcast') {
      openPodcastDialog()
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('token')
    router.push('/login')
  }

  const toggleTheme = () => {
    setTheme(theme === 'dark' ? 'light' : 'dark')
  }

  return (
    <div
      className={cn(
        'app-sidebar flex h-full flex-col bg-sidebar border-sidebar-border border-r transition-all duration-300',
        isCollapsed ? 'w-16' : 'w-64'
      )}
    >
      {/* Header */}
      <div
        className={cn(
          'flex h-16 items-center group',
          isCollapsed ? 'justify-center px-2' : 'justify-between px-4'
        )}
      >
        {isCollapsed ? (
          <div className="relative flex items-center justify-center w-full">
            <Book
              className="h-6 w-6 text-sidebar-foreground transition-opacity group-hover:opacity-0"
            />
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleCollapse}
              className="absolute text-sidebar-foreground hover:bg-sidebar-accent opacity-0 group-hover:opacity-100 transition-opacity"
            >
              <Menu className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2">
              <Book className="h-6 w-6 text-primary" />
              <span className="text-base font-medium text-sidebar-foreground">
                Open Notebook
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleCollapse}
              className="text-sidebar-foreground hover:bg-sidebar-accent"
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>

      {/* Navigation */}
      <nav
        className={cn(
          'flex-1 space-y-1 py-4 overflow-y-auto',
          isCollapsed ? 'px-2' : 'px-3'
        )}
      >
        {/* Create Button */}
        <div
          className={cn(
            'mb-4',
            isCollapsed ? 'px-0' : 'px-3'
          )}
        >
          <DropdownMenu open={createMenuOpen} onOpenChange={setCreateMenuOpen}>
            {isCollapsed ? (
              <Tooltip content="Create" side="right">
                <DropdownMenuTrigger asChild>
                  <Button
                    onClick={() => setCreateMenuOpen(true)}
                    variant="default"
                    size="sm"
                    className="w-full justify-center px-2 bg-primary hover:bg-primary/90 text-primary-foreground border-0"
                    aria-label="Create"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </DropdownMenuTrigger>
              </Tooltip>
            ) : (
              <DropdownMenuTrigger asChild>
                <Button
                  onClick={() => setCreateMenuOpen(true)}
                  variant="default"
                  size="sm"
                  className="w-full justify-start bg-primary hover:bg-primary/90 text-primary-foreground border-0"
                >
                  <Plus className="h-4 w-4 mr-2" />
                  Create
                </Button>
              </DropdownMenuTrigger>
            )}

            <DropdownMenuContent
              align={isCollapsed ? 'end' : 'start'}
              side={isCollapsed ? 'right' : 'bottom'}
              className="w-48"
            >
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault()
                  handleCreateSelection('source')
                }}
              >
                <FileText className="h-4 w-4 mr-2" />
                Source
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault()
                  handleCreateSelection('notebook')
                }}
              >
                <Book className="h-4 w-4 mr-2" />
                Notebook
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={(e) => {
                  e.preventDefault()
                  handleCreateSelection('podcast')
                }}
              >
                <Mic className="h-4 w-4 mr-2" />
                Podcast
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {/* Navigation Sections */}
        {navigation.map((section, index) => (
          <div key={section.title}>
            {index > 0 && (
              <Separator className="my-3" />
            )}
            <div className="space-y-1">
              {!isCollapsed && (
                <h3 className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-sidebar-foreground/60">
                  {section.title}
                </h3>
              )}

              {section.items.map((item) => {
                const isActive = pathname.startsWith(item.href)
                const button = (
                  <Button
                    variant={isActive ? 'secondary' : 'ghost'}
                    className={cn(
                      'w-full gap-3 text-sidebar-foreground',
                      isActive && 'bg-sidebar-accent text-sidebar-accent-foreground',
                      isCollapsed ? 'justify-center px-2' : 'justify-start'
                    )}
                  >
                    <item.icon className="h-4 w-4" />
                    {!isCollapsed && <span>{item.name}</span>}
                  </Button>
                )

                if (isCollapsed) {
                  return (
                    <Tooltip key={item.name} content={item.name} side="right">
                      <Link href={item.href}>
                        {button}
                      </Link>
                    </Tooltip>
                  )
                }

                return (
                  <Link key={item.name} href={item.href}>
                    {button}
                  </Link>
                )
              })}
            </div>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div
        className={cn(
          'border-t border-sidebar-border p-3 space-y-2',
          isCollapsed && 'px-2'
        )}
      >
        {/* Back to HARVIS link */}
        {isCollapsed ? (
          <Tooltip content="Back to HARVIS" side="right">
            <Link href="/ide">
              <Button
                variant="ghost"
                className="w-full justify-center text-sidebar-foreground hover:bg-sidebar-accent"
              >
                <Home className="h-4 w-4" />
              </Button>
            </Link>
          </Tooltip>
        ) : (
          <Link href="/ide">
            <Button
              variant="ghost"
              className="w-full justify-start gap-3 text-sidebar-foreground hover:bg-sidebar-accent"
            >
              <Home className="h-4 w-4" />
              Back to HARVIS
            </Button>
          </Link>
        )}

        {/* Command Palette hint */}
        {!isCollapsed && (
          <div className="px-3 py-1.5 text-xs text-sidebar-foreground/60">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-1.5">
                <Command className="h-3 w-3" />
                Quick actions
              </span>
              <kbd className="pointer-events-none inline-flex h-5 select-none items-center gap-1 rounded border bg-muted px-1.5 font-mono text-[10px] font-medium text-muted-foreground">
                {isMac ? <span className="text-xs">&#8984;</span> : <span>Ctrl+</span>}K
              </kbd>
            </div>
            <p className="mt-1 text-[10px] text-sidebar-foreground/40">
              Navigation, search, ask, theme
            </p>
          </div>
        )}

        {/* Theme Toggle */}
        <div
          className={cn(
            'flex',
            isCollapsed ? 'justify-center' : 'justify-start'
          )}
        >
          {isCollapsed ? (
            <Tooltip content="Toggle theme" side="right">
              <Button
                variant="ghost"
                size="sm"
                onClick={toggleTheme}
                className="h-9 w-9 p-0 text-sidebar-foreground hover:bg-sidebar-accent"
              >
                {theme === 'dark' ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </Button>
            </Tooltip>
          ) : (
            <Button
              variant="ghost"
              size="sm"
              onClick={toggleTheme}
              className="w-full justify-start gap-3 text-sidebar-foreground hover:bg-sidebar-accent"
            >
              {theme === 'dark' ? (
                <>
                  <Sun className="h-4 w-4" />
                  Light Mode
                </>
              ) : (
                <>
                  <Moon className="h-4 w-4" />
                  Dark Mode
                </>
              )}
            </Button>
          )}
        </div>

        {/* Logout Button */}
        {isCollapsed ? (
          <Tooltip content="Sign Out" side="right">
            <Button
              variant="outline"
              className="w-full justify-center"
              onClick={handleLogout}
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </Tooltip>
        ) : (
          <Button
            variant="outline"
            className="w-full justify-start gap-3"
            onClick={handleLogout}
          >
            <LogOut className="h-4 w-4" />
            Sign Out
          </Button>
        )}
      </div>
    </div>
  )
}
