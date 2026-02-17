## 2026-02-16: Add Ansible Playbooks to RAG VectorDB with Qwen3 Embedding

### Problem
The RAG corpus system supported various documentation sources (Kubernetes, Docker, Python, etc.) but lacked support for Ansible playbooks. Ansible playbooks are complex YAML files with Jinja2 templating, role hierarchies, and variable structures that require high-dimensional embeddings for semantic understanding.

### Root Cause
No fetcher existed to parse and index Ansible playbook content. The RAG system needed a specialized fetcher that could handle:
- YAML with Jinja2 templates (`{{ variable }}`)
- Role directory structures (tasks/, handlers/, vars/, defaults/, meta/)
- Module invocations with complex parameters
- Variable files and inventories
- Playbook structural analysis

### Solution Applied
Implemented full Ansible playbook support using the high-tier `qwen3-embedding` model (4096 dimensions) for complex technical content.

#### Files Modified:

1. **Backend Fetcher** (`python_back_end/rag_corpus/source_fetchers.py`)
   - Added `AnsiblePlaybookFetcher` class (~300 lines)
   - Recursively scans directories for `.yml`/`.yaml` files
   - Detects file types: tasks, handlers, variables, templates, inventories, playbooks
   - Extracts role names from directory structure
   - Parses YAML to identify modules used
   - Enriches content with structural metadata for better embedding
   - Updated `get_fetcher_for_config()` to handle "ansible" fetcher type
   - Updated `get_fetcher()` to support "ansible_playbooks" source

2. **Backend Routes** (`python_back_end/rag_corpus/routes.py`)
   - Added `ansible_playbooks` to `SOURCE_EMBEDDING_MODELS` with `qwen3-embedding`
   - Added `ansible_paths` field to `UpdateRagRequest` model
   - Updated job creation to pass `ansible_paths` parameter

3. **Job Manager** (`python_back_end/rag_corpus/job_manager.py`)
   - Added `ansible_paths` field to `Job` dataclass
   - Updated `create_job()` to accept `ansible_paths` parameter
   - Updated `_get_fetcher()` to handle ansible_playbooks source

4. **Frontend Settings** (`front_end/newjfrontend/app/settings/page.tsx`)
   - Added `ansible_playbooks` to `SOURCE_CONFIG` in "devops" group
   - Added state variables for ansible paths input
   - Added `addAnsiblePath`/`removeAnsiblePath` handler functions
   - Added Ansible paths input UI section (red-themed to match branding)
   - Updated `handleStartUpdate` to include `ansible_paths`

5. **TypeScript Types** (`front_end/newjfrontend/lib/rag.ts`)
   - Added `ansible_paths?: string[]` to `RagUpdateRequest` interface

### Features:
- Uses `qwen3-embedding` (4096 dims) for high-fidelity semantic search
- Parses YAML structure to extract playbook metadata
- Detects Jinja2 templates and marks content accordingly
- Identifies Ansible modules used in playbooks
- Supports role directory structures (`roles/<name>/tasks/main.yml`, etc.)
- UI input for specifying local playbook directories
- Works with complex playbooks containing nested structures

### Result
Users can now:
1. Go to Settings page
2. Select "Ansible Playbooks" source (in DevOps section)
3. Enter paths to local directories containing Ansible content
4. Click "Start Update" to index playbooks into the VectorDB
5. Query the RAG corpus for Ansible-related questions

The system uses Qwen3's high-dimensional embeddings to capture nuanced relationships in complex Ansible configurations, including Jinja2 templating patterns, module parameters, and role dependencies.

---

## 2026-02-15: Add Image Copy/Paste Support to Chat Input

### Problem
Users needed to manually select images from file system. They couldn't simply copy and paste images directly into the chat interface.

### Root Cause
The chat input textarea component didn't have any paste event handling for image files.

### Solution Applied
Added clipboard paste event handling to the chat input component that detects and processes pasted images.

**File:** `front_end/newjfrontend/components/chat-input.tsx`

#### Changes Made:

1. **Added `handlePaste` function** (lines 140-190)
   - Intercepts paste events on the textarea
   - Checks `e.clipboardData.items` for image data (screenshots, copied from browser)
   - Checks `e.clipboardData.files` for file data (copied from file manager)
   - Filters for supported image types (png, jpeg, gif, webp)
   - Prevents image data from being pasted as text into textarea

2. **Added `processImageBlob` helper function** (lines 192-212)
   - Converts pasted image blob to base64
   - Creates ImageAttachment object with proper metadata
   - Adds to attachments state for display

3. **Attached handler to Textarea** (line 848)
   - Added `onPaste={handlePaste}` prop to the Textarea component

4. **Updated placeholder text** (line 854)
   - Changed from `"Ask anything..."` to `"Ask anything... (paste images to analyze)"`
   - Users now know paste is supported

### Features:
- ✅ Paste screenshots directly (Cmd/Ctrl+Shift+3/4 on Mac, PrintScreen on Windows)
- ✅ Paste copied images from browser/web pages
- ✅ Paste images copied from file manager
- ✅ Supports all existing image types (PNG, JPEG, GIF, WebP)
- ✅ VL model requirement check (same as file upload)
- ✅ Multiple images can be pasted at once
- ✅ Works alongside existing upload methods (file picker, drag-drop if implemented)

### Result
Users can now:
1. Take a screenshot
2. Copy any image from the web or file manager
3. Press Ctrl+V (or Cmd+V) while focused in the chat input
4. The image immediately appears as an attachment
5. Type a message and send - the AI will analyze the image

---
