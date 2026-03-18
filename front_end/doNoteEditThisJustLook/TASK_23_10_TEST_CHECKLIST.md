# Task 23.10 Test Checklist: Global Keyboard Shortcuts

## Quick Test Guide

### Prerequisites
- [ ] Navigate to `/ide` route
- [ ] Have an active VibeCode session
- [ ] Container is running
- [ ] At least one file is open in the editor

## Keyboard Shortcuts Test

### 1. Command Palette (Ctrl/Cmd+Shift+P)
- [ ] Press `Ctrl+Shift+P` (Windows/Linux) or `Cmd+Shift+P` (macOS)
- [ ] Command palette modal opens
- [ ] Search input is focused
- [ ] Browser print dialog does NOT open
- [ ] Can search and execute commands

**Result:** ✅ PASS / ❌ FAIL

---

### 2. Save File (Ctrl/Cmd+S)
- [ ] Open a file in the editor
- [ ] Make changes to the file
- [ ] Press `Ctrl+S` (Windows/Linux) or `Cmd+S` (macOS)
- [ ] Save button shows "Saving..." then "Saved"
- [ ] File is saved to backend
- [ ] Browser save dialog does NOT open
- [ ] Tab dirty indicator clears

**Result:** ✅ PASS / ❌ FAIL

---

### 3. Toggle Left Sidebar (Ctrl/Cmd+B)
- [ ] Left sidebar (file explorer) is visible
- [ ] Press `Ctrl+B` (Windows/Linux) or `Cmd+B` (macOS)
- [ ] Left sidebar hides smoothly
- [ ] Press shortcut again
- [ ] Left sidebar shows again
- [ ] Browser bookmarks bar does NOT toggle
- [ ] File tree state is preserved

**Result:** ✅ PASS / ❌ FAIL

---

### 4. Toggle Terminal (Ctrl/Cmd+J)
- [ ] Terminal panel is visible at bottom
- [ ] Press `Ctrl+J` (Windows/Linux) or `Cmd+J` (macOS)
- [ ] Terminal panel hides smoothly
- [ ] Press shortcut again
- [ ] Terminal panel shows again
- [ ] Browser downloads panel does NOT open
- [ ] Terminal content is preserved
- [ ] Active terminal tab is maintained

**Result:** ✅ PASS / ❌ FAIL

---

### 5. Focus Terminal (Ctrl/Cmd+`)
- [ ] Click in the editor to focus it
- [ ] Press `Ctrl+\`` (Windows/Linux) or `Cmd+\`` (macOS)
- [ ] Terminal panel becomes visible (if hidden)
- [ ] Terminal input receives focus
- [ ] Cursor is blinking in terminal input
- [ ] Start typing - characters appear in terminal
- [ ] No console errors

**Result:** ✅ PASS / ❌ FAIL

---

## Edge Cases Test

### 6. Save with No Active File
- [ ] Close all editor tabs
- [ ] Press `Ctrl/Cmd+S`
- [ ] Nothing happens (graceful no-op)
- [ ] No console errors
- [ ] No visual glitches

**Result:** ✅ PASS / ❌ FAIL

---

### 7. Focus Terminal When Hidden
- [ ] Hide terminal with `Ctrl/Cmd+J`
- [ ] Press `Ctrl/Cmd+\``
- [ ] Terminal shows and receives focus
- [ ] Input is ready for typing

**Result:** ✅ PASS / ❌ FAIL

---

### 8. Multiple Shortcuts in Sequence
- [ ] Press `Ctrl/Cmd+B` (hide left sidebar)
- [ ] Press `Ctrl/Cmd+J` (hide terminal)
- [ ] Press `Ctrl/Cmd+Shift+P` (open command palette)
- [ ] Close command palette
- [ ] Press `Ctrl/Cmd+\`` (show and focus terminal)
- [ ] Press `Ctrl/Cmd+B` (show left sidebar)
- [ ] All actions work correctly
- [ ] No conflicts or errors

**Result:** ✅ PASS / ❌ FAIL

---

### 9. Rapid Shortcut Presses
- [ ] Rapidly press `Ctrl/Cmd+B` multiple times
- [ ] Panel toggles smoothly without glitches
- [ ] Rapidly press `Ctrl/Cmd+S` multiple times
- [ ] Save handles multiple requests gracefully
- [ ] No console errors

**Result:** ✅ PASS / ❌ FAIL

---

## Cross-Platform Test

