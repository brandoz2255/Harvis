import { NextRequest, NextResponse } from 'next/server';
import { getDb } from '@/lib/db';
import bcrypt from 'bcrypt';
import jwt from 'jsonwebtoken';

const JWT_SECRET = process.env.JWT_SECRET || 'your-secret-key';

export async function POST(req: NextRequest) {
  try {
    const { username, email, password } = await req.json();

    if (!username || !email || !password) {
      return NextResponse.json({ message: 'Missing required fields' }, { status: 400 });
    }

    const hashedPassword = await bcrypt.hash(password, 10);

    const { rows } = await getDb().query(
      'INSERT INTO users (username, email, password) VALUES ($1, $2, $3) RETURNING id',
      [username, email, hashedPassword]
    );

    const userId = rows[0].id;
    const token = jwt.sign({ userId }, JWT_SECRET, { expiresIn: '1h' });

    return NextResponse.json({ token });

  } catch (error) {
    console.error('Signup error:', error);
    return NextResponse.json({ message: 'User with this email or username already exists' }, { status: 409 });
  }
}