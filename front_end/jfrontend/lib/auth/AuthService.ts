
export const AuthService = {
  async login(email: string, password: string): Promise<string> {
    // #region agent log
    fetch('http://127.0.0.1:7242/ingest/3639bdfd-8484-4d74-afff-e877a6386062',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'AuthService.ts:login:entry',message:'Login attempt started',data:{email},timestamp:Date.now(),sessionId:'debug-session',hypothesisId:'A'})}).catch(()=>{});
    // #endregion
    
    let response: Response;
    try {
      response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
        credentials: 'include',
      });
    } catch (fetchError: any) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/3639bdfd-8484-4d74-afff-e877a6386062',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'AuthService.ts:login:fetch-error',message:'Fetch failed completely',data:{error:fetchError?.message},timestamp:Date.now(),sessionId:'debug-session',hypothesisId:'B'})}).catch(()=>{});
      // #endregion
      throw fetchError;
    }

    // #region agent log
    const responseText = await response.clone().text();
    fetch('http://127.0.0.1:7242/ingest/3639bdfd-8484-4d74-afff-e877a6386062',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'AuthService.ts:login:response',message:'Got response from server',data:{status:response.status,statusText:response.statusText,contentType:response.headers.get('content-type'),responsePreview:responseText.substring(0,500),url:response.url,redirected:response.redirected},timestamp:Date.now(),sessionId:'debug-session',hypothesisId:'A,C,D,E'})}).catch(()=>{});
    // #endregion

    if (!response.ok) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/3639bdfd-8484-4d74-afff-e877a6386062',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'AuthService.ts:login:not-ok',message:'Response not OK, parsing error',data:{status:response.status,responsePreview:responseText.substring(0,300)},timestamp:Date.now(),sessionId:'debug-session',hypothesisId:'A,C'})}).catch(()=>{});
      // #endregion
      
      try {
        const errorData = JSON.parse(responseText);
        throw new Error(errorData.message || errorData.detail || 'Login failed');
      } catch (parseError: any) {
        // #region agent log
        fetch('http://127.0.0.1:7242/ingest/3639bdfd-8484-4d74-afff-e877a6386062',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'AuthService.ts:login:parse-error',message:'Failed to parse error response as JSON',data:{parseError:parseError?.message,responsePreview:responseText.substring(0,300)},timestamp:Date.now(),sessionId:'debug-session',hypothesisId:'A,C,D'})}).catch(()=>{});
        // #endregion
        throw new Error(`Login failed: Server returned non-JSON response (${response.status})`);
      }
    }

    try {
      const data = JSON.parse(responseText);
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/3639bdfd-8484-4d74-afff-e877a6386062',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'AuthService.ts:login:success',message:'Login successful',data:{hasToken:!!data.access_token},timestamp:Date.now(),sessionId:'debug-session',hypothesisId:'success'})}).catch(()=>{});
      // #endregion
      return data.access_token;
    } catch (parseError: any) {
      // #region agent log
      fetch('http://127.0.0.1:7242/ingest/3639bdfd-8484-4d74-afff-e877a6386062',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({location:'AuthService.ts:login:success-parse-error',message:'Failed to parse success response',data:{parseError:parseError?.message,responsePreview:responseText.substring(0,300)},timestamp:Date.now(),sessionId:'debug-session',hypothesisId:'D'})}).catch(()=>{});
      // #endregion
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
