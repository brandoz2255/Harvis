import { NextRequest, NextResponse } from 'next/server';
import jwt from 'jsonwebtoken';
import { getDb } from '@/lib/db';

const JWT_SECRET = process.env.JWT_SECRET || 'your-secret-key';

export async function GET(req: NextRequest) {
  const authHeader = req.headers.get('Authorization');
  if (!authHeader || !authHeader.startsWith('Bearer ')) {
    return NextResponse.json({ message: 'Unauthorized' }, { status: 401 });
  }

  const token = authHeader.split(' ')[1];

  try {
    const decoded = jwt.verify(token, JWT_SECRET) as { userId: number };
    const { rows } = await getDb().query('SELECT id, username, email, avatar FROM users WHERE id = $1', [decoded.userId]);

    if (rows.length === 0) {
      return NextResponse.json({ message: 'User not found' }, { status: 404 });
    }

    const user = rows[0];
    return NextResponse.json({ id: user.id, name: user.username, email: user.email, avatar: user.avatar });

  } catch (error) {
    console.error('Error fetching user:', error);
    return NextResponse.json({ message: 'Invalid token' }, { status: 401 });
  }
}