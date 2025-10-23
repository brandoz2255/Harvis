# Task 23.11: User Preferences Flow Diagram

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Browser (IDE Page)                       │
│                                                                  │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              useUserPreferences Hook                    │    │
│  │                                                          │    │
│  │  - Loads preferences on mount                           │    │
│  │  - Debounces saves (500ms)                              │    │
│  │  - Accumulates updates                                  │    │
│  │  - Handles errors                                       │    │
│  └────────────────────────────────────────────────────────┘    │
│                          ↓                                       │
│  ┌────────────────────────────────────────────────────────┐    │
│  │                  IDE Page State                         │    │
│  │                                                          │    │
│  │  - leftPanelWidth: 280                                  │    │
│  │  - rightPanelWidth: 384                                 │    │
│  │  - terminalHeight: 200                                  │    │
│  │  - theme: 'dark'                                        │    │
│  │  - selectedModel: 'mistral'                             │    │
│  └────────────────────────────────────────────────────────┘    │
│                          ↓                                       │
│  ┌────────────────────────────────────────────────────────┐    │
│  │              ResizablePanel Components                  │    │
│  │                                                          │    │
│  │  Left Panel  →  handleLeftPanelResize()                 │    │
│  │  Right Panel →  handleRightPanelResize()                │    │
│  │  Terminal    →  handleTerminalResize()                  │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
                          ↓
                    HTTP POST
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                    Backend API Server                            │
│                                                                  │
│  POST /api/user/prefs                                           │
│  {                                                               │
│    "left_panel_width": 350,                                     │
│    "right_panel_width": 450,                                    │
│    "terminal_height": 300                                       │
│  }                                                               │
└─────────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│                      PostgreSQL Database                         │
│                                                                  │
│  user_prefs table:                                              │
│  ┌──────────┬───────┬──────────────────┬─────────────────┐     │
│  │ user_id  │ theme │ left_panel_width │ right_panel_... │     │
│  ├──────────┼───────┼──────────────────┼─────────────────┤     │
│  │    1     │ dark  │       350        │       450       │     │
│  └──────────┴───────┴──────────────────┴─────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

## Sequence Diagram: Panel Resize

```
User          IDE Page         Handler              Hook              API           Database
 │                │                │                   │                │                │
 │  Drag Panel    │                │                   │                │                │
 │───────────────>│                │                   │                │                │
 │                │                │                   │                │                │
 │                │  onResize(350) │                   │                │                │
 │                │───────────────>│                   │                │                │
 │                │                │                   │                │                │
 │                │                │ setLeftPanelWidth(350)             │                │
 │                │                │──────────────────>│                │                │
 │                │                │                   │                │                │
 │                │  [UI Updates Immediately]          │                │                │
 │                │<──────────────────────────────────>│                │                │
 │                │                │                   │                │                │
 │                │                │ updatePreferences({left_panel_width: 350})          │
 │                │                │──────────────────>│                │                │
 │                │                │                   │                │                │
 │                │                │                   │ [Accumulate]   │                │
 │                │                │                   │ [Start Timer]  │                │
 │                │                │                   │                │                │
 │  [User continues resizing...]   │                   │                │                │
 │                │                │                   │ [Reset Timer]  │                │
 │                │                │                   │                │                │
 │  [User stops]  │                │                   │                │                │
 │                │                │                   │                │                │
 │                │                │                   │ [500ms passes] │                │
 │                │                │                   │                │                │
 │                │                │                   │ POST /api/user/prefs            │
 │                │                │                   │───────────────>│                │
 │                │                │                   │                │                │
 │                │                │                   │                │  UPDATE        │
 │                │                │                   │                │───────────────>│
 │                │                │                   │                │                │
 │                │                │                   │                │  Success       │
 │                │                │                   │                │<───────────────│
 │                │                │                   │                │                │
 │                │                │                   │  200 OK        │                │
 │                │                │                   │<───────────────│                │
 │                │                │                   │                │                │
 │                │                │  [Preferences Saved]               │                │
 │                │                │<──────────────────│                │                │
```

## Sequence Diagram: Page Load

```
User          IDE Page         Hook              API           Database
 │                │               │                │                │
 │  Open /ide     │               │                │                │
 │───────────────>│               │                │                │
 │                │               │                │                │
 │                │  useUserPreferences()          │                │
 │                │──────────────>│                │                │
 │                │               │                │                │
 │                │               │ GET /api/user/prefs             │
 │                │               │───────────────>│                │
 │                │               │                │                │
 │                │               │                │  SELECT        │
 │                │               │                │───────────────>│
 │                │               │                │                │
 │                │               │                │  Results       │
 │                │               │                │<───────────────│
 │                │               │                │                │
 │                │               │  200 OK        │                │
 │                │               │<───────────────│                │
 │                │               │                │                │
 │                │  preferences  │                │                │
 │                │<──────────────│                │                │
 │                │               │                │                │
 │                │  [Apply Preferences]           │                │
 │                │  - setLeftPanelWidth(280)      │                │
 │                │  - setRightPanelWidth(384)     │                │
 │                │  - setTerminalHeight(200)      │                │
 │                │  - setSelectedModel('mistral') │                │
 │                │               │                │                │
 │  [IDE Rendered with Preferences]                │                │
 │<──────────────────────────────────────────────────────────────────│
```

## Component Hierarchy

