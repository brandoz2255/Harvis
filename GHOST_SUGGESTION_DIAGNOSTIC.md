# Ghost Suggestion Diagnostic Guide

## Step 1: Check Frontend Logs

Open the IDE page (`http://localhost:9000/ide`) and open DevTools Console.

Look for these logs when the editor loads:
```
✅ MonacoCopilot: Registering provider for language: python
✅ MonacoCopilot: Provider registered successfully for python
✅ MonacoCopilot: Setup complete
🧪 MonacoCopilot: Post-setup diagnostic
```

If you see `⚠️ MonacoCopilot: Not enabled`, check:
- Is Inline Suggestions toggle ON in the AI Assistant panel?
- Is there an active session?

## Step 2: Run Browser Console Diagnostic

Paste this in your browser console while on the IDE page:

```javascript
// Comprehensive Monaco Inline Suggestions Diagnostic
const editor = window.monaco?.editor?.getEditors()[0];
if (!editor) {
  console.error('❌ No editor found');
} else {
  const model = editor.getModel();
  const inlineSuggestConfig = editor.getOption(55); // EditorOption.inlineSuggest
  
  console.log('=== MONACO INLINE SUGGESTIONS DIAGNOSTIC ===');
  console.log('📊 Editor:', {
    hasEditor: !!editor,
    hasModel: !!model,
    language: model?.getLanguageId(),
    contentLength: model?.getValue()?.length
  });
  
  console.log('📊 InlineSuggest Config:', inlineSuggestConfig);
  
  const actions = {
    trigger: editor.getAction('editor.action.inlineSuggest.trigger'),
    accept: editor.getAction('editor.action.inlineSuggest.accept'),
    hide: editor.getAction('editor.action.inlineSuggest.hide')
  };
  
  console.log('📊 Actions:', {
    trigger: { exists: !!actions.trigger, supported: actions.trigger?.isSupported?.() },
    accept: { exists: !!actions.accept, supported: actions.accept?.isSupported?.() },
    hide: { exists: !!actions.hide, supported: actions.hide?.isSupported?.() }
  });
  
  // Try manual trigger
  console.log('🧪 Attempting manual trigger...');
  if (actions.trigger && actions.trigger.isSupported?.()) {
    actions.trigger.run().then(() => {
      console.log('✅ Manual trigger completed');
    }).catch(err => {
      console.error('❌ Manual trigger failed:', err);
    });
  } else {
    console.error('❌ Trigger action not supported!');
  }
}
```

## Step 3: Check Backend Logs

In a terminal, run:
```bash
docker logs -f backend | grep -E "🤖|✅|❌|copilot"
```

Then type in the IDE editor and wait 1 second. You should see:
```
INFO: 🤖 Querying Ollama for code suggestion with model: qwen2.5-coder:7b
INFO: ✅ Ollama returned suggestion: XX chars
```

If you see no logs, the frontend isn't calling the backend.

## Step 4: Test Backend Directly

Get your JWT token from DevTools → Application → Cookies → `access_token`, then run:

```bash
TOKEN="your-token-here"
curl -X POST http://localhost:9000/api/ide/copilot/suggest \
  -H "Content-Type: application/json" \
  -H "Cookie: access_token=$TOKEN" \
  -d '{
    "session_id": "your-session-id",
    "filepath": "test.py",
    "language": "python",
    "content": "def hello():\n    print(",
    "cursor_offset": 25,
    "model": "qwen2.5-coder:7b"
  }'
```

Expected response:
```json
{
  "suggestion": "\"Hello, World!\")",
  "range": {"start": 25, "end": 25}
}
```

## Step 5: Check Model Availability

```bash
docker exec backend curl http://ollama:11434/api/tags
```

Make sure `qwen2.5-coder:7b` is in the list. If not:
```bash
docker exec backend ollama pull qwen2.5-coder:7b
```

## Common Issues

### Issue: "Trigger action not supported"
**Fix**: Monaco's inline suggestion feature isn't loaded. Check:
1. Is the import correct? `import 'monaco-editor/esm/vs/editor/contrib/inlineCompletions/browser/inlineCompletions.contribution'`
2. Did the frontend build successfully?

### Issue: Provider never called
**Fix**: Provider might be registered for wrong language. Check:
1. What language is shown in diagnostic? (should match file extension)
2. Is the provider registered for `*` (all languages)?

### Issue: Backend returns empty suggestion
**Fix**: Model might not be loaded or responding. Check:
1. Run `docker exec backend ollama list` to see loaded models
2. Check Ollama logs: `docker logs ollama`

### Issue: Frontend never calls backend
**Fix**: 
1. Check network tab in DevTools for `/api/ide/copilot/suggest` calls
2. Check if MonacoCopilot component is mounted
3. Check if enabled toggle is ON

## Expected Flow (When Working)

1. ✅ User types in editor
2. ✅ 600ms passes with no typing
3. ✅ MonacoCopilot content change listener triggers
4. ✅ Console: "MonacoCopilot: Content changed, triggering inline suggestion"
5. ✅ Console: "MonacoCopilot: provideInlineCompletions called"
6. ✅ Console: "🌐 MonacoCopilot: Calling getSuggestion()"
7. ✅ Backend: "🤖 Querying Ollama..."
8. ✅ Backend: "✅ Ollama returned suggestion"
9. ✅ Console: "✨ MonacoCopilot: Returning ghost suggestion"
10. ✅ Ghost text appears in editor (Tab to accept, Esc to dismiss)

## Contact Points

If diagnostics show everything working but no ghost text:
- Check if Monaco version supports inline completions
- Try registering provider for `'*'` instead of specific language
- Check if there's a CSS issue hiding the ghost text



