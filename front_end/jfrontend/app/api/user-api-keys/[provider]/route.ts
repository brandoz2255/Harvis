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

// GET - Retrieve specific API key for backend use (returns decrypted key)
export async function GET(
  request: NextRequest,
  { params }: { params: { provider: string } }
) {
  try {
    const user = await getUserFromToken(request);
    if (!user) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 });
    }

    const provider = params.provider.toLowerCase();

    const result = await pool.query(
      `SELECT api_key_encrypted, api_url, is_active 
       FROM user_api_keys 
       WHERE user_id = $1 AND provider_name = $2 AND is_active = true`,
      [user.userId, provider]
    );

    if (result.rows.length === 0) {
      return NextResponse.json({ 
        error: 'API key not found or inactive' 
      }, { status: 404 });
    }

    const row = result.rows[0];
    
    try {
      const decryptedKey = decryptApiKey(row.api_key_encrypted);
      
      return NextResponse.json({
        api_key: decryptedKey,
        api_url: row.api_url,
        provider: provider
      });
    } catch (decryptError) {
      console.error('Error decrypting API key:', decryptError);
      return NextResponse.json({ 
        error: 'Failed to decrypt API key' 
      }, { status: 500 });
    }
  } catch (error) {
    console.error('Error fetching API key:', error);
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 });
  }
}