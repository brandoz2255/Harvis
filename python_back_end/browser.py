import atexit
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from selenium.webdriver.firefox.firefox_profile import FirefoxProfile
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import random
import time
import logging
import json
import shutil
import re
from typing import Optional, List, Literal, Union, Dict
from urllib.parse import urlparse, urljoin
import platform
import subprocess  # nosec
import os
from selenium_stealth import stealth

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── One global driver we keep alive ────────────────────────────────────────────
_driver = None

# List of common user agents - expanded and updated list
USER_AGENTS = [
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:119.0) Gecko/20100101 Firefox/119.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:119.0) Gecko/20100101 Firefox/119.0"
]

def detect_installed_browsers() -> List[str]:
    """Detect which browsers are installed on the system."""
    browsers = []
    system = platform.system().lower()

    def check_linux_browser(commands):
        for cmd in commands:
            if shutil.which(cmd):
                return True
        return False

    if system == "linux":
        # Check Firefox (multiple possible binary names)
        if check_linux_browser(['firefox', 'firefox-esr', 'firefox-bin']):
            browsers.append("firefox")

    elif system == "darwin":  # macOS
        # Check Firefox
        firefox_paths = [
            "/Applications/Firefox.app",
            os.path.expanduser("~/Applications/Firefox.app")
        ]
        if any(os.path.exists(path) for path in firefox_paths):
            browsers.append("firefox")

    elif system == "windows":
        # Check Firefox
        firefox_paths = [
            "C:\\Program Files\\Mozilla Firefox\\firefox.exe",
            "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
            os.path.expanduser("~\\AppData\\Local\\Mozilla Firefox\\firefox.exe")
        ]
        if any(os.path.exists(path) for path in firefox_paths):
            browsers.append("firefox")

    logger.info(f"Detected browsers: {browsers}")
    return browsers

def _random_delay(min_seconds: float = 1.0, max_seconds: float = 3.0):
    """Add random delay with human-like variation."""
    base_delay = random.uniform(min_seconds, max_seconds)
    # Add small random variations to seem more human
    micro_delays = [random.uniform(0.1, 0.3) for _ in range(random.randint(1, 3))]
    total_delay = base_delay + sum(micro_delays)
    time.sleep(total_delay)

def _detect_captcha(driver) -> bool:
    """Detect if a CAPTCHA is present on the page."""
    captcha_indicators = [
        "//iframe[contains(@src, 'recaptcha')]",
        "//div[contains(@class, 'g-recaptcha')]",
        "//div[contains(@class, 'captcha')]",
        "//img[contains(@src, 'captcha')]"
    ]
    
    for indicator in captcha_indicators:
        try:
            if driver.find_elements(By.XPATH, indicator):
                return True
        except:
            continue
    return False

def _handle_captcha(driver) -> bool:
    """Attempt to handle or bypass CAPTCHA."""
    try:
        # Wait for CAPTCHA iframe
        iframe = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "iframe[title*='recaptcha']"))
        )
        
        # Switch to iframe
        driver.switch_to.frame(iframe)
        
        # Add random delay before clicking
        _random_delay(1.0, 3.0)
        
        # Click checkbox with random delay
        checkbox = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".recaptcha-checkbox-border"))
        )
        checkbox.click()
        
        # Switch back to main content
        driver.switch_to.default_content()
        
        # Wait to see if CAPTCHA was solved
        _random_delay(2.0, 4.0)
        
        return not _detect_captcha(driver)
        
    except Exception as e:
        logger.error(f"Error handling CAPTCHA: {e}")
        return False

def _get_random_viewport():
    """Get random but realistic viewport dimensions."""
    common_resolutions = [
        (1920, 1080), (1366, 768), (1536, 864),
        (1440, 900), (1280, 720), (1600, 900)
    ]
    return random.choice(common_resolutions)

