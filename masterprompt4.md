# Open Notebook UI Implementation Master Prompt

## 🎯 OBJECTIVE
Implement the **exact UI** from Open Notebook (https://github.com/lfnovo/open-notebook) into HARVIS AI as the **prominent interface**, replacing existing notebook functionality while preserving the original design, layout, and user experience.

---

## 📋 PROJECT CONTEXT

### Current HARVIS Structure
- **Frontend**: Next.js 14 (App Router) at `front_end/jfrontend/`
- **Backend**: FastAPI at `python_back_end/` (Already prepared for Open Notebook integration)
- **Styling**: Tailwind CSS + Radix UI components
- **State**: Zustand for state management
- **Database**: PostgreSQL (primary) + SurrealDB (for Open Notebook)

### Open Notebook Architecture to Implement
- **Framework**: Next.js 14 with TypeScript
- **UI Components**: shadcn/ui (Radix UI primitives)
- **Styling**: Tailwind CSS
- **State Management**: React hooks + Context
- **Backend Integration**: API routes connecting to FastAPI/SurrealDB

---

## 🎨 UI COMPONENTS TO REPLICATE EXACTLY

### 1. Main Layout Structure (`app/layout.tsx`)

```typescript
// Target structure from Open Notebook
<html>
  <body>
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar - Collapsible notebook navigation */}
      <NotebookSidebar />
      
      {/* Main Content Area */}
      <main className="flex-1 flex flex-col">
        {/* Top Navigation Bar */}
        <TopNavigation />
        
        {/* Content Area - Dynamic based on route */}
        <div className="flex-1 overflow-auto">
          {children}
        </div>
      </main>
    </div>
  </body>
</html>
```

**Implementation Requirements:**
- Copy EXACT layout structure from Open Notebook's `app/layout.tsx`
- Preserve all CSS classes and Tailwind utilities
- Maintain responsive behavior (mobile/desktop transitions)
- Keep the same color scheme and spacing

---

### 2. Notebook Sidebar Component (`components/NotebookSidebar.tsx`)

```typescript
// Features to implement exactly:
interface NotebookSidebarFeatures {
  // Navigation
  notebookList: Notebook[]
  activeNotebook: string | null
  createNotebook: () => void
  selectNotebook: (id: string) => void
  
  // UI States
  isCollapsed: boolean
  toggleCollapse: () => void
  
  // Actions
  renameNotebook: (id: string, name: string) => void
  deleteNotebook: (id: string) => void
  duplicateNotebook: (id: string) => void
  
  // Organization
  searchNotebooks: (query: string) => void
  sortNotebooks: (method: 'name' | 'date' | 'modified') => void
  filterByTags: (tags: string[]) => void
}
```

**Visual Elements to Copy:**
- [ ] Notebook list with icons (📓 icon for each notebook)
- [ ] "New Notebook" button with + icon
- [ ] Search bar for filtering notebooks
- [ ] Active notebook highlighting (blue background)
- [ ] Hover states for each notebook item
- [ ] Context menu (right-click) with options:
  - Rename
  - Duplicate
  - Delete
  - Share
- [ ] Collapse/expand toggle button
- [ ] Empty state message when no notebooks exist

**Styling Requirements:**
```css
/* Copy exact classes from Open Notebook */
.sidebar {
  @apply w-64 bg-gray-900 border-r border-gray-800 flex flex-col;
}

.sidebar-collapsed {
  @apply w-16;
}

.notebook-item {
  @apply px-4 py-3 hover:bg-gray-800 cursor-pointer transition-colors rounded-md mx-2;
}

.notebook-item-active {
  @apply bg-blue-600 text-white;
}
```

---

### 3. Top Navigation Component (`components/TopNavigation.tsx`)

```typescript
interface TopNavigationProps {
  currentView: 'sources' | 'chat' | 'podcast' | 'settings'
  notebookName: string
  onViewChange: (view: string) => void
}
```

**Navigation Tabs (Exact from Open Notebook):**
1. **Sources** 📁 - Manage documents, PDFs, videos, audio, web pages
2. **Chat** 💬 - AI-powered conversation with notebook context
3. **Podcast** 🎙️ - Generate professional podcasts from sources
4. **Settings** ⚙️ - Notebook configuration and preferences

**Visual Requirements:**
- [ ] Tab bar with underline indicator for active tab
- [ ] Notebook name displayed prominently (editable on click)
- [ ] User menu in top-right corner
- [ ] Search functionality for current view
- [ ] Breadcrumb navigation (Notebook Name > Current View)

---

### 4. Sources View (`app/notebook/[id]/sources/page.tsx`)

This is the primary content management interface.

**Layout Structure:**
```
┌─────────────────────────────────────────────────────┐
│  Sources Header                                      │
│  [+ Add Source ▼] [Filter] [Sort] [View: Grid/List] │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐           │
│  │ PDF  │  │Video │  │Audio │  │ Web  │           │
│  │ Doc1 │  │ Lec1 │  │Pod1  │  │ Art1 │           │
│  └──────┘  └──────┘  └──────┘  └──────┘           │
│                                                     │
│  ┌──────┐  ┌──────┐  ┌──────┐                     │
│  │ PDF  │  │ PDF  │  │Video │                     │
│  │ Doc2 │  │ Doc3 │  │ Lec2 │                     │
│  └──────┘  └──────┘  └──────┘                     │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**Features to Implement:**
- [ ] Grid/List view toggle
- [ ] Source cards with:
  - Type icon (PDF, video, audio, web)
  - Thumbnail/preview
  - Title and description
  - Metadata (date added, file size, status)
  - Actions menu (view, edit, delete)
- [ ] Upload area (drag & drop support)
- [ ] Processing status indicators
- [ ] Filtering by source type
- [ ] Sorting options
- [ ] Bulk selection and actions

**Component Example:**
```typescript
// Copy from Open Notebook: components/SourceCard.tsx
interface SourceCardProps {
  source: {
    id: string
    type: 'pdf' | 'video' | 'audio' | 'web' | 'text'
    title: string
    description?: string
    thumbnail?: string
    metadata: {
      size?: number
      duration?: number
      pageCount?: number
      processingStatus: 'pending' | 'processing' | 'ready' | 'error'
    }
  }
  onView: () => void
  onEdit: () => void
  onDelete: () => void
}
```

---

### 5. Chat Interface (`app/notebook/[id]/chat/page.tsx`)

**Layout Structure:**
```
┌─────────────────────────────────────────────────────┐
│  Chat History Sidebar (collapsible)                  │
│  - Previous conversations                            │
│  - New chat button                                   │
├─────────────────────────────────────────────────────┤
│  Main Chat Area                                      │
│  ┌─────────────────────────────────────────────┐    │
│  │ AI: Hello! I've analyzed your sources...    │    │
│  │ [Source Citation 1] [Source Citation 2]     │    │
│  └─────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────┐    │
│  │ User: What are the main themes?            │    │
│  └─────────────────────────────────────────────┘    │
│  ┌─────────────────────────────────────────────┐    │
│  │ AI: Based on your documents, the main...   │    │
│  │ [Source Citation 3]                         │    │
│  └─────────────────────────────────────────────┘    │
├─────────────────────────────────────────────────────┤
│  Input Area                                          │
│  [Type your message...                    ] [Send]   │
│  [📎 Attach] [🎤 Voice] [⚙️ Model Settings]         │
└─────────────────────────────────────────────────────┘
```

**Features to Copy:**
- [ ] Message bubbles (user vs AI distinction)
- [ ] Source citations as clickable badges
- [ ] Streaming response animation
- [ ] Code block syntax highlighting
- [ ] Markdown rendering
- [ ] Copy message button
- [ ] Regenerate response button
- [ ] Model selection dropdown (Esperanto library integration)
- [ ] Context source selector (which sources to include)
- [ ] Voice input support
- [ ] File attachment support

---

### 6. Podcast Generation View (`app/notebook/[id]/podcast/page.tsx`)

**Layout Structure:**
```
┌─────────────────────────────────────────────────────┐
│  Podcast Configuration                               │
│  ┌───────────────────────────────────────────┐      │
│  │ Title: [                                 ]│      │
│  │ Description: [                           ]│      │
│  │ Hosts: [Speaker 1] [Speaker 2]           │      │
│  │ Duration: [○ Short ○ Medium ● Long]      │      │
│  │ Style: [○ Conversational ● Interview]    │      │
│  │ Sources: [✓ Select sources to include]   │      │
│  └───────────────────────────────────────────┘      │
│                                                      │
│  [Generate Podcast] Button                           │
│                                                      │
│  ┌───────────────────────────────────────────┐      │
│  │ Generation Progress                       │      │
│  │ [████████████░░░░░░░] 65%                │      │
│  │ Status: Generating audio script...        │      │
│  └───────────────────────────────────────────┘      │
│                                                      │
│  Generated Podcasts                                  │
│  ┌──────────────────────────────────────────┐       │
│  │ 🎙️ Episode 1: Overview Discussion        │       │
│  │ Duration: 15:30 | Created: 2 days ago    │       │
│  │ [▶ Play] [⬇ Download] [🗑 Delete]        │       │
│  └──────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────┘
```

**Features to Implement:**
- [ ] Podcast configuration form
- [ ] Source selection interface
- [ ] Generation progress indicator
- [ ] Audio player component (play/pause/seek)
- [ ] Download functionality
- [ ] Podcast episode list
- [ ] Transcription viewer
- [ ] Share/export options

---

### 7. Settings View (`app/notebook/[id]/settings/page.tsx`)

**Settings Categories:**

1. **General**
   - Notebook name
   - Description
   - Tags
   - Visibility (private/shared)

2. **AI Configuration**
   - Default AI provider (via Esperanto)
   - Model selection per provider
   - Temperature settings
   - Max tokens
   - System prompts

3. **Processing Settings**
   - Auto-processing new sources
   - OCR language preferences
   - Video transcription settings
   - Audio transcription settings

4. **Search & Indexing**
   - Vector search configuration
   - Full-text search settings
   - Re-index sources button

5. **Integrations**
   - API keys management
   - Webhook configurations
   - Export settings

---

## 🔌 BACKEND API INTEGRATION

### API Endpoints to Connect (FastAPI Backend)

```typescript
// Type definitions matching Open Notebook's API
interface NotebookAPI {
  // Notebooks
  GET    /api/notebooks
  POST   /api/notebooks
  GET    /api/notebooks/:id
  PATCH  /api/notebooks/:id
  DELETE /api/notebooks/:id
  
  // Sources
  GET    /api/notebooks/:id/sources
  POST   /api/notebooks/:id/sources
  GET    /api/notebooks/:id/sources/:sourceId
  PATCH  /api/notebooks/:id/sources/:sourceId
  DELETE /api/notebooks/:id/sources/:sourceId
  POST   /api/notebooks/:id/sources/upload
  
  // Chat
  GET    /api/notebooks/:id/chats
  POST   /api/notebooks/:id/chats
  GET    /api/notebooks/:id/chats/:chatId
  POST   /api/notebooks/:id/chats/:chatId/messages
  
  // Podcast
  GET    /api/notebooks/:id/podcasts
  POST   /api/notebooks/:id/podcasts/generate
  GET    /api/notebooks/:id/podcasts/:podcastId
  DELETE /api/notebooks/:id/podcasts/:podcastId
  
  // Search
  POST   /api/notebooks/:id/search/vector
  POST   /api/notebooks/:id/search/fulltext
  
  // Processing
  GET    /api/notebooks/:id/sources/:sourceId/status
  POST   /api/notebooks/:id/sources/:sourceId/reprocess
}
```

### API Client Setup

```typescript
// lib/api/notebook-client.ts
import axios from 'axios'

const API_BASE_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'http://localhost:8000'

export const notebookAPI = {
  // Notebooks
  getNotebooks: () => 
    axios.get(`${API_BASE_URL}/api/notebooks`),
  
  createNotebook: (data: CreateNotebookDTO) => 
    axios.post(`${API_BASE_URL}/api/notebooks`, data),
  
  getNotebook: (id: string) => 
    axios.get(`${API_BASE_URL}/api/notebooks/${id}`),
  
  updateNotebook: (id: string, data: UpdateNotebookDTO) => 
    axios.patch(`${API_BASE_URL}/api/notebooks/${id}`, data),
  
  deleteNotebook: (id: string) => 
    axios.delete(`${API_BASE_URL}/api/notebooks/${id}`),
  
  // Sources
  uploadSource: (notebookId: string, file: File, metadata?: any) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('metadata', JSON.stringify(metadata))
    return axios.post(
      `${API_BASE_URL}/api/notebooks/${notebookId}/sources/upload`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )
  },
  
  // Chat
  sendMessage: (notebookId: string, chatId: string, message: string) => 
    axios.post(
      `${API_BASE_URL}/api/notebooks/${notebookId}/chats/${chatId}/messages`,
      { message }
    ),
  
  // ... other endpoints
}
```

---

## 🎨 STYLING & DESIGN SYSTEM

### Color Palette (Copy from Open Notebook)

```typescript
// tailwind.config.ts - Exact colors from Open Notebook
module.exports = {
  theme: {
    extend: {
      colors: {
        // Primary colors
        primary: {
          50: '#eff6ff',
          100: '#dbeafe',
          200: '#bfdbfe',
          300: '#93c5fd',
          400: '#60a5fa',
          500: '#3b82f6',  // Main blue
          600: '#2563eb',
          700: '#1d4ed8',
          800: '#1e40af',
          900: '#1e3a8a',
        },
        // Dark theme (default)
        dark: {
          bg: '#0a0a0a',
          surface: '#141414',
          border: '#262626',
          hover: '#1f1f1f',
          text: {
            primary: '#ffffff',
            secondary: '#a3a3a3',
            muted: '#737373',
          }
        }
      }
    }
  }
}
```

### Typography

```css
/* Copy exact font settings from Open Notebook */
h1 { @apply text-3xl font-bold tracking-tight; }
h2 { @apply text-2xl font-semibold tracking-tight; }
h3 { @apply text-xl font-semibold; }
h4 { @apply text-lg font-medium; }
p  { @apply text-base leading-relaxed; }

