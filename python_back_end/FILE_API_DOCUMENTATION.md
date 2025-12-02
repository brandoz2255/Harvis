# VibeCode File API Documentation

## Overview

The VibeCode File API provides endpoints for managing files and folders within Docker container workspaces. All operations are performed on the container filesystem at `/workspace` and are scoped by session ID.

## Base URL

```
/api/vibecode
```

## Authentication

All endpoints require JWT authentication via Bearer token:

```
Authorization: Bearer <your-jwt-token>
```

## Endpoints

### 1. Get File Tree

Get the directory structure for a session workspace.

**Endpoint:** `POST /api/vibecode/files/tree`

**Request Body:**
```json
{
  "session_id": "string",
  "path": "/workspace"  // optional, defaults to /workspace
}
```

**Response:**
```json
{
  "name": "workspace",
  "type": "directory",
  "path": "/workspace",
  "size": 4096,
  "permissions": "drwxr-xr-x",
  "children": [
    {
      "name": "test.txt",
      "type": "file",
      "path": "/workspace/test.txt",
      "size": 1234,
      "permissions": "-rw-r--r--",
      "children": null
    },
    {
      "name": "folder",
      "type": "directory",
      "path": "/workspace/folder",
      "size": 4096,
      "permissions": "drwxr-xr-x",
      "children": []
    }
  ]
}
```

**Status Codes:**
- `200` - Success
- `404` - Container not found
- `500` - Server error

---

### 2. Create File or Folder

Create a new file or folder in the workspace.

**Endpoint:** `POST /api/vibecode/files/create`

**Request Body:**
```json
{
  "session_id": "string",
  "path": "string",  // relative to /workspace or absolute
  "type": "file"     // "file" or "folder"
}
```

**Examples:**
```json
// Create a file
{
  "session_id": "abc123",
  "path": "test.txt",
  "type": "file"
}

// Create a nested folder
{
  "session_id": "abc123",
  "path": "src/components",
  "type": "folder"
}
```

**Response:**
```json
{
  "success": true,
  "message": "File created successfully"
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid type or path
- `404` - Container not found
- `500` - Server error

---

### 3. Read File

Read the content of a file.

**Endpoint:** `POST /api/vibecode/files/read`

**Request Body:**
```json
{
  "session_id": "string",
  "path": "string"
}
```

**Response:**
```json
{
  "content": "file content here...",
  "path": "/workspace/test.txt"
}
```

**Status Codes:**
- `200` - Success
- `404` - File not found or container not found
- `500` - Server error

---

### 4. Save File

Save content to a file (creates file if it doesn't exist).

**Endpoint:** `POST /api/vibecode/files/save`

**Request Body:**
```json
{
  "session_id": "string",
  "path": "string",
  "content": "string"
}
```

**Example:**
```json
{
  "session_id": "abc123",
  "path": "hello.py",
  "content": "print('Hello, World!')\n"
}
```

**Response:**
```json
{
  "success": true,
  "message": "File saved successfully"
}
```

**Status Codes:**
- `200` - Success
- `400` - Invalid path
- `404` - Container not found
- `500` - Server error

**Notes:**
- Automatically creates parent directories if needed
- Handles special characters and newlines correctly
- Overwrites existing file content

---

### 5. Rename File or Folder

Rename a file or folder (stays in same directory).

**Endpoint:** `POST /api/vibecode/files/rename`

**Request Body:**
```json
{
  "session_id": "string",
  "old_path": "string",
  "new_name": "string"  // just the name, not full path
}
```

**Example:**
```json
{
  "session_id": "abc123",
  "old_path": "test.txt",
  "new_name": "renamed.txt"
}
```

**Response:**
```json
{
  "success": true,
  "message": "File/folder renamed successfully"
}
```

**Status Codes:**
- `200` - Success
- `404` - Source not found or container not found
- `409` - Destination already exists
- `500` - Server error

---

### 6. Move File or Folder

Move a file or folder to a different directory (drag-and-drop support).

**Endpoint:** `POST /api/vibecode/files/move`

**Request Body:**
```json
{
  "session_id": "string",
  "source_path": "string",
  "target_dir": "string"
}
```

**Example:**
```json
{
  "session_id": "abc123",
  "source_path": "test.txt",
  "target_dir": "folder/subfolder"
}
```

**Response:**
```json
{
  "success": true,
  "message": "File/folder moved successfully"
}
```

**Status Codes:**
- `200` - Success
- `404` - Source or target not found, or container not found
- `409` - Destination already exists
- `500` - Server error

**Notes:**
- Target directory must exist
- Preserves the original filename
- Validates target is a directory

---

### 7. Delete File or Folder

Delete a file or folder (soft delete to trash by default).

**Endpoint:** `POST /api/vibecode/files/delete`

**Request Body:**
```json
{
  "session_id": "string",
  "path": "string",
  "soft": true  // optional, defaults to true
}
```

**Examples:**
```json
// Soft delete (move to trash)
{
  "session_id": "abc123",
  "path": "test.txt",
  "soft": true
}