def _add_browser_features(driver):
    """Add common browser features to appear more human-like."""
    features = [
        # Common browser features
        'navigator.webdriver=undefined;',
        'navigator.languages=["en-US","en"];',
        'navigator.plugins.length=3;',
        'navigator.platform="Win32";',
        'navigator.maxTouchPoints=0;',
        'navigator.hardwareConcurrency=8;',
        # WebGL properties
        'WebGLRenderingContext.prototype.getParameter=getParameter;',
        # Screen properties
        f'Object.defineProperty(screen, "width", {{get: function() {{return {_get_random_viewport()[0]};}}}});',
        f'Object.defineProperty(screen, "height", {{get: function() {{return {_get_random_viewport()[1]};}}}});',
        # Canvas fingerprint randomization
        'HTMLCanvasElement.prototype.toDataURL=function(){return "data:image/png;base64,";};'
    ]
    
    for feature in features:
        try:
            driver.execute_script(feature)
        except Exception as e:
            logger.warning(f"Could not execute firefox stealth script, error: {e}")

def _add_stealth_js(driver):
    """Add additional stealth JavaScript to make automation harder to detect."""
    stealth_js = """
    // Override navigator properties
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    
    // Override permissions
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
    );
    
    // Override webGL
    HTMLCanvasElement.prototype.toDataURL = function() {
        return 'data:image/png;base64,';
    };
    
    // Add fake plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [
            {
                0: {type: "application/x-google-chrome-pdf", suffixes: "pdf", description: "Portable Document Format"},
                description: "Chrome PDF Plugin",
                filename: "internal-pdf-viewer",
                name: "Chrome PDF Plugin",
                length: 1
            },
            {
                0: {type: "application/pdf", suffixes: "pdf", description: "Portable Document Format"},
                description: "Chrome PDF Viewer",
                filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai",
                name: "Chrome PDF Viewer",
                length: 1
            }
        ]
    });
    """
    try:
        driver.execute_script(stealth_js)
    except:
        pass

def _create_undetected_firefox_profile():
    """Create a Firefox profile with enhanced stealth settings."""
    # Create a new temporary profile
    temp_dir = tempfile.mkdtemp()
    profile = FirefoxProfile(temp_dir)
    
    # Essential privacy and anti-detection preferences
    prefs = {
        # Disable automation indicators
        "dom.webdriver.enabled": False,
        "useAutomationExtension": False,
        "marionette": False,
        "toolkit.telemetry.enabled": False,
        
        # Privacy settings
        "privacy.resistFingerprinting": True,
        "privacy.trackingprotection.enabled": False,
        "privacy.trackingprotection.fingerprinting.enabled": False,
        "privacy.trackingprotection.cryptomining.enabled": False,
        "privacy.firstparty.isolate": True,
        
        # Disable various features that can be used for detection
        "media.navigator.enabled": False,
        "media.peerconnection.enabled": False,
        "dom.battery.enabled": False,
        "dom.gamepad.enabled": False,
        "dom.vibrator.enabled": False,
        "dom.webaudio.enabled": False,
        "dom.w3c_touch_events.enabled": False,
        
        # Network settings
        "network.http.referer.spoofSource": True,
        "network.http.sendRefererHeader": 0,
        "network.http.sendSecureXSiteReferrer": False,
        "network.cookie.lifetimePolicy": 2,
        "network.dns.disablePrefetch": True,
        "network.prefetch-next": False,
        "network.predictor.enabled": False,
        "network.predictor.enable-prefetch": False,
        
        # WebGL and Canvas
        "webgl.disabled": True,
        "canvas.capturestream.enabled": False,
        "canvas.poisondata": True,
        
        # Disable Firefox-specific features
        "beacon.enabled": False,
        "browser.cache.disk.enable": False,
        "browser.cache.memory.enable": False,
        "browser.cache.offline.enable": False,
        "browser.send_pings": False,
        "browser.sessionstore.privacy_level": 2,
        "browser.urlbar.filter.javascript": True,
        "browser.zoom.siteSpecific": False,
        
        # Additional security settings
        "security.ssl.disable_session_identifiers": True,
        "security.ssl.errorReporting.automatic": False,
        "security.tls.version.min": 1,
        
        # Disable various protocols
        "network.websocket.enabled": False,
        "network.http.spdy.enabled": False,
        "network.http.altsvc.enabled": False,
        "network.proxy.socks_remote_dns": True,
        
        # Font settings
        "gfx.downloadable_fonts.enabled": False,
        "gfx.downloadable_fonts.woff2.enabled": False,
        
        # Misc
        "javascript.options.shared_memory": False,
        "dom.serviceWorkers.enabled": False,
        "dom.storage.enabled": False,
        "dom.enable_performance": False,
        "geo.enabled": False,
        "geo.wifi.uri": False,
        "browser.search.geoip.url": False
    }
    
    # Apply all preferences
    for pref, value in prefs.items():
        profile.set_preference(pref, value)
    
    # Set random user agent
    profile.set_preference("general.useragent.override", 
                          random.choice([ua for ua in USER_AGENTS if "Firefox" in ua]))  # nosec
    
    return profile

