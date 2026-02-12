# Copilot-Style Code Propose Flow - Implementation Plan

## Current Status ✅

### What Already Works:
1. **DiffMerge Component** - Monaco DiffEditor with Accept/Reject buttons
2. **Frontend State Management** - `showDiffView`, `diffViewData`, handlers wired
3. **Backend Propose Endpoint** - `/api/ide/chat/propose-diff` exists but requires `base_content`
4. **AI Assistant Chat** - Working with model selector
5. **Editor Integration** - Monaco editor with file tabs

### What Needs Implementation:

## Backend Tasks

### 1. Implement File Writing in `/api/ide/diff/apply` ✅ HIGH PRIORITY

**File**: `python_back_end/vibecoding/ide_ai.py`

**Current State**: TODO placeholder, returns mock success

**What to Do**:
- Import `file_operations` and `container_manager`
- Get container for session_id
- Use `file_operations.save_file(container, safe_path, request.draft_content)`
- Return proper success response with actual file stats

**Code Location**: Line ~613-649

**Dependencies**: 
- `from vibecoding import file_operations, container_manager`

---

### 2. Auto-Read File Content in `/api/ide/chat/propose-diff` ✅ HIGH PRIORITY

**File**: `python_back_end/vibecoding/ide_ai.py`

**Current State**: Requires `base_content`, throws 400 if missing

**What to Do**:
- If `request.base_content` is None, read from container using `file_operations.read_file()`
- Get container via `container_manager.get_container(request.session_id)`
- Use `read_file(container, safe_path)` to get content
- Continue with existing logic

**Code Location**: Line ~548-610

**Dependencies**:
- `from vibecoding import file_operations, container_manager`

---

## Frontend Tasks

### 3. Add "Propose Changes" Trigger ✅ MEDIUM PRIORITY

**Option A: Command Palette** (Recommended)
- Add entry: "AI → Propose changes to current file"
- Opens dialog asking for instructions
- Calls `handleProposeDiff(filepath, instructions)`

**Option B: Context Menu** (Alternative)
- Right-click in editor → "AI → Propose changes..."
- Same dialog flow

**Option C: Keyboard Shortcut** (Nice to have)
- `Cmd/Ctrl + Shift + P` → type "propose"
- Or `Cmd/Ctrl + K` → "propose changes"

**File**: `front_end/jfrontend/app/ide/page.tsx`
- Already has `CommandPalette` component
- Need to add command entry

---

### 4. Save File After Accept ✅ HIGH PRIORITY

**File**: `front_end/jfrontend/app/ide/page.tsx`

**Current State**: `handleApplyDiff` only updates editor tab, doesn't save to container

**What to Do**:
- After updating editor tab, call `/api/vibecode/files/save`
- Pass `session_id`, `filepath`, `content`
- Show toast on success/error
- File should persist in container

**Code Location**: Line ~723-737

**API Endpoint**: `POST /api/vibecode/files/save`

---

### 5. Add Quick Action in AI Assistant ✅ LOW PRIORITY

**File**: `front_end/jfrontend/app/ide/components/AIAssistant.tsx`

**What to Do**:
- On assistant messages, add button: "Propose changes to current file"
- Extracts instructions from message or asks for clarification
- Calls parent's `onProposeDiff(currentFilePath, instructions)`

**Code Location**: In message rendering section (~line 244+)

---

### 6. Selection Support ✅ LOW PRIORITY

**File**: `front_end/jfrontend/app/ide/page.tsx`

**What to Do**:
- Get selected text from Monaco editor
- If selection exists, include in `propose-diff` request
- Backend can use selection to focus changes

**Requires**: 
- Editor ref access to `editor.getSelection()`
- Pass selection to `handleProposeDiff`

---

## Implementation Order

1. **Backend File Writing** (Task 1) - Critical, blocks Accept functionality
2. **Backend Auto-Read** (Task 2) - Critical, makes propose easier
3. **Frontend Save After Accept** (Task 4) - Critical, completes the flow
4. **Command Palette Trigger** (Task 3) - Important UX
5. **Quick Action Button** (Task 5) - Nice to have
6. **Selection Support** (Task 6) - Enhancement

---

## Testing Checklist

- [ ] Open file in editor
- [ ] Trigger "Propose changes" via command palette
- [ ] Enter instructions (e.g., "Add error handling")
- [ ] Diff viewer appears with proposed changes
- [ ] Edit proposed changes in right pane
- [ ] Click "Accept All"
- [ ] File saved to container
- [ ] Editor refreshes with new content
- [ ] File persists after page reload
- [ ] Works with empty file (new file)
- [ ] Works with large files (< 10MB)
- [ ] Error handling for invalid paths
- [ ] Error handling for container not found

---

## API Contracts

### POST /api/ide/chat/propose-diff

**Request**:
```json
{
  "session_id": "uuid",
  "filepath": "src/app.py",
  "base_content": "optional - if omitted, read from container",
  "instructions": "Add error handling",
  "selection": { "start": 10, "end": 20, "text": "optional" }
}
```

**Response**:
```json
{
  "draft_content": "full file content",
  "diff": "unified diff string",
  "stats": {
    "lines_added": 5,
    "lines_removed": 2,
    "hunks": 1
  }
}
```

### POST /api/ide/diff/apply

**Request**:
```json
{
  "session_id": "uuid",
  "filepath": "src/app.py",
  "draft_content": "final accepted content"
}
```

**Response**:
```json
{
  "saved": true,
  "bytes": 1024,
  "updated_at": "2025-11-04T19:00:00Z"
}
```

---

## Files to Modify

### Backend
- `python_back_end/vibecoding/ide_ai.py` - Tasks 1 & 2

### Frontend
- `front_end/jfrontend/app/ide/page.tsx` - Tasks 3, 4, 6
- `front_end/jfrontend/app/ide/components/AIAssistant.tsx` - Task 5
- `front_end/jfrontend/components/CommandPalette.tsx` - Task 3 (if needed)

---

## Dependencies

- ✅ `file_operations.read_file()` - Exists
- ✅ `file_operations.save_file()` - Exists
- ✅ `container_manager.get_container()` - Exists
- ✅ `IDEDiffAPI.apply()` - Exists in frontend
- ✅ `FilesAPI.save()` - Need to check if exists

---

## Notes

- Keep existing sessions, explorer, terminal, execution untouched ✅
- Use existing Ollama compat layer ✅
- All calls relative `/api/...` ✅
- JWT auth via header or cookie ✅
- No new Dockerfiles ✅

---

## Success Criteria

✅ From editor, can trigger "Propose changes"  
✅ AI generates code based on instructions  
✅ Diff viewer shows side-by-side comparison  
✅ Can accept/reject/merge changes  
✅ Accepted changes save to container  
✅ Editor refreshes with new content  
✅ No regressions in existing features  

---

**Status**: Ready for implementation 🚀