// Hard delete (permanent)
{
  "session_id": "abc123",
  "path": "test.txt",
  "soft": false
}
```

**Response:**
```json
{
  "success": true,
  "message": "File/folder soft deleted (moved to trash)"
}
```

**Status Codes:**
- `200` - Success
- `400` - Cannot delete workspace root
- `404` - File not found or container not found
- `500` - Server error

**Notes:**
- Soft delete moves to `.vibe_trash/` with timestamp
- Hard delete permanently removes the file/folder
- Cannot delete `/workspace` root directory
- Trash files are named: `filename.timestamp`

---

## Security

### Path Sanitization

All file paths are sanitized to prevent security vulnerabilities:

- ✅ Blocks `..` path traversal attempts
- ✅ Blocks absolute paths outside `/workspace`
- ✅ Validates symlinks don't escape workspace
- ✅ Normalizes paths (removes `.`, `..`, redundant slashes)

**Examples of blocked paths:**
- `../etc/passwd` ❌
- `/etc/passwd` ❌
- `/workspace/../etc/passwd` ❌
- `../../../../../../etc/passwd` ❌

### Authentication

All endpoints require:
- Valid JWT token in Authorization header
- Token must not be expired
- User must have access to the session

### Container Isolation

- Each session has its own Docker container
- Files are isolated by session ID
- No cross-session file access
- Container volumes persist data

---

## Error Handling

### Common Error Responses

**401 Unauthorized:**
```json
{
  "detail": "Could not validate credentials"
}
```

**404 Not Found:**
```json
{
  "detail": "Container not found for session abc123"
}
```

**400 Bad Request:**
```json
{
  "detail": "Invalid path: security violation"
}
```

**409 Conflict:**
```json
{
  "detail": "Destination already exists"
}
```

**500 Internal Server Error:**
```json
{
  "detail": "Failed to save file: <error details>"
}
```

---

## Usage Examples

### JavaScript/TypeScript (Frontend)

```typescript
// Get file tree
async function getFileTree(sessionId: string) {
  const response = await fetch('/api/vibecode/files/tree', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      path: '/workspace'
    })
  });
  return await response.json();
}

// Save file
async function saveFile(sessionId: string, path: string, content: string) {
  const response = await fetch('/api/vibecode/files/save', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      path: path,
      content: content
    })
  });
  return await response.json();
}

// Read file
async function readFile(sessionId: string, path: string) {
  const response = await fetch('/api/vibecode/files/read', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      session_id: sessionId,
      path: path
    })
  });
  const data = await response.json();
  return data.content;
}
```

### Python

```python
import requests

BASE_URL = "http://localhost:8000"
TOKEN = "your-jwt-token"

headers = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# Create a file
response = requests.post(
    f"{BASE_URL}/api/vibecode/files/create",
    headers=headers,
    json={
        "session_id": "abc123",
        "path": "test.py",
        "type": "file"
    }
)
print(response.json())

# Save content
response = requests.post(
    f"{BASE_URL}/api/vibecode/files/save",
    headers=headers,
    json={
        "session_id": "abc123",
        "path": "test.py",
        "content": "print('Hello, World!')\n"
    }
)
print(response.json())
```

### cURL

```bash
# Get file tree
curl -X POST http://localhost:8000/api/vibecode/files/tree \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc123", "path": "/workspace"}'

# Create a file
curl -X POST http://localhost:8000/api/vibecode/files/create \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc123", "path": "test.txt", "type": "file"}'

# Save file content
curl -X POST http://localhost:8000/api/vibecode/files/save \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "abc123", "path": "test.txt", "content": "Hello!"}'
```

---

## Performance

Expected latency for operations:

- **File tree** (1000 files): < 1 second
- **Create file/folder**: < 100ms
- **Read file**: < 100ms
- **Save file**: < 500ms
- **Rename**: < 100ms
- **Move**: < 100ms
- **Delete**: < 100ms

---

## Testing

Run the test script to verify all endpoints:

```bash
# Set your JWT token
export TOKEN="your-jwt-token-here"

# Run tests
./test_file_api_endpoints.sh
```

Or test individual endpoints with curl:

```bash
# Test file tree
curl -X POST http://localhost:8000/api/vibecode/files/tree \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_id": "test-session", "path": "/workspace"}' | jq
```

---

## Integration with Frontend

The file API is designed to work seamlessly with the VibeCode IDE frontend:

1. **File Explorer**: Uses `/files/tree` to display directory structure
2. **Code Editor**: Uses `/files/read` and `/files/save` for editing
3. **Drag & Drop**: Uses `/files/move` for file organization
4. **Context Menu**: Uses `/files/create`, `/files/rename`, `/files/delete`

See the design document for frontend integration details.
