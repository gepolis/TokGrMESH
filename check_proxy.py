import requests
import concurrent.futures
from typing import List, Dict, Tuple
import time
import os

PROXY_FILE = "C:\\Users\\NAVI\\PycharmProjects\\MosRu\\pr.txt"
TEST_URL = "https://httpbin.org/ip"  # HTTPS для проверки работы с HTTPS сайтами
TIMEOUT = 15  # Увеличил таймаут для надежности
MAX_WORKERS = 500  # Увеличил количество потоков
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


def load_proxies(file_path: str) -> List[Dict]:
    """Загружаем прокси из файла и парсим их"""
    proxies = []
    if not os.path.exists(file_path):
        return proxies

    with open(file_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            parts = line.split(':')
            proxy = {
                'ip': parts[0],
                'port': parts[1],
                'auth': None
            }

            if len(parts) >= 4:  # Если есть логин и пароль
                proxy['auth'] = {
                    'username': parts[2],
                    'password': parts[3]
                }

            proxies.append(proxy)

    return proxies


def check_proxy(proxy: Dict) -> Tuple[Dict, bool, float]:
    """Проверяем один прокси с замером времени отклика"""
    proxy_str = f"{proxy['ip']}:{proxy['port']}"
    if proxy['auth']:
        proxy_str = f"{proxy['auth']['username']}:{proxy['auth']['password']}@{proxy_str}"

    proxies_config = {
        "http": f"http://{proxy_str}",
        "https": f"http://{proxy_str}"
    }

    start_time = time.time()
    try:
        response = requests.get(
            TEST_URL,
            proxies=proxies_config,
            headers={"User-Agent": USER_AGENT},
            timeout=TIMEOUT
        )
        response_time = round((time.time() - start_time) * 1000)  # В миллисекундах

        if response.status_code == 200:
            return (proxy, True, response_time)
    except Exception as e:
        response_time = round((time.time() - start_time) * 1000)

    return (proxy, False, response_time)


def check_all_proxies(proxies: List[Dict]) -> List[Dict]:
    """Проверяем все прокси с многопоточностью"""
    results = []
    valid_count = 0

    print(f"\n🔍 Проверяем {len(proxies)} прокси...\n")

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(check_proxy, proxy) for proxy in proxies]

        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            proxy, is_valid, response_time = future.result()

            if is_valid:
                valid_count += 1
                status = "✅ РАБОЧИЙ"
                color = "\033[92m"  # Зеленый
            else:
                status = "❌ НЕ РАБОТАЕТ"
                color = "\033[91m"  # Красный

            # Красивое форматирование вывода
            auth_info = ""
            if proxy['auth']:
                auth_info = f" | 👤 {proxy['auth']['username']}:{'*' * len(proxy['auth']['password'])}"

            print(f"{color}{status}\033[0m | {proxy['ip']}:{proxy['port']}{auth_info} | ⏱ {response_time}ms")

            if is_valid:
                results.append({
                    'proxy': proxy,
                    'response_time': response_time
                })

    # Статистика
    print(f"\n📊 Результаты:")
    print(f"🔹 Всего проверено: {len(proxies)}")
    print(f"🔹 Рабочих: {valid_count} ")
    print(f"🔹 Не рабочих: {len(proxies) - valid_count}")

    return results


def save_valid_proxies(valid_proxies: List[Dict]):
    """Сохраняем рабочие прокси в файл"""
    with open(PROXY_FILE, 'w') as f:
        for item in valid_proxies:
            proxy = item['proxy']
            if proxy['auth']:
                line = f"{proxy['ip']}:{proxy['port']}:{proxy['auth']['username']}:{proxy['auth']['password']}\n"
            else:
                line = f"{proxy['ip']}:{proxy['port']}\n"
            f.write(line)

    print(f"\n💾 Сохранено {len(valid_proxies)} рабочих прокси в файл {PROXY_FILE}")


def main():
    print("=== 🔥 ПРОКСИ ЧЕКЕР (с авторизацией) ===")
    print("=== Для купленных прокси с логином/паролем ===\n")

    # Загрузка прокси
    proxies = load_proxies(PROXY_FILE)
    if not proxies:
        print(f"Файл {PROXY_FILE} не найден или пуст!")
        return

    # Проверка прокси
    valid_proxies = check_all_proxies(proxies)

    # Сохранение результатов
    if valid_proxies:
        save_valid_proxies(valid_proxies)

        # Сортировка по скорости
        fast_proxies = sorted(valid_proxies, key=lambda x: x['response_time'])[:5]
        print("\n🚀 Топ-5 самых быстрых прокси:")
        for i, item in enumerate(fast_proxies, 1):
            proxy = item['proxy']
            print(f"{i}. {proxy['ip']}:{proxy['port']} ({item['response_time']}ms)")
    else:
        print("\n😢 Не найдено ни одного рабочего прокси")


if __name__ == "__main__":
    main()