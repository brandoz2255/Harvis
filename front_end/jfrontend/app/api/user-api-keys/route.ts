import { NextRequest, NextResponse } from 'next/server';
import { Pool } from 'pg';
import jwt from 'jsonwebtoken';
import crypto from 'crypto';

// Database connection
const pool = new Pool({
  connectionString: process.env.DATABASE_URL,
});

// Encryption key for API keys (should be in environment variables)
const ENCRYPTION_KEY = process.env.API_KEY_ENCRYPTION_KEY || 'your-32-character-secret-key-here!';
const ALGORITHM = 'aes-256-gcm';

// Encrypt API key
function encryptApiKey(text: string): string {
  const iv = crypto.randomBytes(16);
  const key = crypto.scryptSync(ENCRYPTION_KEY, 'salt', 32);
  const cipher = crypto.createCipherGCM(ALGORITHM, key, iv);
  let encrypted = cipher.update(text, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  const authTag = cipher.getAuthTag();
  return iv.toString('hex') + ':' + authTag.toString('hex') + ':' + encrypted;
}

// Decrypt API key
function decryptApiKey(encryptedText: string): string {
  const parts = encryptedText.split(':');
  const iv = Buffer.from(parts[0], 'hex');
  const authTag = Buffer.from(parts[1], 'hex');
  const encrypted = parts[2];
  const key = crypto.scryptSync(ENCRYPTION_KEY, 'salt', 32);
  const decipher = crypto.createDecipherGCM(ALGORITHM, key, iv);
  decipher.setAuthTag(authTag);
  let decrypted = decipher.update(encrypted, 'hex', 'utf8');
  decrypted += decipher.final('utf8');
  return decrypted;
}

// Get user from JWT token
async function getUserFromToken(request: NextRequest) {
  const authHeader = request.headers.get('authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return null;
  }

  const token = authHeader.substring(7);
  try {
    const decoded = jwt.verify(token, process.env.JWT_SECRET!) as any;
    return decoded;
  } catch (error) {
    return null;
  }
}

// GET - Retrieve all API keys for user
export async function GET(request: NextRequest) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const result = await pool.query(
      `SELECT id, provider_name, api_url, is_active, created_at, updated_at 
       FROM user_api_keys 
       WHERE user_id = $1 
       ORDER BY provider_name`,
      [user.userId]
    );

    // Don't return encrypted keys, just metadata
    const apiKeys = result.rows.map(row => ({
      id: row.id,
      provider_name: row.provider_name,
      api_url: row.api_url,
      is_active: row.is_active,
      has_key: true, // Indicate that a key exists
      created_at: row.created_at,
      updated_at: row.updated_at,
    }));

    return NextResponse.json({ api_keys: apiKeys });
  } catch (error) {
    console.error('Error fetching API keys:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// POST - Add or update API key
export async function POST(request: NextRequest) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { provider_name, api_key, api_url } = await request.json();

    if (!provider_name || !api_key) {
      return NextResponse.json({ 
        error: 'Provider name and API key are required' 
      }, { status: 400 });
    }

    // Validate provider name
    const validProviders = ['ollama', 'gemini', 'openai', 'anthropic', 'huggingface'];
    if (!validProviders.includes(provider_name.toLowerCase())) {
      return NextResponse.json({ 
        error: 'Invalid provider name' 
      }, { status: 400 });
    }

    const encryptedKey = encryptApiKey(api_key);

    // Upsert the API key
    const result = await pool.query(
      `INSERT INTO user_api_keys (user_id, provider_name, api_key_encrypted, api_url, is_active)
       VALUES ($1, $2, $3, $4, true)
       ON CONFLICT (user_id, provider_name)
       DO UPDATE SET 
         api_key_encrypted = $3,
         api_url = $4,
         is_active = true,
         updated_at = CURRENT_TIMESTAMP
       RETURNING id, provider_name, api_url, is_active, created_at, updated_at`,
      [user.userId, provider_name.toLowerCase(), encryptedKey, api_url || null]
    );

    const savedKey = result.rows[0];
    return NextResponse.json({
      message: 'API key saved successfully',
      api_key: {
        id: savedKey.id,
        provider_name: savedKey.provider_name,
        api_url: savedKey.api_url,
        is_active: savedKey.is_active,
        has_key: true,
        created_at: savedKey.created_at,
        updated_at: savedKey.updated_at,
      }
    });
  } catch (error) {
    console.error('Error saving API key:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// DELETE - Remove API key
export async function DELETE(request: NextRequest) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { searchParams } = new URL(request.url);
    const provider_name = searchParams.get('provider');

    if (!provider_name) {
      return NextResponse.json({ 
        error: 'Provider name is required' 
      }, { status: 400 });
    }

    const result = await pool.query(
      `DELETE FROM user_api_keys 
       WHERE user_id = $1 AND provider_name = $2
       RETURNING id`,
      [user.userId, provider_name.toLowerCase()]
    );

    if (result.rows.length === 0) {
      return NextResponse.json({ 
        error: 'API key not found' 
      }, { status: 404 });
    }

    return NextResponse.json({ 
      message: 'API key deleted successfully' 
    });
  } catch (error) {
    console.error('Error deleting API key:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// PATCH - Toggle API key active status
export async function PATCH(request: NextRequest) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { provider_name, is_active } = await request.json();

    if (!provider_name || typeof is_active !== 'boolean') {
      return NextResponse.json({ 
        error: 'Provider name and active status are required' 
      }, { status: 400 });
    }

    const result = await pool.query(
      `UPDATE user_api_keys 
       SET is_active = $3, updated_at = CURRENT_TIMESTAMP
       WHERE user_id = $1 AND provider_name = $2
       RETURNING id, provider_name, api_url, is_active, updated_at`,
      [user.userId, provider_name.toLowerCase(), is_active]
    );

    if (result.rows.length === 0) {
      return NextResponse.json({ 
        error: 'API key not found' 
      }, { status: 404 });
    }

    const updatedKey = result.rows[0];
    return NextResponse.json({
      message: 'API key status updated successfully',
      api_key: {
        id: updatedKey.id,
        provider_name: updatedKey.provider_name,
        api_url: updatedKey.api_url,
        is_active: updatedKey.is_active,
        has_key: true,
        updated_at: updatedKey.updated_at,
      }
    });
  } catch (error) {
    console.error('Error updating API key status:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}