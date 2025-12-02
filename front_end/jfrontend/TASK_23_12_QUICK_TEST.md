# Task 23.12 Quick Test Guide

## 30-Second Verification

### Setup
```bash
# If dev server not running:
cd aidev/front_end/jfrontend
npm run dev
```

Navigate to: `http://localhost:3000/ide`

### Visual Check (10 seconds)
1. Look at bottom status bar
2. Find three new toggle buttons (left side of quick actions section)
3. Icons should be: Sidebar, PanelRightClose, PanelBottomClose
4. All should be **blue** (panels visible by default)

### Click Test (10 seconds)
1. Click left panel button → File explorer hides, button turns gray
2. Click right panel button → AI/Execution panel hides, button turns gray
3. Click terminal button → Terminal hides, button turns gray
4. Click all three again → All panels show, buttons turn blue

### Keyboard Test (10 seconds)
1. Press **Ctrl+B** → File explorer toggles
2. Press **Ctrl+Alt+B** → Right panel toggles
3. Press **Ctrl+J** → Terminal toggles

### Persistence Test (Optional - 30 seconds)
1. Hide all three panels
2. Refresh browser (F5)
3. All panels should remain hidden
4. Show all panels
5. Refresh again
6. All panels should be visible

## Expected Results

✅ Three toggle buttons visible in status bar
✅ Buttons change color (blue ↔ gray) when clicked
✅ Panels hide/show smoothly
✅ Keyboard shortcuts work
✅ Panel state persists across refresh

## If Something's Wrong

### Buttons not visible
- Check StatusBar component is receiving props
- Check browser console for errors

### Buttons don't change color
- Verify showLeftPanel/showRightPanel/showTerminal props passed correctly
- Check StatusBar className logic

### Keyboard shortcuts don't work
- Check browser console for errors
- Verify keyboard event listener is attached
- Try clicking buttons instead

### Persistence doesn't work
- Check browser localStorage (DevTools → Application → Local Storage)
- Look for key: `ide-panel-visibility`
- Should contain: `{"showLeftPanel":true,"showRightPanel":true,"showTerminal":true}`

## Success!

If all checks pass, task 23.12 is complete and working correctly.

## Next Task

Proceed to task 23.13: Implement responsive design