def clean_search_query(query: str) -> str:
    """Clean up search query by removing command words."""
    # Remove common command prefixes in English and Spanish
    prefixes = [
        'search for', 'search', 'look up', 'find', 'google',
        'busca', 'buscar', 'encuentra', 'investigar', 'investiga',
        'información sobre', 'informacion sobre'
    ]
    
    query = query.lower().strip()
    for prefix in prefixes:
        if query.startswith(prefix):
            query = query[len(prefix):].strip()
    
    return query

def _init_driver(headless: bool = False, proxy: Optional[str] = None):
    """Create the global driver with enhanced undetected support for Firefox."""
    global _driver

    if _driver is not None:
        return _driver

    # Always use Firefox
    options = webdriver.FirefoxOptions()
    if headless:
        options.add_argument("--headless")

    # Create undetected Firefox profile with private browsing
    profile = _create_undetected_firefox_profile()

    # Enable private browsing
    profile.set_preference("browser.privatebrowsing.autostart", True)

    # Additional privacy settings
    profile.set_preference("privacy.trackingprotection.enabled", True)
    profile.set_preference("network.cookie.cookieBehavior", 1)  # Block third-party cookies
    profile.set_preference("privacy.donottrackheader.enabled", True)
    profile.set_preference("privacy.trackingprotection.cryptomining.enabled", True)
    profile.set_preference("privacy.trackingprotection.fingerprinting.enabled", True)

    # Add proxy if provided
    if proxy:
        profile.set_preference("network.proxy.type", 1)
        profile.set_preference("network.proxy.http", proxy)
        profile.set_preference("network.proxy.http_port", 8080)
        profile.set_preference("network.proxy.ssl", proxy)
        profile.set_preference("network.proxy.ssl_port", 8080)

    # Additional Firefox-specific arguments
    options.add_argument("--private")
    options.add_argument("--no-remote")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-infobars")

    # Use custom profile
    options.profile = profile

    try:
        service = FirefoxService(executable_path=GeckoDriverManager().install())
        _driver = webdriver.Firefox(service=service, options=options)
    except Exception as e:
        logger.error(f"Failed to initialize Firefox with GeckoDriverManager: {e}")
        # Try with system Firefox if available
        if shutil.which('firefox'):
            _driver = webdriver.Firefox(options=options)
        else:
            raise

    # Apply additional stealth measures
    _add_firefox_stealth(_driver)

    # Set window size and viewport
    viewport_width, viewport_height = _get_random_viewport()
    _driver.set_window_size(viewport_width, viewport_height)

    # Add common browser features and stealth
    _add_browser_features(_driver)
    _add_stealth_js(_driver)

    # Add random delay before first action
    _random_delay(1.0, 3.0)

    # Make sure we close the browser when Python exits
    atexit.register(lambda: _driver.quit() if _driver else None)
    logger.info("Firefox WebDriver initialized successfully")
    return _driver