.text-muted { @apply text-gray-400; }
.text-primary { @apply text-white; }
```

### Component Shadows & Borders

```css
/* Exact shadow and border styles */
.card {
  @apply bg-dark-surface border border-dark-border rounded-lg shadow-lg;
}

.card-hover {
  @apply hover:border-primary-500 hover:shadow-xl transition-all duration-200;
}

.input {
  @apply bg-dark-surface border border-dark-border rounded-md px-3 py-2;
  @apply focus:border-primary-500 focus:ring-1 focus:ring-primary-500;
}
```

---

## 📁 FILE STRUCTURE TO CREATE

```
front_end/jfrontend/
├── app/
│   ├── notebook/
│   │   ├── layout.tsx                  # Main notebook layout
│   │   ├── page.tsx                    # Notebook list/home
│   │   └── [id]/
│   │       ├── layout.tsx              # Single notebook layout
│   │       ├── sources/
│   │       │   └── page.tsx            # Sources view
│   │       ├── chat/
│   │       │   └── page.tsx            # Chat interface
│   │       ├── podcast/
│   │       │   └── page.tsx            # Podcast generation
│   │       └── settings/
│   │           └── page.tsx            # Settings view
│   └── api/
│       └── notebook/                   # API routes proxy
│           ├── [id]/
│           │   ├── route.ts
│           │   ├── sources/
│           │   │   └── route.ts
│           │   ├── chat/
│           │   │   └── route.ts
│           │   └── podcast/
│           │       └── route.ts
│           └── route.ts
│
├── components/
│   ├── notebook/
│   │   ├── NotebookSidebar.tsx         # Main sidebar
│   │   ├── TopNavigation.tsx           # Top nav bar
│   │   ├── SourceCard.tsx              # Source display card
│   │   ├── SourceGrid.tsx              # Grid layout for sources
│   │   ├── SourceList.tsx              # List layout for sources
│   │   ├── ChatMessage.tsx             # Chat message component
│   │   ├── ChatInput.tsx               # Chat input area
│   │   ├── SourceCitation.tsx          # Clickable source badge
│   │   ├── PodcastPlayer.tsx           # Audio player
│   │   ├── PodcastConfiguration.tsx    # Podcast settings form
│   │   └── UploadZone.tsx              # File upload area
│   │
│   └── ui/                             # shadcn/ui components
│       ├── button.tsx
│       ├── card.tsx
│       ├── dialog.tsx
│       ├── dropdown-menu.tsx
│       ├── input.tsx
│       ├── tabs.tsx
│       ├── textarea.tsx
│       └── ... (other shadcn components)
│
├── lib/
│   ├── api/
│   │   ├── notebook-client.ts          # API client
│   │   └── types.ts                    # TypeScript types
│   ├── hooks/
│   │   ├── useNotebook.ts              # Notebook hook
│   │   ├── useSources.ts               # Sources hook
│   │   ├── useChat.ts                  # Chat hook
│   │   └── usePodcast.ts               # Podcast hook
│   └── utils/
│       ├── file-upload.ts              # File handling
│       ├── audio-utils.ts              # Audio processing
│       └── markdown.ts                 # Markdown rendering
│
└── stores/
    └── notebook-store.ts               # Zustand store for notebooks
