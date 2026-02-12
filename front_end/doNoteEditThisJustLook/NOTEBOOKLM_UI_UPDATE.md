# NotebookLM UI Update

## Overview
Updated the NotebookLM page to match the reference design with an improved "Add Sources" modal.

## Changes Made

### 1. New AddSourcesModal Component
Created a dedicated `AddSourcesModal` component that matches the NotebookLM design:

**Features:**
- Dark theme matching the reference design (#1e1e1e background)
- Gradient logo icon (orange → pink → purple)
- "Discover sources" button in header
- Drag & drop file upload with visual feedback
- Three source type sections:
  - Google Workspace (with Google Drive button)
  - Link (Website and YouTube buttons)
  - Paste text (Copied text button)
- Inline URL input form (appears when clicking Website)
- Inline text input form (appears when clicking Copied text)
- Source limit progress bar (0/50)
- Proper file type support display

### 2. UI Improvements

**Upload Area:**
- Larger upload icon with blue accent
- Dashed border that highlights on drag
- Clear "choose file" link styling
- Comprehensive file type list

**Source Type Cards:**
- Semi-transparent backgrounds (bg-gray-800/50)
- Subtle borders (border-gray-700/50)
- Google logo SVG for Google Workspace
- YouTube icon with red accent
- Proper icon sizing and spacing

**Input Forms:**
- URL input with Enter key support
- Text input with title and content fields
- Proper validation (disabled buttons when empty)
- Close buttons to dismiss forms

### 3. Functionality

**File Upload:**
- Drag & drop support
- Click to browse
- Multiple file selection
- Supported formats: PDF, txt, md, doc, docx, mp3, wav, images

**URL Sources:**
- Inline URL input form
- Enter key to submit
- Validation before submission

**Text Sources:**
- Title and content fields
- Multi-line text area
- Validation before submission

## File Modified
- `aidev/front_end/jfrontend/app/notebooks/[id]/page.tsx`

## Testing

### To Test:
1. Navigate to `/notebooks`
2. Create or open a notebook
3. Click "Add sources" button
4. Verify:
   - Modal appears with correct styling
   - Drag & drop works
   - Click to upload works
   - Website button shows URL input
   - Copied text button shows text input
   - Source limit bar shows correct count
   - Close button works
   - Escape key closes modal (if implemented)

### Expected Behavior:
- Modal matches the NotebookLM reference design
- All source types can be added
- Forms validate input before submission
- Modal closes after successful source addition
- Source appears in the left panel after adding

## Design Reference
The UI now matches the NotebookLM "Add sources" modal with:
- Dark theme (#1e1e1e)
- Gradient logo
- Three-column source type layout
- Drag & drop upload area
- Source limit progress bar
- Inline input forms for URL and text

## Notes
- Google Drive integration is a placeholder (button exists but no functionality)
- YouTube integration is a placeholder (button exists but no functionality)
- The "Discover sources" button is a placeholder