def _add_firefox_stealth(driver):
    """Add Firefox-specific stealth measures."""
    # Inject Firefox-specific stealth JavaScript
    firefox_stealth_js = """
    // Override Firefox-specific properties
    Object.defineProperty(window, 'InstallTrigger', {
        get: () => true
    });
    
    // Override navigator properties
    Object.defineProperty(navigator, 'deviceMemory', {
        get: () => 8
    });
    Object.defineProperty(navigator, 'hardwareConcurrency', {
        get: () => 8
    });
    Object.defineProperty(navigator, 'connection', {
        get: () => ({
            effectiveType: '4g',
            rtt: 50,
            downlink: 10,
            saveData: false
        })
    });
    
    // Add Firefox-specific plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => [{
            0: {
                type: 'application/x-shockwave-flash',
                suffixes: 'swf',
                description: 'Shockwave Flash'
            },
            description: 'Shockwave Flash',
            filename: 'plugin.x-shockwave-flash',
            name: 'Shockwave Flash',
            length: 1
        }]
    });
    
    // Override performance timing
    const originalGetEntries = window.performance.getEntries;
    window.performance.getEntries = function() {
        const entries = originalGetEntries.apply(this, arguments);
        return entries.map(entry => {
            entry.duration += Math.random() * 100;
            return entry;
        });
    };
    """
    try:
        driver.execute_script(firefox_stealth_js)
    except Exception as e:
        logger.warning(f"Could not execute firefox stealth script, error: {e}")

def open_blank_tabs(count: int = 1) -> str:
    """Open specified number of blank tabs."""
    try:
        if count < 1:
            return "Please specify a positive number of tabs."
        
        if count > 10:
            return "For stability, please open 10 or fewer tabs at once."
        
        driver = _init_driver()
        
        # Add random delay between tabs
        for i in range(count):
            if i > 0:  # Don't delay before the first tab
                _random_delay(0.2, 0.5)
            
            driver.execute_script("window.open('about:blank', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
        
        return f"Opened {count} new {'tab' if count == 1 else 'tabs'}"
        
    except Exception as e:
        logger.error(f"Error opening blank tabs: {e}")
        return "Had trouble opening the tabs. Please try again."

def extract_number_from_text(text: str) -> int:
    """Extract number of tabs to open from text."""
    number_words = {
        'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5,
        'six': 6, 'seven': 7, 'eight': 8, 'nine': 9, 'ten': 10,
        'uno': 1, 'dos': 2, 'tres': 3, 'cuatro': 4, 'cinco': 5,
        'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10
    }
    
    # First try to find written numbers
    words = text.lower().split()
    for word in words:
        if word in number_words:
            return number_words[word]
    
    # Then try to find numeric digits
    numbers = re.findall(r'\d+', text)
    if numbers:
        return min(int(numbers[0]), 10)  # Limit to 10 tabs
    
    return 1  # Default to 1 if no number found

def is_valid_domain(url: str) -> bool:
    """Check if the URL has a valid domain extension."""
    valid_tlds = {
        'com', 'org', 'edu', 'gov', 'net', 'io', 'ai', 'app',
        'dev', 'me', 'info', 'blog', 'co', 'us', 'uk', 'eu'
    }
    try:
        domain = urlparse(url).netloc or url
        return any(domain.endswith('.' + tld) for tld in valid_tlds)
    except:
        return False

def normalize_url(url: str) -> str:
    """Normalize URL format."""
    if not url:
        return url
        
    # Remove common prefixes from voice recognition
    url = re.sub(r'^(?:go to|navigate to|open|visit)\s+', '', url.lower().strip())
    
    # Handle special cases
    if url == "blank" or url == "empty":
        return "about:blank"
    
    # Add https:// if no protocol specified
    if not url.startswith(('http://', 'https://', 'about:')):
        url = 'https://' + url
    
    return url

def smart_url_handler(text: str) -> Union[str, Dict[str, str]]:
    """Intelligently determine if text is a URL, search query, or domain."""
    text = text.lower().strip()
    
    # Handle blank tab requests
    if re.search(r'\b(blank|empty|new)\s+tab', text):
        return "about:blank"
    
    # Extract potential URL
    url_match = re.search(r'(?:https?:\/\/)?(?:www\.)?([a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,})', text)
    if url_match:
        domain = url_match.group(1)
        if is_valid_domain(domain):
            return normalize_url(domain)
    
    # If it looks like a domain but without TLD, assume .com
    domain_match = re.search(r'\b([a-zA-Z0-9-]+)(?:\s+dot\s+com|\s+dot\s+org)?\b', text)
    if domain_match:
        domain = domain_match.group(1)
        if len(domain) > 2 and not re.search(r'\b(search|find|look|busca)\b', text):
            return normalize_url(f"{domain}.com")
    
    # Otherwise, treat as search query
    return {"type": "search", "query": text}

def open_new_tab(url: str, headless: bool = False, proxy: Optional[str] = None) -> str:
    """Open a new browser tab with the specified URL."""
    if not url:
        return "about:blank"

    try:
        driver = _init_driver(headless=headless, proxy=proxy)
        
        # Clean up the URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # If this is the first tab and it's empty, use it
        if len(driver.window_handles) == 1:
            current_url = driver.current_url
            if current_url == "data:," or current_url == "about:blank":
                logger.info(f"Using initial tab for {url}")
                driver.get(url)
                return f"Opened {url}"
        
        # Otherwise, open a new tab
        logger.info(f"Opening new tab with {url}")
        # Create new tab with JavaScript
        driver.execute_script(f"window.open('{url}', '_blank');")
        
        # Switch to the new tab
        driver.switch_to.window(driver.window_handles[-1])
        
        # Wait for the page to start loading
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") != "complete"
            )
        except TimeoutException:
            pass  # Page might load too fast to catch loading state
        
        # Add random delay to seem more human
        _random_delay(1.0, 2.0)
        
        return f"Opened {url}"
        
    except Exception as e:
        logger.error(f"Error opening new tab: {e}")
        if "ERR_NAME_NOT_RESOLVED" in str(e):
            return f"Could not find website {url}. Check the URL and try again."
        return "Had trouble opening the tab. Please try again."

