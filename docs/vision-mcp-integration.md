# Vision and MCP Integration

This document details the Vision Language (VL) model support and Model Context Protocol (MCP) plugin integration features.

## 1. Vision Features

The assistant now supports real-time vision capabilities, including screen sharing and image uploads, specifically when a Vision Language (VL) model is active.

### Camera Icon (Screenshare)
- **Location**: Left side of the chat input, next to the image icon.
- **Functionality**: Uses the `getDisplayMedia` API to capture the user's screen.
- **Automatic Updates**: When active, the screenshot is automatically updated every 3 seconds.
- **Live Preview**: A small thumbnail preview of the current capture is displayed above the input.
- **Constraints**: 
    - Only active when a VL model is selected.
    - If a non-VL model is selected, clicking the icon will show an error message.

### Image Upload (Image Icon)
- **Support**: Allows uploading images in PNG, JPEG, GIF, and WebP formats.
- **Batching**: Supports multiple image uploads in a single message.
- **Previews**: Thumbnails with "remove" buttons are shown for each uploaded image.
- **Constraints**: 
    - Works only with VL models. Non-VL models will show an error.
    - Buttons are grayed out when a non-VL model is selected to provide visual feedback.

### VL Model Detection
The system automatically detects vision-capable models by scanning their names for specific patterns.
- **Detection Patterns**: `vision`, `vl`, `llava`, `bakllava`, `moondream`, `minicpm-v`, `qwen2-vl`, `cogvlm`, `internvl`, `phi-3-vision`, `deepseek-vl`, `yi-vl`, `gemma-2-vision`.
- **UI Indicators**: When a VL model is selected, the footer displays "Vision model active" in green.
- **Feature Gating**: Image and camera buttons are disabled (grayed out) for non-VL models.

---

## 2. Paperclip Menu & File Support

The paperclip icon opens a multi-functional menu for file handling and plugin management.

### Upload Files
Supported file formats for ingestion and analysis:
- **Documents**: PDF, DOCX, DOC, TXT, MD.
- **Data/Code**: CSV, JSON, JS, TS, PY, HTML, CSS, XML, YAML.

### MCP Plugin Management
The Model Context Protocol (MCP) allows the assistant to interact with external tools and services.

- **Adding Plugins**: A modal allows users to configure:
    - **Plugin Name**: A friendly identifier for the plugin.
    - **Host**: IP address or hostname of the MCP server.
    - **Port**: The port number on which the MCP server is listening.
- **State Management**:
    - **LocalStorage Persistence**: Plugin configurations are saved locally and persist across browser sessions.
    - **Toggle Support**: Plugins can be individually enabled or disabled.
    - **Deletion**: Existing plugins can be removed from the list.

---

## 3. Technical Implementation Overview

Key files involved in this integration:

- [types/message.ts](file:///home/dulc3/Documents/github/harvis/aidev/front_end/newjfrontend/types/message.ts): Defines `ImageAttachment`, `FileAttachment`, `MCPPlugin`, and the `isVisionModel` detection logic.
- [components/chat-input.tsx](file:///home/dulc3/Documents/github/harvis/aidev/front_end/newjfrontend/components/chat-input.tsx): Implements the screen capture loop, image handling, and MCP management UI.
- [components/chat-message.tsx](file:///home/dulc3/Documents/github/harvis/aidev/front_end/newjfrontend/components/chat-message.tsx): Displays image attachments and input type badges in the chat history.
- [app/page.tsx](file:///home/dulc3/Documents/github/harvis/aidev/front_end/newjfrontend/app/page.tsx): Handles routing vision requests to the `/api/analyze-and-respond` endpoint.
