import atexit
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import random
import time
import logging
import json
from typing import Optional, List
from urllib.parse import quote

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── One global driver we keep alive ────────────────────────────────────────────
_driver = None

# List of common user agents
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15"
]

def _random_delay(min_seconds: float = 1.0, max_seconds: float = 3.0):
    """Add random delay to mimic human behavior."""
    time.sleep(random.uniform(min_seconds, max_seconds))

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
    """Handle CAPTCHA detection by waiting for user input."""
    if _detect_captcha(driver):
        logger.warning("CAPTCHA detected! Waiting for manual intervention...")
        try:
            # Wait for CAPTCHA to be solved (up to 5 minutes)
            WebDriverWait(driver, 300).until_not(
                lambda d: _detect_captcha(d)
            )
            logger.info("CAPTCHA appears to be solved!")
            return True
        except:
            logger.error("CAPTCHA handling timeout!")
            return False
    return True

def _init_driver(headless: bool = False, proxy: Optional[str] = None):
    """Create the global Firefox driver once with anti-detection measures."""
    global _driver
    if _driver is not None:
        return _driver

    try:
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("--headless")

        # Add anti-detection measures
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)

        # Set random user agent
        options.set_preference("general.useragent.override", random.choice(USER_AGENTS))

        # Add proxy if provided
        if proxy:
            options.set_preference("network.proxy.type", 1)
            options.set_preference("network.proxy.http", proxy)
            options.set_preference("network.proxy.http_port", 8080)
            options.set_preference("network.proxy.ssl", proxy)
            options.set_preference("network.proxy.ssl_port", 8080)

        # Additional options for stability
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        service = FirefoxService(executable_path=GeckoDriverManager().install())
        _driver = webdriver.Firefox(service=service, options=options)

        # Set window size to a reasonable default
        _driver.set_window_size(1280, 800)

        # Add random viewport size
        viewport_width = random.randint(1024, 1920)
        viewport_height = random.randint(768, 1080)
        _driver.execute_script(f"window.resizeTo({viewport_width}, {viewport_height});")

        # Make sure we close the browser when Python exits
        atexit.register(lambda: _driver.quit() if _driver else None)
        logger.info("Firefox WebDriver initialized successfully")
        return _driver
    except Exception as e:
        logger.error(f"Failed to initialize Firefox WebDriver: {e}")
        raise

def clear_browser_cache():
    """Clear the browser cache."""
    try:
        driver = _init_driver()
        # Open about:preferences page for clearing cache via UI (Firefox method)
        driver.get("about:preferences#privacy")

        # Wait for page to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "clear-data-dialog"))
        )

        # Click the 'Clear Data' button
        clear_data_button = driver.find_element(By.XPATH, "//button[contains(@id, 'clear-data-dialog')]")
        _random_delay()
        clear_data_button.click()

        # Wait for dialog to open and select all data types
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "clearDataDialog"))
        )

        # Select cache checkbox if present (it might already be selected)
        try:
            cache_checkbox = driver.find_element(By.XPATH, "//label[@for='cache']")
            _random_delay()
            if not cache_checkbox.get_attribute("aria-checked") == "true":
                cache_checkbox.click()
        except:
            pass  # Cache checkbox might not be found or already checked

        # Click the clear button
        confirm_button = driver.find_element(By.XPATH, "//button[@id='clearDataDialog']//*[contains(text(), 'Clear')]")
        _random_delay()
        confirm_button.click()

        # Wait for clearing to complete and close preferences tab
        WebDriverWait(driver, 10).until_not(
            EC.presence_of_element_located((By.ID, "clear-data-dialog"))
        )

        driver.close()  # Close the preferences tab

        logger.info("Successfully cleared browser cache")
        return "✅ Browser cache has been cleared"
    except Exception as e:
        error_msg = f"Failed to clear browser cache: {str(e)}"
        logger.error(error_msg)
        return f"❌ Error clearing browser cache: {error_msg}"

