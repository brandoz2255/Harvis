# IDE AI Features Explained

## What Each Feature Does

### 1. **Inline Suggestions (formerly "Copilot")**

**What it does:**
- As you type code in the Monaco editor, after a 600ms pause, it automatically shows gray/ghost text suggestions
- These suggestions appear right at your cursor position
- **Accept**: Press `Tab` to accept the suggestion
- **Dismiss**: Press `Esc` or just continue typing

**How it works:**
- Uses Monaco's `InlineCompletionsProvider` API
- Calls `/api/ide/copilot/suggest` endpoint with your current code context
- Backend uses a fast code model (like `deepseek-coder:6.7b`) optimized for quick completions
- Suggestions are debounced (600ms) to avoid excessive API calls

**Where to control it:**
- In the **AI Assistant** panel (right side), look for "Suggestion Model" section
- Toggle "Suggestions ON/OFF" button
- Select which model to use (DeepSeek Coder, Code Llama, etc.)

**What was broken:**
1. Variable name conflict: `model` parameter was shadowing the prop
2. Monaco inline completions weren't explicitly enabled in editor config
3. Missing error handling and debugging

**What I fixed:**
- Renamed function parameter from `model` to `editorModel` to avoid conflict
- Added `inlineSuggest: { enabled: true }` to Monaco editor options
- Added console logging to help debug issues
- Fixed dependency array to include `model` prop
- Added better error handling

---

### 2. **Auto-Propose Changes**

**What it does:**
- **TODO Comment Detection**: When you type a comment like `// TODO: add error handling`, it automatically detects it after 1 second and opens a diff viewer with proposed changes
- **AI Assistant Auto-Propose**: When the AI Assistant responds with code (and you asked for code changes), it automatically opens a diff viewer

**How it works:**

**TODO Detection:**
- Monitors editor content changes
- Detects patterns: `// TODO:`, `# TODO:`, `/* TODO: */`, `// FIXME:`, `// AI:`
- Extracts the instruction from the comment
- Calls `handleProposeDiff()` to show side-by-side diff
- Debounced by 1000ms to avoid triggering while typing

**AI Assistant Auto-Propose:**
- After AI finishes streaming response, checks if:
  1. Auto-propose is enabled (checkbox in AI Assistant header)
  2. Response contains code blocks (```) or coding keywords
  3. User's message asked for code changes (keywords like "write", "create", "add", etc.)
- If all conditions met, automatically opens diff viewer

**Where to control it:**
- In the **AI Assistant** panel header, there's an "Auto-propose" checkbox
- Default: **enabled** (checked)
- Uncheck to disable automatic proposals

**What was broken:**
- Auto-propose wasn't checking the `autoProposeEnabled` state variable
- It was only checking localStorage, which might be out of sync

**What I fixed:**
- Now properly checks `autoProposeEnabled` state before triggering
- Added the check at the beginning of the auto-detect logic

---

## How to Test

### Test Inline Suggestions:
1. Open a file in the editor (e.g., `test.py`)
2. Make sure "Suggestions" is **ON** in AI Assistant panel
3. Start typing some code, like:
   ```python
   def calculate_sum(a, b):
       return
   ```
4. Pause for 600ms after typing `return`
5. You should see gray ghost text suggesting completion
6. Press `Tab` to accept, or `Esc` to dismiss

**Check browser console** (F12) for debug logs:
- `MonacoCopilot: Registering provider for language: python`
- `MonacoCopilot: provideInlineCompletions called`
- `MonacoCopilot: Fetching suggestion...`
- `MonacoCopilot: Got suggestions: 1`

### Test TODO Auto-Propose:
1. Make sure "Auto-propose" checkbox is checked in AI Assistant
2. Type in editor: `// TODO: add error handling`
3. Wait 1 second
4. Diff viewer should automatically open with proposed changes

**Check browser console** for:
- `🔍 Detected TODO comment: add error handling`

### Test AI Assistant Auto-Propose:
1. Make sure "Auto-propose" checkbox is checked
2. In AI Assistant, type: "Add error handling to the main function"
3. Wait for AI response (should contain code)
4. Diff viewer should automatically open

---

## Troubleshooting

### Inline Suggestions Not Appearing:
1. Check browser console (F12) for errors
2. Verify "Suggestions" is **ON** in AI Assistant panel
3. Make sure you have a file open and are typing
4. Wait 600ms after typing (pause briefly)
5. Check if backend model is available: `docker exec ollama ollama list`
6. Verify session is active and authenticated

### Auto-Propose Not Working:
1. Check "Auto-propose" checkbox is enabled in AI Assistant header
2. For TODO detection: Make sure comment format is correct (`// TODO: instruction`)
3. Wait 1 second after typing the comment
4. Check browser console for detection logs
5. For AI Assistant: Make sure your message asks for code changes (use words like "add", "create", "implement")

### Common Issues:
- **"Model not found"**: Pull the model: `docker exec ollama ollama pull deepseek-coder:6.7b`
- **No suggestions appearing**: Check browser console, verify backend is running, check network tab for API calls
- **Suggestions too slow**: Try a smaller model (e.g., `deepseek-coder:1.3b`)

---

## Technical Details

### Backend Endpoint:
- `/api/ide/copilot/suggest` - Returns inline code suggestions
- Uses `COMPLETION_MODEL` (default: `deepseek-coder:6.7b`)
- Optimized parameters: `temperature=0.2`, `top_p=0.15`, `top_k=5`

### Frontend Components:
- `MonacoCopilot.tsx` - Registers inline completions provider
- `AIAssistant.tsx` - Contains auto-propose logic
- `page.tsx` - Contains TODO detection logic

### Configuration:
- Model selection stored in `localStorage: copilot_model`
- Auto-propose preference stored in `localStorage: auto_propose_enabled`
- Debounce timing: 600ms for inline suggestions, 1000ms for TODO detection





