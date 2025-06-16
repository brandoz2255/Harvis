# Browser Automation

This document details the browser automation components of the AI Voice Assistant, including natural language processing, search functionality, and anti-detection measures.

## Overview

The browser automation system allows the AI assistant to:
- Open new browser tabs
- Navigate to URLs
- Perform web searches
- Handle browser sessions
- Manage multiple tabs

## Natural Language Processing

### Command Detection
```python
def is_browser_command(message):
    """Determine if the message is actually a browser command."""
    message_lower = message.lower().strip()
    
    # Common browser command patterns
    browser_patterns = [
        r'^(?:please\s+)?(?:can\s+you\s+)?(?:open|launch|start)\s+(?:a\s+)?(?:new\s+)?(?:browser\s+)?(?:tab|window)',
        r'^(?:please\s+)?(?:can\s+you\s+)?(?:search|look\s+up|find)\s+(?:for\s+)?(?:information\s+about\s+)?',
        r'^(?:please\s+)?(?:can\s+you\s+)?(?:go\s+to|navigate\s+to|visit|open)\s+(?:the\s+)?(?:website\s+)?(?:at\s+)?',
    ]
```

### URL Extraction
```python
def extract_url(text):
    """Extract URL from text using improved pattern matching."""
    url_pattern = r'(?:https?:\/\/)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)'
```

### Search Query Extraction
```python
def extract_search_query(message):
    """Extract search query from message using improved pattern matching."""
    search_patterns = [
        r'(?:search|look\s+up|find)\s+(?:for\s+)?(?:information\s+about\s+)?(.+)',
        r'(?:what\s+is|who\s+is|where\s+is|how\s+to)\s+(.+)',
        r'(?:tell\s+me\s+about|show\s+me\s+information\s+about)\s+(.+)',
    ]
```

## Anti-Detection Measures

### Browser Fingerprinting
1. **User Agent Rotation**
   - Random selection from common user agents
   - Prevents consistent fingerprinting
   - Mimics different browsers and platforms

2. **Viewport Randomization**
   - Random window sizes
   - Dynamic viewport dimensions
   - Prevents consistent screen size fingerprinting

3. **Automation Flags**
   - Disabled automation indicators
   - Removed webdriver flags
   - Hidden automation attributes

### Proxy Support
```python
if proxy:
    options.set_preference("network.proxy.type", 1)
    options.set_preference("network.proxy.http", proxy)
    options.set_preference("network.proxy.http_port", 8080)
    options.set_preference("network.proxy.ssl", proxy)
    options.set_preference("network.proxy.ssl_port", 8080)
```

## CAPTCHA Handling

### Detection
```python
def _detect_captcha(driver) -> bool:
    """Detect if a CAPTCHA is present on the page."""
    captcha_indicators = [
        "//iframe[contains(@src, 'recaptcha')]",
        "//div[contains(@class, 'g-recaptcha')]",
        "//div[contains(@class, 'captcha')]",
        "//img[contains(@src, 'captcha')]"
    ]
```

### Handling
1. **Automatic Detection**
   - Multiple CAPTCHA type detection
   - Real-time monitoring
   - Pattern recognition

2. **User Intervention**
   - 5-minute timeout for manual solving
   - Clear feedback messages
   - Graceful error handling

## Natural Language Commands

### Supported Patterns
1. **Browser Control**
   - "Open a new tab"
   - "Launch browser"
   - "Start a new window"

2. **Navigation**
   - "Go to website"
   - "Visit [URL]"
   - "Navigate to [URL]"

3. **Search Queries**
   - "Search for [query]"
   - "Look up [query]"
   - "Find information about [query]"
   - "What is [query]"
   - "Who is [query]"
   - "How to [query]"

### Context Awareness
1. **Command Validation**
   - Prevents false positives
   - Context-based interpretation
   - Natural language understanding

2. **Query Processing**
   - Removes common question words
   - Handles various phrasings
   - Maintains query context

## Implementation

### Core Components

```python
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
import atexit

# Global driver instance
_driver = None

def _init_driver(headless: bool = False):
    """Initialize the Firefox WebDriver."""
    global _driver
    if _driver is not None:
        return _driver

    options = webdriver.FirefoxOptions()
    if headless:
        options.add_argument("--headless")
    
    # Additional options for stability
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    service = FirefoxService(executable_path=GeckoDriverManager().install())
    _driver = webdriver.Firefox(service=service, options=options)
    
    # Set window size
    _driver.set_window_size(1280, 800)
    
    # Register cleanup
    atexit.register(lambda: _driver.quit() if _driver else None)
    return _driver
```

## Key Features

### 1. Tab Management

```python
def open_new_tab(url: str, headless: bool = False) -> str:
    """Open URL in a new tab."""
    if not url:
        raise ValueError("URL must not be empty")

    try:
        driver = _init_driver(headless=headless)
        
        # Handle first tab or new tab
        if len(driver.window_handles) == 1 and driver.current_url in ("about:blank", "data:"):
            driver.get(url)
        else:
            driver.execute_script(f"window.open('{url}', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
            
        return f"✅ Opened: {url}"
    except Exception as e:
        logger.error(f"Failed to open URL: {e}")
        raise
```