def open_new_tab(url: str, headless: bool = False, proxy: Optional[str] = None) -> str:
    """Open URL in a new tab with CAPTCHA handling."""
    if not url:
        raise ValueError("URL must not be empty")

    try:
        driver = _init_driver(headless=headless, proxy=proxy)
        _random_delay()

        # If this is the first call, driver has one blank tab. Load URL there.
        if len(driver.window_handles) == 1 and driver.current_url in ("about:blank", "data:"):
            driver.get(url)
        else:
            driver.execute_script(f"window.open('{url}', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])

        # Check for CAPTCHA
        if not _handle_captcha(driver):
            return "⚠️ CAPTCHA detected and not solved. Please try again."

        logger.info(f"Successfully opened URL: {url}")
        return f"✅ Opened: {url}"
    except WebDriverException as e:
        error_msg = f"Failed to open URL: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

def search_google(query: str, headless: bool = False, proxy: Optional[str] = None) -> str:
    """Perform a Google search with CAPTCHA handling."""
    if not query:
        raise ValueError("Search query must not be empty")

    try:
        # URL encode the query
        encoded_query = quote(query)
        google_url = f"https://www.google.com/search?q={encoded_query}"

        # Add random delay before search
        _random_delay(2.0, 4.0)

        result = open_new_tab(google_url, headless=headless, proxy=proxy)

        # Add random delay after search
        _random_delay(1.0, 2.0)

        return result
    except Exception as e:
        error_msg = f"Failed to perform Google search: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

def navigate_to(url: str, headless: bool = False, proxy: Optional[str] = None) -> str:
    """Navigate to a URL with CAPTCHA handling."""
    if not url:
        raise ValueError("URL must not be empty")

    try:
        driver = _init_driver(headless=headless, proxy=proxy)
        _random_delay()

        driver.get(url)

        # Check for CAPTCHA
        if not _handle_captcha(driver):
            return "⚠️ CAPTCHA detected and not solved. Please try again."

        logger.info(f"Successfully navigated to: {url}")
        return f"✅ Navigated to: {url}"
    except WebDriverException as e:
        error_msg = f"Failed to navigate to URL: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

def execute_nlp_browser_command(command: str, headless: bool = False, proxy: Optional[str] = None) -> str:
    """
    Execute browser command based on NLP processed input.
    Args:
        command (str): The natural language command to process
        headless (bool): Whether to run in headless mode
        proxy (Optional[str]): Proxy server for the browser session

    Returns:
        str: Result message of the executed action
    """
    import re

    # Normalize and lower-case the input
    command_lower = command.lower().strip()

    # Define regex patterns for different commands
    open_tab_patterns = [
        r'^open a new tab and go to (.+)',
        r'^launch a new tab and navigate to (.+)'
    ]

    search_patterns = [
        r'search for (.+)$',
        r'look up (.+)$',
        r'find (.+)$',
        r'what is (.+)$',
        r'tell me about (.+)$'
    ]

    # Check for URL in command
    url_pattern = re.compile(r'(?:https?:\/\/)?(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)')

    # Extract URL if present
    url_match = re.search(url_pattern, command)
    if url_match:
        url = url_match.group()
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return open_new_tab(url, headless=headless, proxy=proxy)

    # Check for clear browser cache commands
    if "clear browser cache" in command_lower or "hey clear browser cache" in command_lower:
        return clear_browser_cache()

    # Check for open tab commands
    for pattern in open_tab_patterns:
        match = re.search(pattern, command_lower)
        if match:
            url = match.group(1).strip()
            return open_new_tab(url, headless=headless, proxy=proxy)

    # Check for search commands
    for pattern in search_patterns:
        match = re.search(pattern, command_lower)
        if match:
            query = match.group(1).strip()
            return search_google(query, headless=headless, proxy=proxy)

    # Default: Try to interpret as a URL and open it
    return navigate_to(command, headless=headless, proxy=proxy)
