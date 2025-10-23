# Task 23.11: Quick Test Guide

## 🚀 Quick Start Testing

### Prerequisites
1. Backend server running (`docker-compose up` or similar)
2. Frontend dev server running (`npm run dev`)
3. User account created and logged in
4. Browser DevTools open (F12)

## ⚡ 5-Minute Test

### Test 1: Panel Resize Persistence (2 min)
```
1. Open http://localhost:3000/ide
2. Select any session
3. Drag left panel to make it wider (~350px)
4. Wait 1 second
5. Press F5 to refresh
6. ✅ Left panel should be ~350px wide
```

### Test 2: Debouncing (1 min)
```
1. Open DevTools → Network tab
2. Filter for "prefs"
3. Rapidly resize left panel back and forth for 2 seconds
4. Stop and wait 1 second
5. ✅ Should see only 1 POST request to /api/user/prefs
```

### Test 3: Theme Toggle (1 min)
```
1. Click theme toggle in status bar (or Ctrl+Shift+P → "Toggle Theme")
2. Wait 1 second
3. Press F5 to refresh
4. ✅ Theme should persist (check console for "Applied theme from preferences")
```

### Test 4: Panel Visibility (1 min)
```
1. Press Ctrl+B to hide left panel
2. Press Ctrl+J to hide terminal
3. Press F5 to refresh
4. ✅ Panels should still be hidden
5. Press Ctrl+B and Ctrl+J to show them again
6. Press F5 to refresh
7. ✅ Panels should still be visible
```

## 🔍 What to Look For

### In Browser Console
```javascript
// On page load, you should see:
Applied theme from preferences: dark

// No errors should appear
```

### In Network Tab
```
// After resizing a panel and waiting 500ms:
POST /api/user/prefs
Status: 200 OK
Response: { user_id: 1, left_panel_width: 350, ... }
```

### In localStorage
```javascript
// Open console and run:
JSON.parse(localStorage.getItem('ide-panel-visibility'))
// Should show: { showLeftPanel: true, showRightPanel: true, showTerminal: true }
```

## ✅ Success Criteria

All of these should be true:
- [ ] Panel sizes persist across refresh
- [ ] Only 1 API call after rapid resizing
- [ ] Theme persists across refresh
- [ ] Panel visibility persists across refresh
- [ ] No errors in console
- [ ] No TypeScript errors
- [ ] Build succeeds (`npm run build`)

## ❌ Common Issues

### Issue: Preferences don't persist
**Check:**
- Is backend running?
- Is user logged in? (check localStorage for 'token')
- Are there errors in console?
- Is `/api/user/prefs` endpoint working?

**Fix:**
```bash
# Test API manually
curl -X GET http://localhost:9000/api/user/prefs \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Issue: Too many API calls
**Check:**
- Are you waiting 500ms after resizing?
- Is debouncing working?

**Fix:**
- Check Network tab timing
- Verify hook is using debounce correctly

### Issue: Panel sizes reset to defaults
**Check:**
- Are preferences loading?
- Is the effect running?
- Are there errors in console?

**Fix:**
- Check console for "Applied theme from preferences"
- Verify preferences object is not null

## 🐛 Debugging Commands

### Check if preferences are loading
```javascript
// In browser console:
console.log('Preferences:', window.localStorage.getItem('token'))
```

### Check API response
```bash
# Get your token from localStorage
TOKEN="your_token_here"

# Test GET endpoint
curl -X GET http://localhost:9000/api/user/prefs \
  -H "Authorization: Bearer $TOKEN"

# Test POST endpoint
curl -X POST http://localhost:9000/api/user/prefs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"left_panel_width": 350}'
```

### Check localStorage
```javascript
// In browser console:
// Check panel visibility
console.log('Panel visibility:', 
  JSON.parse(localStorage.getItem('ide-panel-visibility')))

// Check all IDE-related keys
console.log('IDE keys:', 
  Object.keys(localStorage).filter(k => k.startsWith('ide-')))
```

## 📊 Performance Check

### Check for excessive re-renders
```
1. Install React DevTools extension
2. Open React DevTools → Profiler
3. Click "Record"
4. Resize a panel
5. Stop recording
6. ✅ Should see minimal re-renders (only affected components)
```

### Check for memory leaks
```
1. Open DevTools → Memory tab
2. Take heap snapshot
3. Resize panels 10 times
4. Take another heap snapshot
5. Compare snapshots
6. ✅ Should see no significant memory increase
```

## 📝 Test Results Template

```
Date: ___________
Tester: ___________

Test 1: Panel Resize Persistence
[ ] PASS  [ ] FAIL
Notes: _________________________________

Test 2: Debouncing
[ ] PASS  [ ] FAIL
Notes: _________________________________

Test 3: Theme Toggle
[ ] PASS  [ ] FAIL
Notes: _________________________________

Test 4: Panel Visibility
[ ] PASS  [ ] FAIL
Notes: _________________________________

Overall Status: [ ] PASS  [ ] FAIL
Issues Found: _________________________________
```

## 🎯 Next Steps After Testing

### If All Tests Pass ✅
1. Mark task as verified in TASK_23_11_VERIFICATION.md
2. Update TASK_23_11_SUMMARY.md with test results
3. Commit changes with message: "feat: implement user preferences persistence (task 23.11)"
4. Move to next task (23.12)

### If Tests Fail ❌
1. Document issues in TASK_23_11_VERIFICATION.md
2. Debug using commands above
3. Fix issues
4. Re-test
5. Update documentation

---

**Quick Test Guide Created**: 2025-10-09
**Estimated Time**: 5 minutes
**Difficulty**: Easy