```
IDEPage
├── useUserPreferences()
│   ├── preferences (state)
│   ├── updatePreferences (function)
│   └── isLoading (state)
│
├── Panel State
│   ├── leftPanelWidth
│   ├── rightPanelWidth
│   ├── terminalHeight
│   ├── showLeftPanel
│   ├── showRightPanel
│   └── showTerminal
│
├── Handlers
│   ├── handleLeftPanelResize()
│   ├── handleRightPanelResize()
│   ├── handleTerminalResize()
│   └── handleThemeToggle()
│
└── Components
    ├── ResizablePanel (Left)
    │   └── onResize={handleLeftPanelResize}
    │
    ├── ResizablePanel (Right)
    │   └── onResize={handleRightPanelResize}
    │
    └── ResizablePanel (Terminal)
        └── onResize={handleTerminalResize}
```

## State Management Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Preferences State                         │
│                                                              │
│  Source: Backend API (/api/user/prefs)                      │
│  Managed by: useUserPreferences hook                         │
│  Persistence: PostgreSQL database                            │
│  Scope: User-level (cross-device)                           │
│                                                              │
│  Data:                                                       │
│  - theme: 'dark' | 'light'                                  │
│  - left_panel_width: number                                 │
│  - right_panel_width: number                                │
│  - terminal_height: number                                  │
│  - default_model: string                                    │
│  - font_size: number                                        │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    Local Component State                     │
│                                                              │
│  Source: React useState                                      │
│  Managed by: IDE Page component                             │
│  Persistence: None (ephemeral)                              │
│  Scope: Component instance                                  │
│                                                              │
│  Data:                                                       │
│  - leftPanelWidth: number (initialized from preferences)    │
│  - rightPanelWidth: number (initialized from preferences)   │
│  - terminalHeight: number (initialized from preferences)    │
│  - selectedModel: string (initialized from preferences)     │
└─────────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────┐
│                    localStorage State                        │
│                                                              │
│  Source: Browser localStorage                                │
│  Managed by: IDE Page component                             │
│  Persistence: Browser storage                                │
│  Scope: Device-specific                                     │
│                                                              │
│  Data:                                                       │
│  - ide-panel-visibility: { showLeft, showRight, showTerm }  │
│  - ide-tabs-{sessionId}: { tabs, activeTabId }             │
│  - ide-terminal-tabs-{sessionId}: { tabs, activeTabId }    │
└─────────────────────────────────────────────────────────────┘
```

## Debouncing Mechanism

```
Time:     0ms    100ms   200ms   300ms   400ms   500ms   600ms   700ms
          │       │       │       │       │       │       │       │
User:     Resize  Resize  Resize  Stop    Wait    Wait    Wait    Wait
          │       │       │       │       │       │       │       │
State:    Update  Update  Update  Update  ─────   ─────   ─────   ─────
          │       │       │       │       │       │       │       │
Timer:    Start   Reset   Reset   Reset   ─────   ─────   ─────   ─────
          │       │       │       │       │       │       │       │
API:      ─────   ─────   ─────   ─────   ─────   Call!   ─────   ─────
                                                   │
                                                   └─> POST /api/user/prefs
                                                       { left_panel_width: 350 }
```

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    Happy Path                                │
│                                                              │
│  User resizes panel                                          │
│    ↓                                                         │
│  State updates immediately (optimistic)                      │
│    ↓                                                         │
│  After 500ms: API call                                       │
│    ↓                                                         │
│  Success: Preferences saved                                  │
│    ↓                                                         │
│  UI remains as-is                                            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    Error Path                                │
│                                                              │
│  User resizes panel                                          │
│    ↓                                                         │
│  State updates immediately (optimistic)                      │
│    ↓                                                         │
│  After 500ms: API call                                       │
│    ↓                                                         │
│  Error: Network failure / Server error                       │
│    ↓                                                         │
│  Hook logs error to console                                  │
│    ↓                                                         │
│  Hook reloads preferences from server                        │
│    ↓                                                         │
│  UI reverts to last saved state                              │
└─────────────────────────────────────────────────────────────┘
```

## Integration Points

```
┌─────────────────────────────────────────────────────────────┐
│                    IDE Page Component                        │
│                                                              │
│  Integrates with:                                            │
│                                                              │
│  1. useUserPreferences Hook                                  │
│     - Provides preferences state                             │
│     - Provides updatePreferences function                    │
│     - Handles debouncing and API calls                       │
│                                                              │
│  2. ResizablePanel Component                                 │
│     - Receives width/height props                            │
│     - Calls onResize callback                                │
│     - Handles drag interactions                              │
│                                                              │
│  3. Backend API                                              │
│     - GET /api/user/prefs (load)                            │
│     - POST /api/user/prefs (save)                           │
│     - Requires JWT authentication                            │
│                                                              │
│  4. localStorage                                             │
│     - Stores panel visibility                                │
│     - Stores open tabs                                       │
│     - Device-specific persistence                            │
│                                                              │
│  5. Command Palette                                          │
│     - Theme toggle command                                   │
│     - Calls handleThemeToggle                                │
│     - Saves to preferences                                   │
└─────────────────────────────────────────────────────────────┘
```

---

**Visual Guide Created**: 2025-10-09
**Purpose**: Illustrate user preferences flow and architecture
**Related Task**: 23.11 Wire user preferences persistence