def search_google(query: str, headless: bool = False, proxy: Optional[str] = None) -> str:
    """Enhanced Google search with additional anti-detection measures."""
    if not query:
        raise ValueError("Search query must not be empty")
    
    try:
        # Clean up the query first
        cleaned_query = clean_search_query(query)
        if not cleaned_query:
            return "Please provide a search term"
        
        # Initialize driver if not already initialized
        driver = _init_driver(headless=headless, proxy=proxy)
        
        # Add some randomization to the search URL
        search_params = [
            "https://www.google.com/search?q=",
            "https://google.com/search?source=hp&q=",
            "https://www.google.com/search?source=hp&ei=random&q="
        ]
        search_url = random.choice(search_params) + cleaned_query.replace(" ", "+")  # nosec  # nosec
        
        # Random pre-search delay
        _random_delay(0.5, 2.0)
        
        # If this is the first tab and it's empty, use it
        if len(driver.window_handles) == 1:
            current_url = driver.current_url
            if current_url == "data:," or current_url == "about:blank":
                driver.get(search_url)
            else:
                # Open in new tab
                driver.execute_script(f"window.open('{search_url}', '_blank');")
                driver.switch_to.window(driver.window_handles[-1])
        else:
            # Open in new tab
            driver.execute_script(f"window.open('{search_url}', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])
        
        # Wait for search results with random delay
        try:
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "search"))
            )
            logger.info(f"Successfully searched for: {cleaned_query}")
            return f"Searching for '{cleaned_query}'"
        except TimeoutException:
            logger.warning("Search results took too long to load")
            return f"Started search for '{cleaned_query}' but it's taking longer than usual"
            
    except Exception as e:
        logger.error(f"Error during Google search: {e}")
        return "Had trouble with the search. Please try again."

def navigate_to(url: str) -> str:
    """Navigate the current tab to the specified URL."""
    try:
        driver = _init_driver()
        
        # Clean up the URL
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Get current window handle
        current_handle = driver.current_window_handle
        
        # Navigate
        driver.get(url)
        
        # Wait for page to start loading
        try:
            WebDriverWait(driver, 10).until(
                lambda d: d.execute_script("return document.readyState") != "complete"
            )
        except TimeoutException:
            pass  # Page might load too fast to catch loading state
        
        return f"Navigating to {url}"
        
    except Exception as e:
        logger.error(f"Error navigating to URL: {e}")
        if "ERR_NAME_NOT_RESOLVED" in str(e):
            return f"Could not find website {url}. Check the URL and try again."
        return "Had trouble navigating to the page. Please try again."

def get_current_browser() -> Optional[Literal["firefox", "chrome"]]:
    """Get the currently active browser type."""
    return _browser_type
