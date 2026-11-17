# Image Reader Skill

Reads image files and returns them in base64 format for multimodal models to process.

## Tools

### read_image(path)
Reads an image file and returns base64-encoded data with metadata.

**Usage:**
```
read_image("/path/to/image.png")
```

**Returns:**
- base64: Base64-encoded image data
- format: Image format (png, jpg, etc)
- size: File size in bytes
- dimensions: [width, height]

## Example

When a user shares an image path, use this tool to read the image and pass it to the multimodal model for analysis.