```

---

## 🚀 IMPLEMENTATION PHASES

### Phase 1: Core Layout & Navigation (Day 1-2)
1. [ ] Create notebook layout structure
2. [ ] Implement NotebookSidebar component
3. [ ] Implement TopNavigation component
4. [ ] Set up routing for notebook views
5. [ ] Add basic state management (Zustand store)
6. [ ] Configure API client base setup

**Success Criteria:**
- Can navigate between different notebook views
- Sidebar shows notebook list (mock data)
- Top navigation shows current view
- Layout is responsive and matches Open Notebook

### Phase 2: Sources View (Day 3-4)
1. [ ] Create SourceCard component
2. [ ] Implement SourceGrid layout
3. [ ] Implement SourceList layout
4. [ ] Add UploadZone component
5. [ ] Connect to backend upload API
6. [ ] Add processing status indicators
7. [ ] Implement filtering and sorting

**Success Criteria:**
- Can upload PDF, video, audio, and web URLs
- Sources display in grid/list view
- Processing status shows correctly
- Can filter and sort sources

### Phase 3: Chat Interface (Day 5-6)
1. [ ] Create ChatMessage component
2. [ ] Implement ChatInput with file attachment
3. [ ] Add SourceCitation component
4. [ ] Connect to streaming chat API
5. [ ] Implement markdown rendering
6. [ ] Add code syntax highlighting
7. [ ] Add voice input support

**Success Criteria:**
- Can send messages and receive AI responses
- Source citations are clickable and highlighted
- Streaming works smoothly
- Markdown and code render correctly

### Phase 4: Podcast Generation (Day 7)
1. [ ] Create PodcastConfiguration component
2. [ ] Implement PodcastPlayer component
3. [ ] Connect to podcast generation API
4. [ ] Add progress tracking
5. [ ] Implement audio download

**Success Criteria:**
- Can configure and generate podcasts
- Progress indicator shows status
- Can play and download generated podcasts

### Phase 5: Settings & Polish (Day 8-9)
1. [ ] Create settings forms
2. [ ] Implement AI provider configuration (Esperanto)
3. [ ] Add search configuration
4. [ ] Polish all animations and transitions
5. [ ] Test responsive behavior
6. [ ] Add loading states everywhere
7. [ ] Add error boundaries

**Success Criteria:**
- All settings can be configured and saved
- UI is polished and smooth
- No console errors
- Works on mobile and desktop

### Phase 6: Integration & Testing (Day 10)
1. [ ] Connect all components to real backend
2. [ ] Test complete workflows
3. [ ] Fix any integration issues
4. [ ] Update documentation
5. [ ] Create user guide

**Success Criteria:**
- All features work end-to-end
- No broken API calls
- Performance is acceptable
- Documentation is complete

---

## ✅ QUALITY CHECKLIST

### Visual Consistency
- [ ] All colors match Open Notebook's design system
- [ ] All spacing and margins are consistent
- [ ] All icons are the same style (Lucide React)
- [ ] All fonts match (Inter or system font)
- [ ] All animations are smooth (200ms standard transitions)
- [ ] Dark theme is implemented correctly

### Component Accuracy
- [ ] NotebookSidebar matches original exactly
- [ ] TopNavigation matches original exactly
- [ ] SourceCard matches original exactly
- [ ] ChatMessage matches original exactly
- [ ] All hover states work correctly
- [ ] All active states are visible

### Functionality
- [ ] All buttons are clickable and do something
- [ ] All forms validate input
- [ ] All API calls have error handling
- [ ] All loading states show spinners
- [ ] All empty states show helpful messages
- [ ] All tooltips are informative

### Responsive Design
- [ ] Mobile view (< 640px) works correctly
- [ ] Tablet view (640-1024px) works correctly
- [ ] Desktop view (> 1024px) works correctly
- [ ] Sidebar collapses on mobile
- [ ] All modals are scrollable on small screens

### Performance
- [ ] Initial page load < 3 seconds
- [ ] Navigation between views is instant
- [ ] Large source lists render quickly (virtualization?)
- [ ] Chat streaming is smooth
- [ ] File uploads show progress

### Accessibility
- [ ] All interactive elements are keyboard accessible
- [ ] All images have alt text
- [ ] All forms have proper labels
- [ ] Color contrast meets WCAG AA standards
- [ ] Focus indicators are visible
- [ ] Screen reader announcements work

---

## 🔍 REFERENCE SOURCES

### Where to Find Original Components

1. **GitHub Repository**: https://github.com/lfnovo/open-notebook
   - Browse `app/` directory for page structures
   - Browse `components/` for UI components
   - Check `lib/` for utilities and hooks

2. **Live Demo**: https://www.open-notebook.ai/
   - Use browser DevTools to inspect elements
   - Copy exact CSS classes
   - Note all interactions and animations

3. **Design Patterns**:
   - shadcn/ui documentation: https://ui.shadcn.com/
   - Radix UI primitives: https://www.radix-ui.com/
   - Tailwind CSS: https://tailwindcss.com/

---

## 💡 KEY IMPLEMENTATION NOTES

### 1. EXACT Visual Replication
- **DO**: Take screenshots of Open Notebook and compare side-by-side
- **DO**: Use browser DevTools to inspect and copy classes
- **DO**: Measure padding, margins, and spacing exactly
- **DON'T**: Approximate or "make it look similar"
- **DON'T**: Change colors "just a little"

### 2. Component Copying Strategy
```typescript
// Good: Copy entire component structure
const NotebookSidebar = () => {
  // Exact state management from original
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')
  
  // Exact return structure
  return (
    <aside className="w-64 bg-gray-900 border-r border-gray-800 flex flex-col">
      {/* Exact component tree */}
    </aside>
  )
}

