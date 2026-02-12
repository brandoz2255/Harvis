# Moonshot AI Integration - Changes Summary

## Overview
Added support for Moonshot AI (Kimi K2.5) models to the Harvis AI application. Users can now configure their own Moonshot API key in the profile settings and use Kimi models for chat.

## Changes Made

### Backend Changes

#### 1. New File: `python_back_end/moonshot_api.py`
- Created Moonshot API client with support for:
  - Chat completions (sync and streaming)
  - Model mapping (kimi-k2.5, kimi-k2, kimi-k1.5, kimi-latest)
  - Error handling and timeout management

#### 2. Modified: `python_back_end/main.py`
**Imports Added:**
- Added `moonshot_api` imports for Moonshot client and utilities
- Added `cryptography` imports for API key encryption/decryption

**Encryption Functions:**
- `encrypt_api_key()`: Encrypts API keys using Fernet symmetric encryption
- `decrypt_api_key()`: Decrypts stored API keys
- `get_user_api_key()`: Retrieves a user's API key for a specific provider
- Encryption key derived from JWT_SECRET for consistency

**API Key Management Endpoints:**
- `GET /api/user/api-keys`: List all user's API keys (without sensitive data)
- `POST /api/user/api-keys`: Create or update an API key
- `DELETE /api/user/api-keys/{provider_name}`: Remove an API key
- `GET /api/user/api-keys/{provider_name}`: Get specific API key details

**Models Endpoint:**
- Modified `GET /api/models` to include Moonshot models when user has API key configured
- Models include: kimi-k2.5, kimi-k2, kimi-latest

**Chat Endpoint:**
- Added Moonshot branch in chat streaming logic
- Detects kimi models and routes to Moonshot API
- Uses user's saved API key from database
- Supports streaming responses
- Includes RAG context support
- Adds reasoning model support for kimi-k2.5

**Models Added:**
- `ApiKeyRequest`: Pydantic model for API key creation/update
- `ApiKeyResponse`: Pydantic model for API key responses
- `ApiKeyUpdateRequest`: Pydantic model for API key updates

#### 3. Modified: `python_back_end/requirements.txt`
- Added `cryptography>=41.0.0` for API key encryption

### Frontend Changes

#### 1. Modified: `front_end/newjfrontend/app/profile/page.tsx`
**Added State:**
- `apiKeys`: State for managing API keys (currently supports Moonshot)
- `showApiKey`: State for toggling API key visibility
- `apiKeyLoading`: Loading state for API key operations
- `apiKeyMessage`: Success/error message state

**Added Functions:**
- `loadApiKeys()`: Fetches user's API keys on component mount
- `saveApiKey()`: Saves or updates an API key
- `deleteApiKey()`: Removes an API key

**Added UI Components:**
- New "API Keys" card section in profile page
- Moonshot AI configuration form:
  - API Key input (with show/hide toggle)
  - Optional custom API URL input
  - Save/Remove buttons
  - Active status indicator
- Alert component for success/error messages
- Link to Moonshot Platform for getting API keys

#### 2. New File: `front_end/newjfrontend/components/ui/alert.tsx`
- Created reusable Alert component
- Supports default and destructive variants
- Includes AlertTitle and AlertDescription subcomponents

## Database Schema
The existing `user_api_keys` table (from db_setup.sql) is used:
```sql
CREATE TABLE IF NOT EXISTS user_api_keys (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_name VARCHAR(50) NOT NULL,
    api_key_encrypted TEXT NOT NULL,
    api_url VARCHAR(500),
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, provider_name)
);
```

## How It Works

1. **User Configuration:**
   - User navigates to Profile page
   - Enters their Moonshot API key in the API Keys section
   - Optionally provides a custom API URL
   - Clicks "Save Key"

2. **Key Storage:**
   - API key is encrypted using Fernet symmetric encryption
   - Encrypted key is stored in `user_api_keys` table
   - JWT_SECRET is used to derive the encryption key

3. **Model Selection:**
   - When user has Moonshot API key configured, kimi models appear in model selector
   - Models include: kimi-k2.5, kimi-k2, kimi-latest

4. **Chat Usage:**
   - User selects a kimi model from dropdown
   - Backend detects kimi model and routes to Moonshot branch
   - User's saved API key is retrieved and decrypted
   - Chat completion is sent to Moonshot API
   - Response is streamed back to frontend

5. **Security:**
   - API keys are encrypted at rest
   - Keys are never sent to frontend in plaintext
   - Only authenticated users can access their own keys
   - Keys are deleted when user account is deleted (CASCADE)

## API Endpoints

### Backend
- `GET /api/models` - Returns available models including Moonshot if user has key
- `POST /api/chat` - Chat endpoint with Moonshot support
- `GET /api/user/api-keys` - List user's API keys
- `POST /api/user/api-keys` - Save/update API key
- `DELETE /api/user/api-keys/{provider}` - Delete API key

### Frontend
- `/profile` - Profile page with API key management section

## Testing

To test the integration:
1. Go to Profile page
2. Add your Moonshot API key (get from https://platform.moonshot.cn/)
3. Save the key
4. Go to main chat page
5. Select "Kimi K2.5 (Moonshot)" from model dropdown
6. Send a message - it should use your Moonshot API key

## Notes

- Moonshot API key is required for kimi models to work
- If no API key is configured, kimi models won't appear in the selector
- API keys are encrypted using Fernet (AES-128 in CBC mode with HMAC)
- The encryption key is derived from the JWT_SECRET environment variable
- Custom API URLs are optional (defaults to https://api.moonshot.cn/v1)
