# Task 23.8 Verification: Status Bar with Session Info

## Verification Steps

### 1. Visual Verification

#### Start the Development Server
```bash
cd aidev/front_end/jfrontend
npm run dev
```

#### Navigate to IDE
1. Open browser to `http://localhost:3000/ide`
2. Log in if not authenticated
3. Create or select a session

### 2. Session Info Display

**Test: Session Name**
- [ ] Status bar shows "No session" when no session is active
- [ ] Status bar shows session name after selecting a session
- [ ] Session name updates when switching sessions

**Test: Container Status**
- [ ] Container status badge appears next to session name
- [ ] Status shows "Stopped" with red badge initially
- [ ] Status changes to "Starting" with yellow badge when starting container
- [ ] Status changes to "Running" with green badge when container is running
- [ ] Status updates automatically every 5 seconds (watch for changes)

### 3. File Information Display

**Test: File Selection**
- [ ] No file info shown when no file is selected
- [ ] File name appears when a file is selected from explorer
- [ ] File icon (📄) appears next to file name

**Test: Dirty Indicator**
- [ ] No yellow dot when file is first opened
- [ ] Yellow dot (●) appears after editing file
- [ ] Yellow dot disappears after file is saved

**Test: Language Display**
- [ ] Language shows correctly for .py files (python)
- [ ] Language shows correctly for .js files (javascript)
- [ ] Language shows correctly for .ts files (typescript)
- [ ] Language shows correctly for .md files (markdown)

### 4. Cursor Position Tracking

**Test: Cursor Position Display**
- [ ] Shows "Ln 1, Col 1" when file is first opened
- [ ] Line number updates when moving cursor up/down
- [ ] Column number updates when moving cursor left/right
- [ ] Position updates in real-time as you type
- [ ] Position format is "Ln X, Col Y" in monospace font

**Test: Cursor Movement**
1. Open a file with multiple lines
2. Click on different positions in the editor
3. Verify status bar updates immediately
4. Use arrow keys to move cursor
5. Verify status bar tracks movement

### 5. Theme and Font Size Display

**Test: Theme Indicator**
- [ ] Shows moon icon (🌙) for dark theme
- [ ] Shows "dark" text next to icon
- [ ] Theme indicator is visible and readable

**Test: Font Size Display**
- [ ] Shows font size (e.g., "14px")
- [ ] Font size matches actual editor font size
- [ ] Type icon (T) appears next to font size

### 6. Quick Action Buttons

**Test: Command Palette Button**
- [ ] Command icon (⌘) button is visible
- [ ] Button has hover effect (background changes)
- [ ] Tooltip shows "Command Palette (Ctrl+Shift+P)"
- [ ] Clicking logs "Command palette clicked" to console

**Test: Theme Toggle Button**
- [ ] Sun icon (☀️) button is visible in dark theme
- [ ] Button has hover effect
- [ ] Tooltip shows "Toggle Theme"
- [ ] Clicking button toggles theme (currently just updates preference)
- [ ] Icon changes after toggle (moon ↔ sun)

**Test: Settings Button**
- [ ] Settings icon (⚙️) button is visible
- [ ] Button has hover effect
- [ ] Tooltip shows "Settings"
- [ ] Clicking logs "Settings clicked" to console

### 7. Real-time Container Status Updates

**Test: Automatic Polling**
1. Open browser console (F12)
2. Watch network tab for requests to `/api/vibecode/container/{sessionId}/status`
3. Verify requests occur every 5 seconds
4. Start/stop container and watch status update automatically

**Test: Status Transitions**
- [ ] Status changes from "Stopped" to "Starting" when starting container
- [ ] Status changes from "Starting" to "Running" after container starts
- [ ] Status changes from "Running" to "Stopping" when stopping container
- [ ] Status changes from "Stopping" to "Stopped" after container stops
- [ ] Spinner icon appears during "Starting" and "Stopping" states

