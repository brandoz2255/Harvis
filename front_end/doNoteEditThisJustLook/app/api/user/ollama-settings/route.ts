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
  if (!text) return '';
  const iv = crypto.randomBytes(16);
  const key = crypto.scryptSync(ENCRYPTION_KEY, 'salt', 32);
  const cipher = crypto.createCipheriv(ALGORITHM, key, iv);
  let encrypted = cipher.update(text, 'utf8', 'hex');
  encrypted += cipher.final('hex');
  const authTag = cipher.getAuthTag();
  return iv.toString('hex') + ':' + authTag.toString('hex') + ':' + encrypted;
}

// Decrypt API key
function decryptApiKey(encryptedText: string): string {
  if (!encryptedText) return '';
  const parts = encryptedText.split(':');
  const iv = Buffer.from(parts[0], 'hex');
  const authTag = Buffer.from(parts[1], 'hex');
  const encrypted = parts[2];
  const key = crypto.scryptSync(ENCRYPTION_KEY, 'salt', 32);
  const decipher = crypto.createDecipheriv(ALGORITHM, key, iv);
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

// GET - Retrieve Ollama settings for user
export async function GET(request: NextRequest) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const result = await pool.query(
      `SELECT cloud_url, local_url, api_key_encrypted, preferred_endpoint, created_at, updated_at
       FROM user_ollama_settings
       WHERE user_id = $1`,
      [user.userId]
    );

    // If no settings found, return defaults
    if (result.rows.length === 0) {
      return NextResponse.json({
        cloud_url: '',
        local_url: 'http://ollama:11434',
        api_key: '',
        preferred_endpoint: 'auto'
      });
    }

    const settings = result.rows[0];

    // Decrypt API key if it exists (don't return the actual key, just mask it)
    const hasApiKey = !!settings.api_key_encrypted;

    return NextResponse.json({
      cloud_url: settings.cloud_url || '',
      local_url: settings.local_url || 'http://ollama:11434',
      api_key: hasApiKey ? '****' : '',
      preferred_endpoint: settings.preferred_endpoint || 'auto',
      created_at: settings.created_at,
      updated_at: settings.updated_at,
    });
  } catch (error) {
    console.error('Error fetching Ollama settings:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// POST - Update Ollama settings
export async function POST(request: NextRequest) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const { cloud_url, local_url, api_key, preferred_endpoint } = await request.json();

    // Validate preferred_endpoint
    const validEndpoints = ['cloud', 'local', 'auto'];
    if (preferred_endpoint && !validEndpoints.includes(preferred_endpoint)) {
      return NextResponse.json({
        error: 'Invalid preferred endpoint'
      }, { status: 400 });
    }

    // Encrypt API key if provided and not masked
    let encryptedKey = null;
    if (api_key && api_key !== '****') {
      encryptedKey = encryptApiKey(api_key);
    } else if (api_key === '****') {
      // Keep existing key if user sent masked value
      const existing = await pool.query(
        'SELECT api_key_encrypted FROM user_ollama_settings WHERE user_id = $1',
        [user.userId]
      );
      encryptedKey = existing.rows[0]?.api_key_encrypted || null;
    }

    // Upsert the Ollama settings
    const result = await pool.query(
      `INSERT INTO user_ollama_settings (user_id, cloud_url, local_url, api_key_encrypted, preferred_endpoint)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (user_id)
       DO UPDATE SET
         cloud_url = $2,
         local_url = $3,
         api_key_encrypted = $4,
         preferred_endpoint = $5,
         updated_at = CURRENT_TIMESTAMP
       RETURNING cloud_url, local_url, preferred_endpoint, created_at, updated_at`,
      [user.userId, cloud_url || null, local_url || null, encryptedKey, preferred_endpoint || 'auto']
    );

    const savedSettings = result.rows[0];
    return NextResponse.json({
      message: 'Ollama settings saved successfully',
      settings: {
        cloud_url: savedSettings.cloud_url,
        local_url: savedSettings.local_url,
        api_key: encryptedKey ? '****' : '',
        preferred_endpoint: savedSettings.preferred_endpoint,
        created_at: savedSettings.created_at,
        updated_at: savedSettings.updated_at,
      }
    });
  } catch (error) {
    console.error('Error saving Ollama settings:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}

// Helper function to get decrypted Ollama settings (for backend use)
export async function getDecryptedOllamaSettings(userId: number) {
  try {
    const result = await pool.query(
      `SELECT cloud_url, local_url, api_key_encrypted, preferred_endpoint
       FROM user_ollama_settings
       WHERE user_id = $1`,
      [userId]
    );

    if (result.rows.length === 0) {
      return null;
    }

    const settings = result.rows[0];

    return {
      cloud_url: settings.cloud_url,
      local_url: settings.local_url,
      api_key: settings.api_key_encrypted ? decryptApiKey(settings.api_key_encrypted) : '',
      preferred_endpoint: settings.preferred_endpoint || 'auto'
    };
  } catch (error) {
    console.error('Error getting decrypted Ollama settings:', error);
    return null;
  }
}
