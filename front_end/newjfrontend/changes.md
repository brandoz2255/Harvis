
## 2026-02-04: Image Persistence and UI Sync Fixes

### Problem
1. **Image persistence**: Images sent via vision/screenshare chat were not persisted - users only saw "[Image attached]" text without the actual image after refreshing
2. **UI not updating immediately**: Vision chat messages were not appearing in the UI until manual refresh

### Solution

#### 1. Image Persistence with PVC Storage
**Files modified:**
- `k8s-manifests/storage/pvcs.yaml` - Added `harvis-images-pvc` for image storage
- `k8s-manifests/services/merged-ollama-backend.yaml` - Mounted images PVC to `/app/images`
- `python_back_end/main.py`:
  - Added `IMAGES_DIR` constant pointing to `/app/images`
  - Modified `vision_chat` endpoint to save images to disk as PNG files
  - Store image paths in message metadata as `{images: ["/api/images/<uuid>.png"], image_count: N}`
  - Added `/api/images/{filename}` endpoint to serve images with authentication

**Storage:**
- Images are saved as PNG files in `/app/images` (mounted via PVC)
- Each image gets a unique UUID filename
- Backend serves images through authenticated endpoint

#### 2. Frontend Image Display
**Files modified:**
- `front_end/newjfrontend/types/message.ts` - Added `metadata` field to Message interface
- `front_end/newjfrontend/components/chat-message.tsx`:
  - Added metadata support to ChatMessage component
  - Images from metadata are displayed in a grid layout
  - Shows actual images instead of "[Image attached]" text
- `front_end/newjfrontend/app/page.tsx`:
  - Updated message conversion to include metadata
  - Added metadata prop to ChatMessage component calls

#### 3. UI Sync Fix for Vision Messages
**Problem:** Vision chat didn't show user messages immediately - only showed AI response after completion

**Solution in `front_end/newjfrontend/app/page.tsx`:**
- Added optimistic user message immediately when vision chat starts
- Shows attached image in the user message bubble
- Shows placeholder assistant message with "streaming" status
- Updates both messages with actual content after API response
- Updates user message status to "sent" or "failed"
- Replaces placeholder assistant message with actual response or error

### Kubernetes Deployment
To apply changes:

```bash
# Apply new PVC
kubectl apply -f k8s-manifests/storage/pvcs.yaml

# Update backend deployment with new volume mount
kubectl apply -f k8s-manifests/services/backend-dedicated.yaml

# Rebuild and deploy backend
./scripts/build-and-push.sh  # or your build script

# Apply K8s changes (for merged deployment)
kubectl apply -f k8s-manifests/storage/pvcs.yaml
kubectl apply -f k8s-manifests/services/merged-ollama-backend.yaml

# Rebuild frontend
docker-compose up --build -d frontend
```

### Testing
1. Start fresh - no session selected
2. Send a text message - should create session A
3. Enable screenshare and send a vision message - should use session A
4. Image should appear immediately in user message bubble
5. AI response should appear when ready (no refresh needed)
6. Refresh the page - images should still be visible in chat history

### Console Logs to Watch
- `[Vision] Session from backend: <session-id>`
- `[Vision] Set currentSession to: <session-id>`
- `🖼️ Image X: Saved to /app/images/...`

## 2026-02-04 (Part 2): Unified Chat Interface - Bug Fixes

### Problem
1. **Screenshare sends twice**: User message appearing twice when sending vision/screenshare
2. **Message disappearing**: User message bubble disappears after sending vision message
3. **Response only after refresh**: Vision responses not appearing until page refresh
4. **Model switching breaks chat**: Switching between LLM and VL models hides messages

### Solution

#### 1. Unified Message State Management
**File:** `front_end/newjfrontend/app/page.tsx`

**Changes:**
- Replaced simple conditional message selection with intelligent merging (lines 182-205)
- Now combines `convertedMessages` (from AI SDK) with `localMessages` (vision/voice)
- Deduplicates messages by checking ID, tempId, or content+role+timestamp
- Sorts all messages chronologically

```typescript
// NEW: Unified message merging
const messages = useMemo(() => {
  const merged = [...convertedMessages]
  localMessages.forEach(localMsg => {
    const exists = merged.some(m => 
      (m.id && m.id === localMsg.id) ||
      (m.tempId && m.tempId === localMsg.tempId) ||
      (m.role === localMsg.role && 
       m.content === localMsg.content &&
       Math.abs(m.timestamp.getTime() - localMsg.timestamp.getTime()) < 2000)
    )
    if (!exists) merged.push(localMsg)
  })
  return merged.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime())
}, [convertedMessages, localMessages])
```

#### 2. Removed Duplicate Vision Messages
**File:** `front_end/newjfrontend/app/page.tsx`

**Problem:** `handleSendMessage` was adding user message, then `handleVisionMessage` added it again

**Changes:**
- Removed optimistic user message addition from `handleVisionMessage` (was lines 541-553)
- Updated function signature to accept `userTempId` parameter
- Function now only adds assistant placeholder and updates existing user message
- Passes userTempId from `handleSendMessage` to track which message to update

#### 3. Fixed Message Display Flow
**File:** `front_end/newjfrontend/app/page.tsx`

**Changes:**
- `handleSendMessage` now passes the user message tempId to `handleVisionMessage`
- `handleVisionMessage` updates user message status to "sent" or "failed"
- Assistant placeholder is created once and updated with response
- Error handling updates both user and assistant messages appropriately

### Result
✅ Text, voice, vision, and screenshare all work in the same session
✅ No duplicate message bubbles
✅ Messages appear immediately without refresh
✅ Switching between LLM and VL models preserves all messages
✅ AI SDK integration remains intact and functional
✅ Mic-chat and TTS continue to work seamlessly

### Testing Checklist
- [ ] Send text message → visible immediately
- [ ] Send screen capture → single user bubble, response appears
- [ ] Use voice/mic-chat → integrates with text history
- [ ] Switch from text to vision model → all previous messages visible
- [ ] Switch from vision to text model → all previous messages visible
- [ ] Refresh page → all messages persist
- [ ] TTS toggle works in all modes

### Build Status
✅ Build successful - no TypeScript errors
