# Hello World Test Commands for VibeCode

## ✅ Runnable Files (Should Work)

### Python
```python
# hello.py
print("Hello, World!")
```
**Expected**: "Hello, World!" in output

### JavaScript
```javascript
// hello.js
console.log("Hello, World!");
```
**Expected**: "Hello, World!" in output

### Bash
```bash
#!/bin/bash
# hello.sh
echo "Hello, World!"
```
**Expected**: "Hello, World!" in output

## ❌ Non-Runnable Files (Should Show Actions)

### JSON
```json
{
  "message": "Hello, World!",
  "valid": true
}
```
**Expected**: Format and Validate buttons appear (not Run button)

### YAML
```yaml
# config.yaml
message: Hello, World!
valid: true
```
**Expected**: No Run button

### Markdown
```markdown
# README.md
# Hello, World!
This is a markdown file.
```
**Expected**: No Run button

## Testing Flow

1. **Create a new session** in the `/ide` page
2. **Create test files** using the "+" button in the file explorer
3. **For Python** (`hello.py`):
   - Click Run button
   - Should see "Hello, World!" in Output tab
   
4. **For JavaScript** (`hello.js`):
   - If Node.js is installed: Click Run, see output
   - If Node.js not installed: Run button disabled with tooltip "Requires Node runtime"
   
5. **For JSON** (`test.json`):
   - No Run button visible
   - Should see "Format" and "Validate" buttons
   - Click "Format" → JSON gets pretty-printed
   - Click "Validate" → Shows "JSON is valid ✓" or error message

## Current Runner Image Status

The backend is configured to use: `node:18-bullseye-slim`

This image includes:
- ✅ Node.js 18
- ✅ Bash
- ❌ Python (not included by default)

To add Python support, either:
1. Build the custom runner image in `/runner/` directory
2. Or use a different base image that includes both

## Backend Behavior

- **JSON files**: Returns `exit_code: 126` with message "JSON is not executable. Use Format/Validate."
- **JS files without Node**: Returns `exit_code: 127` with message "Node runtime not available in runner."
- **All errors**: HTTP 200 response (not 500) so Output tab can display the message