### 10. Windows/Linux (Ctrl Key)
- [ ] All shortcuts work with Ctrl key
- [ ] `Ctrl+Shift+P` opens command palette
- [ ] `Ctrl+S` saves file
- [ ] `Ctrl+B` toggles left sidebar
- [ ] `Ctrl+J` toggles terminal
- [ ] `Ctrl+\`` focuses terminal

**Result:** ✅ PASS / ❌ FAIL

---

### 11. macOS (Cmd Key)
- [ ] All shortcuts work with Cmd key
- [ ] `Cmd+Shift+P` opens command palette
- [ ] `Cmd+S` saves file
- [ ] `Cmd+B` toggles left sidebar
- [ ] `Cmd+J` toggles terminal
- [ ] `Cmd+\`` focuses terminal

**Result:** ✅ PASS / ❌ FAIL

---

## Browser Default Prevention Test

### 12. No Browser Defaults Triggered
- [ ] `Ctrl/Cmd+S` does NOT open browser save dialog
- [ ] `Ctrl/Cmd+B` does NOT toggle browser bookmarks
- [ ] `Ctrl/Cmd+Shift+P` does NOT open browser print dialog
- [ ] `Ctrl/Cmd+J` does NOT open browser downloads
- [ ] Only IDE actions are performed

**Result:** ✅ PASS / ❌ FAIL

---

## Performance Test

### 13. Response Time
- [ ] Shortcuts respond in < 100ms
- [ ] No noticeable lag
- [ ] Smooth animations
- [ ] No frame drops

**Result:** ✅ PASS / ❌ FAIL

---

### 14. Memory Leaks
- [ ] Open browser DevTools → Performance → Memory
- [ ] Take heap snapshot
- [ ] Use shortcuts multiple times
- [ ] Take another heap snapshot
- [ ] Compare - no significant memory increase
- [ ] Event listeners are cleaned up

**Result:** ✅ PASS / ❌ FAIL

---

## Console Errors Test

### 15. No Console Errors
- [ ] Open browser DevTools → Console
- [ ] Clear console
- [ ] Use all shortcuts multiple times
- [ ] No errors in console
- [ ] No warnings in console

**Result:** ✅ PASS / ❌ FAIL

---

## Integration Test

### 16. Works with Other Features
- [ ] Shortcuts work while file tree is loading
- [ ] Shortcuts work while AI is processing
- [ ] Shortcuts work while code is executing
- [ ] Shortcuts work with session manager open
- [ ] Shortcuts work with command palette open

**Result:** ✅ PASS / ❌ FAIL

---

## Accessibility Test

### 17. Keyboard Navigation
- [ ] Can navigate entire IDE with keyboard
- [ ] Tab order is logical
- [ ] Focus indicators are visible
- [ ] Shortcuts don't break tab navigation

**Result:** ✅ PASS / ❌ FAIL

---

## Summary

### Total Tests: 17
- **Passed:** ___
- **Failed:** ___
- **Skipped:** ___

### Critical Issues Found
(List any critical issues that prevent the feature from working)

### Minor Issues Found
(List any minor issues or improvements needed)

### Overall Status
- [ ] ✅ All tests passed - Ready for production
- [ ] ⚠️ Minor issues found - Can proceed with notes
- [ ] ❌ Critical issues found - Needs fixes

### Tester Information
- **Name:** _______________
- **Date:** _______________
- **Browser:** _______________
- **OS:** _______________
- **Build Version:** _______________

### Notes
(Add any additional observations or comments)

---

## Quick Reference: Keyboard Shortcuts

```
Ctrl/Cmd+Shift+P  →  Open Command Palette
Ctrl/Cmd+S        →  Save File
Ctrl/Cmd+B        →  Toggle File Explorer
Ctrl/Cmd+J        →  Toggle Terminal
Ctrl/Cmd+`        →  Focus Terminal
```

## Expected Behavior Summary

1. **Command Palette**: Opens modal, focuses search input
2. **Save File**: Saves active tab, shows status indicator
3. **Toggle Left Sidebar**: Shows/hides file explorer smoothly
4. **Toggle Terminal**: Shows/hides terminal panel smoothly
5. **Focus Terminal**: Shows terminal and focuses input field

All shortcuts should:
- Prevent browser default actions
- Work on Windows/Linux (Ctrl) and macOS (Cmd)
- Respond quickly (< 100ms)
- Handle edge cases gracefully
- Not cause console errors
