# Ghost Suggestions & Propose Diagnosis

## Issues Found

### 1. **Ghost Suggestions Not Appearing**

**Root Cause**: The MonacoCopilot provider is only responding to `Automatic` triggers, but Monaco may not be generating automatic triggers reliably.

**Evidence**:
- No backend logs show any `/api/ide/copilot/suggest` requests
- Frontend console should show `MonacoCopilot: provideInlineCompletions called` if Monaco is calling the provider
- The provider explicitly ignores `Explicit` triggers (line 166 in MonacoCopilot.tsx)

**Potential Issues**:
1. Monaco isn't generating `Automatic` triggers at all
2. The provider is registered but Monaco doesn't know when to call it
3. The language doesn't match (provider registered for specific language)
4. InlineCompletionsProvider API may require specific Monaco version

### 2. **Propose Feature Does Nothing**

**Root Cause**: Need to check if:
- The frontend is calling the API correctly
- The backend endpoint is registered
- Auth is working
- Response is being handled

**Evidence**:
- No backend logs for `/api/ide/diff/propose` either
- Function `handleProposeDiff` exists and looks correct
- Backend endpoint exists at line 800 of `ide_ai.py`

## Diagnosis Steps

### Step 1: Check if MonacoCopilot is rendering
Open browser console and look for:
```
MonacoCopilot: Registering provider for language: <language>
MonacoCopilot: Provider registered successfully
```

If you DON'T see this, MonacoCopilot component isn't mounting.

### Step 2: Check if Monaco is calling the provider
Type some code and pause. Look for:
```
MonacoCopilot: provideInlineCompletions called
```

If you DON'T see this, Monaco isn't calling the provider at all.

### Step 3: Check network requests
Open DevTools → Network tab
- Filter for "copilot" or "suggest"
- Type code and pause
- See if ANY requests are made

If NO requests, the provider isn't being triggered.

### Step 4: Test manual trigger
Press `Alt+]` (or `Opt+]` on Mac)

Look for:
```
MonacoCopilot: Manual trigger via Alt+]
```

If this works, the provider is registered but automatic triggering isn't working.

### Step 5: Check propose diff
Click the propose changes button or use shortcut
- Check console for errors
- Check network tab for `/api/ide/diff/propose` request
- Check if auth token is included

## Likely Fixes Needed

### Fix 1: Enable Both Automatic AND Explicit Triggers

The provider should respond to BOTH triggers:

```typescript
if (context.triggerKind === monaco.languages.InlineCompletionTriggerKind.Automatic ||
    context.triggerKind === monaco.languages.InlineCompletionTriggerKind.Explicit) {
```

Currently it's ONLY responding to Automatic (line 166).

### Fix 2: Add Explicit Trigger on Typing

Monaco might not be generating automatic triggers. We need to manually trigger on idle:

```typescript
// In MonacoCopilot, add a content change listener
const model = editor.getModel()
if (model) {
  const disposable = model.onDidChangeContent(() => {
    // Debounce and trigger inline suggest
    if (debounceTimerRef.current) {
      clearTimeout(debounceTimerRef.current)
    }
    debounceTimerRef.current = setTimeout(() => {
      editor.getAction('editor.action.inlineSuggest.trigger')?.run()
    }, 600)
  })
}
```

### Fix 3: Check Monaco Version

The InlineCompletionsProvider API was added in Monaco v0.31.0. Check package.json for monaco-editor version.

### Fix 4: Debug Backend Auth

Check if requests are being blocked by auth:
- Open Network tab
- Try propose changes
- Look at request headers - should include Authorization header
- Check response - might be 401/403

### Fix 5: Add Better Error Logging

Add console.error in catch blocks to see actual errors:

```typescript
catch (error: any) {
  console.error('COPILOT ERROR:', error)
  console.error('Error details:', {
    message: error.message,
    stack: error.stack,
    response: error.response
  })
}
```

## Quick Test

Run this in browser console when IDE is open:

```javascript
// Check if MonacoCopilot provider is registered
window.monaco?.languages.getLanguages()

// Try manual trigger
const action = window.monaco?.editor.getEditors()[0]?.getAction('editor.action.inlineSuggest.trigger')
console.log('Inline suggest action:', action)
if (action) {
  action.run()
  console.log('Triggered inline suggest manually')
}

// Check if any providers are registered
console.log('Monaco editors:', window.monaco?.editor.getEditors())
```

## Expected Behavior

1. Type code → pause 600ms → Monaco calls `provideInlineCompletions` with `Automatic` trigger
2. Provider fetches from `/api/ide/copilot/suggest`
3. Backend processes and returns suggestion
4. Ghost text appears in editor
5. Tab accepts, Esc dismisses

## Current Behavior

1. Type code → pause → NOTHING HAPPENS
2. No `provideInlineCompletions` call
3. No API requests
4. No ghost text

This suggests Monaco isn't triggering the provider AT ALL.