### 8. Layout and Styling

**Test: Visual Appearance**
- [ ] Status bar is at the bottom of the IDE
- [ ] Status bar has dark gray background
- [ ] Status bar has border on top
- [ ] Text is small and readable
- [ ] Left and right sections are properly aligned
- [ ] Separators (|) are visible between items
- [ ] Status bar height is 24px (h-6)

**Test: Responsive Behavior**
- [ ] Status bar stays at bottom when resizing window
- [ ] Text doesn't overflow or wrap
- [ ] All elements remain visible at different window sizes

### 9. Integration with IDE

**Test: State Synchronization**
- [ ] Status bar updates when switching between editor tabs
- [ ] Status bar updates when opening new files
- [ ] Status bar updates when closing files
- [ ] Status bar updates when session changes
- [ ] Status bar updates when container status changes

**Test: User Preferences**
- [ ] Theme from preferences is displayed correctly
- [ ] Font size from preferences is displayed correctly
- [ ] Theme toggle saves to preferences
- [ ] Preferences persist after page reload

### 10. Error Handling

**Test: Missing Data**
- [ ] Status bar handles missing session gracefully
- [ ] Status bar handles missing file gracefully
- [ ] Status bar handles missing preferences gracefully

**Test: API Errors**
- [ ] Status bar handles container status API errors
- [ ] Status bar continues to function if polling fails
- [ ] No console errors when API is unavailable

## Expected Results

### Visual Layout
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ Session: my-project | Container: 🟢 Running | 📄 main.py | python | Ln 42, Col 15 │
│                                                                               │
│                                    🌙 dark | T 14px | ⌘ ☀️ ⚙️                │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Container Status Colors
- 🟢 **Running**: Green background, green text
- 🔴 **Stopped**: Red background, red text
- 🟡 **Starting**: Yellow background, yellow text, spinner
- 🟠 **Stopping**: Orange background, orange text, spinner

### Cursor Position Format
- Format: `Ln {line}, Col {column}`
- Example: `Ln 1, Col 1`, `Ln 42, Col 15`
- Font: Monospace

## Manual Testing Script

```bash
# 1. Start the application
cd aidev/front_end/jfrontend
npm run dev

# 2. Open browser
open http://localhost:3000/ide

# 3. Test sequence:
# - Log in
# - Create/select a session
# - Verify session name appears in status bar
# - Start container
# - Watch status change from Stopped → Starting → Running
# - Open a file from explorer
# - Verify file name appears in status bar
# - Type some text
# - Verify dirty indicator (●) appears
# - Move cursor around
# - Verify cursor position updates in real-time
# - Click theme toggle button
# - Verify theme indicator updates
# - Open browser console
# - Click command palette button
# - Verify "Command palette clicked" appears in console
# - Click settings button
# - Verify "Settings clicked" appears in console
```

## Success Criteria

All checkboxes above should be checked (✓) for the task to be considered complete.

### Critical Features (Must Pass)
- ✅ Session name displays correctly
- ✅ Container status shows with correct colors
- ✅ Container status updates in real-time
- ✅ File name displays when selected
- ✅ Cursor position tracks in real-time
- ✅ Theme and font size display correctly
- ✅ Quick action buttons are functional

### Nice-to-Have Features (Should Pass)
- ✅ Dirty indicator works
- ✅ Language detection works
- ✅ Hover effects on buttons
- ✅ Tooltips show on hover
- ✅ Status bar layout is clean and professional

## Known Limitations

1. **Command Palette**: Button is a placeholder for Task 23.9
2. **Settings Modal**: Button is a placeholder for future implementation
3. **Theme Toggle**: Currently only updates preference, full theme switching may require additional work

## Next Steps After Verification

If all tests pass:
1. Mark task 23.8 as complete
2. Update tasks.md
3. Proceed to task 23.9 (Command Palette)

If tests fail:
1. Document failures
2. Fix issues
3. Re-run verification