// Bad: Creating your own version
const Sidebar = () => {
  return <div>My custom sidebar</div>
}
```

### 3. Backend Integration Pattern
```typescript
// Consistent error handling
async function fetchNotebooks() {
  try {
    const response = await notebookAPI.getNotebooks()
    return response.data
  } catch (error) {
    console.error('Failed to fetch notebooks:', error)
    toast.error('Could not load notebooks')
    return []
  }
}
```

### 4. State Management Approach
```typescript
// Use Zustand for global notebook state
interface NotebookStore {
  notebooks: Notebook[]
  activeNotebookId: string | null
  isLoading: boolean
  
  fetchNotebooks: () => Promise<void>
  setActiveNotebook: (id: string) => void
  createNotebook: (name: string) => Promise<void>
  updateNotebook: (id: string, data: Partial<Notebook>) => Promise<void>
  deleteNotebook: (id: string) => Promise<void>
}

export const useNotebookStore = create<NotebookStore>((set, get) => ({
  notebooks: [],
  activeNotebookId: null,
  isLoading: false,
  
  fetchNotebooks: async () => {
    set({ isLoading: true })
    try {
      const notebooks = await notebookAPI.getNotebooks()
      set({ notebooks, isLoading: false })
    } catch (error) {
      set({ isLoading: false })
    }
  },
  
  // ... other methods
}))
```

---

## 🎯 SUCCESS DEFINITION

The implementation is **SUCCESSFUL** when:

1. ✅ A user familiar with Open Notebook can use HARVIS's notebook interface **without noticing any differences**
2. ✅ All visual elements (colors, spacing, fonts, icons) are **pixel-perfect matches**
3. ✅ All interactions (clicks, hovers, transitions) behave **exactly the same**
4. ✅ All features (sources, chat, podcast, settings) have **feature parity**
5. ✅ The interface is the **prominent default view** when opening HARVIS
6. ✅ Backend integration is **seamless and functional**
7. ✅ Performance is **fast and responsive**
8. ✅ Mobile/tablet/desktop views all work **flawlessly**

---

## 📝 DEVELOPMENT WORKFLOW

### Daily Workflow
1. **Morning**: Review Open Notebook UI for the components being built today
2. **Implementation**: Build components matching exactly
3. **Testing**: Compare side-by-side with Open Notebook
4. **Refinement**: Adjust until pixel-perfect
5. **Integration**: Connect to backend APIs
6. **Documentation**: Update progress checklist

### Git Commit Strategy
```bash
# Feature-based commits
git commit -m "feat(notebook): Add NotebookSidebar component matching Open Notebook"
git commit -m "feat(notebook): Implement SourceCard with exact styling"
git commit -m "feat(notebook): Add ChatMessage component with streaming support"

