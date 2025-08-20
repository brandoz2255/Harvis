
export const AuthService = {
  async login(email: string, password: string): Promise<string> {
    const response = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
      credentials: 'include',
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.message || 'Login failed');
    }

    const data = await response.json();
    return data.access_token;
  },

  async signup(username: string, email: string, password: string): Promise<string> {
    const response = await fetch('/api/auth/signup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, email, password }),
      credentials: 'include',
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.message || 'Signup failed');
    }

    const data = await response.json();
    return data.access_token;
  },

  async fetchUser(token: string): Promise<{ id: string; name: string; email: string; avatar?: string }> {
    const response = await fetch('/api/auth/me', {
      headers: {
        'Authorization': `Bearer ${token}`,
      },
      credentials: 'include',
    });

    if (!response.ok) {
      throw new Error('Failed to fetch user data');
    }

    const data = await response.json();
    return {
      id: data.id.toString(),
      name: data.username,  // Backend returns 'username', frontend expects 'name'
      email: data.email,
      avatar: data.avatar
    };
  },

  async getCurrentUser(request: Request): Promise<{ id: string; name: string; email: string; avatar?: string } | null> {
    try {
      const authHeader = request.headers.get('authorization');
      if (!authHeader) {
        return null;
      }

      const token = authHeader.replace('Bearer ', '');
      return await this.fetchUser(token);
    } catch (error) {
      console.error('Error getting current user:', error);
      return null;
    }
  },
};