### 2. Search Functionality

```python
def search_google(query: str, headless: bool = False) -> str:
    """Perform a Google search."""
    if not query:
        raise ValueError("Search query must not be empty")

    try:
        from urllib.parse import quote
        encoded_query = quote(query)
        google_url = f"https://www.google.com/search?q={encoded_query}"
        return open_new_tab(google_url, headless=headless)
    except Exception as e:
        logger.error(f"Failed to perform search: {e}")
        raise
```

### 3. Navigation

```python
def navigate_to(url: str, headless: bool = False) -> str:
    """Navigate to a URL."""
    if not url:
        raise ValueError("URL must not be empty")

    try:
        driver = _init_driver(headless=headless)
        driver.get(url)
        return f"✅ Navigated to: {url}"
    except Exception as e:
        logger.error(f"Failed to navigate: {e}")
        raise
```

## Error Handling

### Common Issues

1. **WebDriver Initialization**
   - Driver not found
   - Version mismatch
   - Permission issues
   - Resource constraints

2. **Browser Operations**
   - Timeout errors
   - Element not found
   - JavaScript errors
   - Network issues

3. **Session Management**
   - Memory leaks
   - Stale sessions
   - Resource exhaustion
   - Process termination

### Error Recovery

```python
def handle_browser_error(error):
    """Handle browser automation errors."""
    logger.error(f"Browser error: {error}")
    
    if "WebDriver" in str(error):
        return reinitialize_driver()
    elif "timeout" in str(error).lower():
        return retry_operation()
    elif "element" in str(error).lower():
        return wait_and_retry()
    else:
        return graceful_degradation()
```

## Performance Optimization

### 1. Resource Management

```python
def manage_browser_resources():
    """Manage browser resources."""
    if _driver:
        # Clear browser cache
        _driver.execute_script("window.localStorage.clear();")
        _driver.execute_script("window.sessionStorage.clear();")
        
        # Clear cookies
        _driver.delete_all_cookies()
```

### 2. Session Handling

```python
def optimize_session():
    """Optimize browser session."""
    if _driver:
        # Set page load timeout
        _driver.set_page_load_timeout(30)
        
        # Set script timeout
        _driver.set_script_timeout(30)
        
        # Enable JavaScript
        _driver.execute_script("return navigator.userAgent")
```

## Best Practices

### 1. Code Organization

- Separate browser operations
- Clear function interfaces
- Consistent error handling
- Resource cleanup

### 2. Error Handling

- Comprehensive try-catch blocks
- Detailed error logging
- User-friendly messages
- Recovery mechanisms

### 3. Performance

- Resource monitoring
- Session management
- Memory optimization
- Timeout handling

## Testing

### 1. Unit Tests

```python
def test_browser_operations():
    """Test browser operations."""
    # Test tab opening
    assert open_new_tab("https://example.com") == "✅ Opened: https://example.com"
    
    # Test search
    assert search_google("test query") == "✅ Opened: https://www.google.com/search?q=test+query"
    
    # Test navigation
    assert navigate_to("https://example.com") == "✅ Navigated to: https://example.com"
```

### 2. Integration Tests

- End-to-end testing
- Error scenario testing
- Performance testing
- Resource usage testing

## Interview Preparation

### Technical Questions

1. How is browser automation implemented?
2. What strategies handle errors?
3. How is performance optimized?
4. What are the security considerations?
5. How is the system tested?

### Implementation Questions

1. Why was Selenium chosen?
2. How are multiple tabs managed?
3. What are the failure points?
4. How is the system scaled?
5. What are the alternatives?

### Architecture Questions

1. How is the browser integrated?
2. What is the data flow?
3. How is state managed?
4. What are the security risks?
5. How is the system monitored?

## Common Use Cases

### 1. Web Navigation

```python
# Navigate to a website
navigate_to("https://example.com")

# Open in new tab
open_new_tab("https://example.com")
```

### 2. Search Operations

```python
# Google search
search_google("python programming")

# Complex search
search_google("python programming tutorials for beginners")
```

### 3. Tab Management

```python
# Open multiple tabs
open_new_tab("https://example1.com")
open_new_tab("https://example2.com")
```

## Security Considerations

### 1. Input Validation

```python
def validate_url(url: str) -> bool:
    """Validate URL format."""
    import re
    url_pattern = r'https?://\S+|www\.\S+'
    return bool(re.match(url_pattern, url))
```

### 2. Error Message Sanitization

```python
def sanitize_error(error: str) -> str:
    """Sanitize error messages."""
    # Remove sensitive information
    error = error.replace("password", "***")
    error = error.replace("token", "***")
    return error
```

### 3. Resource Cleanup

```python
def cleanup_resources():
    """Clean up browser resources."""
    if _driver:
        _driver.quit()
        global _driver
        _driver = None
```

## Future Improvements

### Planned Features
1. **Enhanced NLP**
   - More command patterns
   - Better context understanding
   - Improved query extraction

2. **Anti-Detection**
   - Advanced fingerprinting
   - Proxy rotation
   - Session management

3. **CAPTCHA Handling**
   - Automated solving
   - Better detection
   - Improved recovery