# Integration commits
git commit -m "integrate(notebook): Connect NotebookSidebar to backend API"
git commit -m "integrate(notebook): Wire up source upload to FastAPI"

# Polish commits
git commit -m "polish(notebook): Fix hover states on SourceCard"
git commit -m "polish(notebook): Improve mobile responsiveness"
```

---

## 🛠️ TOOLS & RESOURCES

### Development Tools
- **Next.js DevTools**: For debugging React components
- **React DevTools**: For inspecting component hierarchy
- **Tailwind CSS IntelliSense**: VS Code extension for class completion
- **Browser DevTools**: For inspecting Open Notebook's live site
- **Figma/Sketch**: Optional for design comparison

### Testing Tools
- **Playwright**: For E2E testing
- **Jest**: For unit tests
- **React Testing Library**: For component tests
- **Lighthouse**: For performance audits

### Code Quality
- **ESLint**: Enforce code standards
- **Prettier**: Code formatting
- **TypeScript**: Type checking
- **Husky**: Git hooks for pre-commit checks

---

## 🚨 COMMON PITFALLS TO AVOID

### 1. ❌ "Close Enough" Syndrome
**Problem**: Making components that are "similar" instead of exact copies
**Solution**: Always compare side-by-side with screenshots

### 2. ❌ Over-Engineering
**Problem**: Adding features or abstractions not in Open Notebook
**Solution**: Stick to the original design exactly

### 3. ❌ Ignoring Responsive Behavior
**Problem**: Only testing on desktop
**Solution**: Test on mobile, tablet, and desktop throughout development

### 4. ❌ Skipping Error States
**Problem**: Only building happy path
**Solution**: Implement loading, error, and empty states for everything

### 5. ❌ Inconsistent Spacing
**Problem**: Using arbitrary spacing values
**Solution**: Use Tailwind's spacing scale consistently (p-2, p-4, p-6, etc.)

### 6. ❌ Missing Accessibility
**Problem**: Forgetting keyboard navigation and screen readers
**Solution**: Test with keyboard only and screen reader tools

### 7. ❌ Poor Backend Error Handling
**Problem**: Not handling API failures gracefully
**Solution**: Always use try-catch and show user-friendly errors

---

## 📚 DOCUMENTATION TO CREATE

After implementation, create:

1. **USER_GUIDE.md**: How to use the notebook interface
2. **DEVELOPER_GUIDE.md**: How components are structured and how to extend
3. **API_INTEGRATION.md**: How the frontend connects to backend
4. **COMPONENT_LIBRARY.md**: Catalog of all notebook components
5. **TROUBLESHOOTING.md**: Common issues and solutions

---

## 🎬 FINAL NOTES

This master prompt is designed to be comprehensive enough that an AI assistant can implement the entire Open Notebook UI with minimal ambiguity. The key principles are:

1. **EXACT** replication of visual design
2. **EXACT** replication of interaction patterns  
3. **EXACT** replication of component structure
4. **SEAMLESS** backend integration
5. **PROMINENT** placement in HARVIS interface

Remember: The goal is not to "reimagine" or "improve" Open Notebook's UI, but to **faithfully reproduce it** within the HARVIS AI application. Every pixel, every interaction, every animation should feel like Open Notebook.

When in doubt, **always refer back to the original Open Notebook repository and live demo**.

Good luck! 🚀