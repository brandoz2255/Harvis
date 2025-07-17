# Walkthrough: Solving Persistent 401 Unauthorized Errors

This document details the troubleshooting process and solution for a persistent authentication issue where the Next.js frontend received `401 Unauthorized` errors from the Python FastAPI backend.

## The Problem

- **Symptom:** API calls from the browser to protected backend endpoints (e.g., `/api/chat`, `/api/chat-history/sessions`) consistently failed with a `401 Unauthorized` error.
- **Log Evidence:** The FastAPI backend logs showed `get_current_user called with credentials: None` and `No credentials provided`, confirming that the authentication dependency was not receiving the user's credentials.

## Initial Investigation & Failed Attempts

1.  **Hypothesis 1: Frontend is not sending credentials.**
    - **Action:** Added `credentials: 'include'` to all `fetch()` calls in the Next.js frontend (`.tsx` components and `AuthService.ts`).
    - **Result:** No change. The error persisted. This change was necessary for sending cookies, but it wasn't the root cause.

2.  **Hypothesis 2: Backend is rejecting the request due to CORS.**
    - **Action:** Added `CORSMiddleware` to the FastAPI application in `python_back_end/main.py`, explicitly allowing the frontend's origin (`http://localhost:3001`) and `allow_credentials=True`.
    - **Result:** No change. The error persisted. This was also a necessary configuration step for a robust setup, but not the core issue.

3.  **Hypothesis 3: Backend is not reading credentials from the right place.**
    - **Action:** Modified the `get_current_user` dependency to read the JWT from a cookie (`request.cookies.get("access_token")`) instead of the `Authorization: Bearer` header.
    - **Result:** This made the problem worse. Now, even direct API calls that used the bearer token failed. The logs showed `No credentials provided in cookies`.

## Root Cause Analysis

The core issue was a fundamental mismatch between how the frontend and backend handled the authentication token:

1.  **The Backend Never Set a Cookie:** The `/api/auth/login` endpoint correctly generated a JWT access token, but it only returned it in the JSON response body. It **never set this token as a cookie** in the browser.
2.  **The Frontend Never Used the Token for Cookies:** The frontend received the token in the JSON response but was only designed to store it in `localStorage` and use it for `Authorization: Bearer` headers. The `credentials: 'include'` setting was trying to send a cookie that never existed.
3.  **The Final Backend Change Was Too Restrictive:** By changing `get_current_user` to *only* look for a cookie, I broke the parts of the app that were correctly using the bearer token.

## The Correct Solution (Multi-Part)

The final, working solution required fixing both the backend's login logic and its token validation logic.

1.  **Modify the Login Endpoint to Set a Cookie:**
    - **File:** `python_back_end/main.py`
    - **Change:** The `/api/auth/login` endpoint was modified to return a `JSONResponse` and explicitly set the access token as a secure, `HttpOnly` cookie. This ensures the browser stores the credential correctly for subsequent requests.

    ```python
    # In the /api/auth/login endpoint:
    from fastapi.responses import JSONResponse

    # ... (inside the login function, after creating the token)
    access_token = create_access_token(...)
    
    # Create a JSON response and set the cookie on it
    response = JSONResponse(content={"access_token": access_token, "token_type": "bearer"})
    response.set_cookie(
        key="access_token",
        value=access_token,
        httponly=True,      # Prevents client-side script access
        samesite="lax",     # CSRF protection
        secure=False,       # Use True in production with HTTPS
    )
    return response
    ```

2.  **Make the Authentication Dependency More Robust:**
    - **File:** `python_back_end/main.py`
    - **Change:** The `get_current_user` dependency was updated to be flexible. It now checks for the token in two places, prioritizing the cookie.

    ```python
    # In the get_current_user function:
    async def get_current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(security)):
        # 1. First, try to get the token from the browser cookie
        token = request.cookies.get("access_token")
        
        # 2. If no cookie, fall back to the Authorization header
        if token is None and credentials is not None:
            token = credentials.credentials

        # 3. If still no token, raise an error
        if token is None:
            logger.error("No credentials provided in cookies or headers")
            raise credentials_exception
        
        # ... (rest of the JWT decoding and user lookup logic)
    ```

This two-pronged approach ensures that when a user logs in via the browser, a cookie is set and used for authentication, which works seamlessly with the `credentials: 'include'` setting on the frontend. It also maintains the ability for other clients to authenticate using a standard `Authorization: Bearer` token, making the API flexible.
