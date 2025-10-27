# ✅ Plus Button Fix - File Creation in Explorer

## Problem
The "+" button in the file explorer was present but not wired to any onClick handler, so clicking it did nothing.

## Solution
Added onClick handler to the Plus button that:
1. Prompts user for file name
2. Calls `createFile('/workspace', fileName)` to create the file
3. File appears in the tree immediately after creation

## Changes Made

**File**: `front_end/jfrontend/components/MonacoVibeFileTree.tsx`  
**Line**: 942-954

```typescript
<Button 
  size="sm"
  variant="ghost"
  className="p-1 h-auto hover:bg-gray-700"
  onClick={() => {
    const fileName = prompt('Enter file name:')
    if (fileName && fileName.trim()) {
      createFile('/workspace', fileName.trim())
    }
  }}
>
  <Plus size={14} className="text-gray-400" />
</Button>
```

## How It Works

1. **User clicks "+" button** → Prompts for filename
2. **User enters** `hello.py` → Clicks OK
3. **createFile() function**:
   - Gets auth token from localStorage
   - Converts absolute path to relative path
   - Calls API: `POST /api/vibecode/files/create`
   - Sends: `{ session_id, path: "hello.py", type: "file" }`
4. **Backend creates file** in runner container workspace
5. **Auto-refresh** → File appears in tree immediately
6. **File opens** in editor automatically (if wired in parent)

## What's Fixed

- ✅ Plus button now creates files
- ✅ Files created in `/workspace` directory
- ✅ Uses existing `createFile()` function (already handles errors)
- ✅ Automatically refreshes tree after creation
- ✅ Works with backend permission fixes (chmod 777)

## Test It

1. **Go to** `/ide` page
2. **Click "+"** in file explorer header
3. **Enter filename**: `test.py` (or any extension)
4. **See file** appear in tree
5. **Click file** to open in editor

**The plus button now works!** 🎉

