
export const AuthService = {
  async login(email: string, password: string): Promise<string> {
    let response: Response;
    try {
      response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
      });
    } catch (fetchError: any) {
      throw fetchError;
    }

    const responseText = await response.clone().text();

    if (!response.ok) {
      try {
        const errorData = JSON.parse(responseText);
        throw new Error(errorData.message || errorData.detail || 'Login failed');
      } catch (parseError: any) {
        throw new Error(`Login failed: Server returned non-JSON response (${response.status})`);
      }
    }

    try {
      const data = JSON.parse(responseText);
      return data.access_token;
    } catch (parseError: any) {
      throw new Error('Login failed: Invalid JSON response from server');
    }
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

  // getCurrentUser removed - auth is now handled entirely by backend
};
