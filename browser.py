import atexit
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.firefox.service import Service as FirefoxService
from webdriver_manager.firefox import GeckoDriverManager
from selenium.common.exceptions import WebDriverException
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── One global driver we keep alive ────────────────────────────────────────────
_driver = None

def _init_driver(headless: bool = False):
    """Create the global Firefox driver once."""
    global _driver
    if _driver is not None:
        return _driver

    try:
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("--headless")

        # Add some additional options for stability
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        service = FirefoxService(executable_path=GeckoDriverManager().install())
        _driver = webdriver.Firefox(service=service, options=options)
        
        # Set window size to a reasonable default
        _driver.set_window_size(1280, 800)

        # Make sure we close the browser when Python exits
        atexit.register(lambda: _driver.quit() if _driver else None)
        logger.info("Firefox WebDriver initialized successfully")
        return _driver
    except Exception as e:
        logger.error(f"Failed to initialize Firefox WebDriver: {e}")
        raise

def open_new_tab(url: str, headless: bool = False) -> str:
    """Open URL in a new tab (or first tab if none)."""
    if not url:
        raise ValueError("URL must not be empty")

    try:
        driver = _init_driver(headless=headless)

        # If this is the first call, driver has one blank tab. Load URL there.
        if len(driver.window_handles) == 1 and driver.current_url in ("about:blank", "data:"):
            driver.get(url)
        else:
            driver.execute_script(f"window.open('{url}', '_blank');")
            driver.switch_to.window(driver.window_handles[-1])

        logger.info(f"Successfully opened URL: {url}")
        return f"✅ Opened: {url}"
    except WebDriverException as e:
        error_msg = f"Failed to open URL: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

def search_google(query: str, headless: bool = False) -> str:
    """Perform a Google search and open the results."""
    if not query:
        raise ValueError("Search query must not be empty")

    try:
        # URL encode the query
        from urllib.parse import quote
        encoded_query = quote(query)
        google_url = f"https://www.google.com/search?q={encoded_query}"
        return open_new_tab(google_url, headless=headless)
    except Exception as e:
        error_msg = f"Failed to perform Google search: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)

def navigate_to(url: str, headless: bool = False) -> str:
    """Navigate to a URL in the browser."""
    if not url:
        raise ValueError("URL must not be empty")

    try:
        driver = _init_driver(headless=headless)
        driver.get(url)
        logger.info(f"Successfully navigated to: {url}")
        return f"✅ Navigated to: {url}"
    except WebDriverException as e:
        error_msg = f"Failed to navigate to URL: {str(e)}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
