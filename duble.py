import os
import hashlib
from collections import defaultdict


def find_duplicate_captchas(folder_path):
    hashes = defaultdict(list)

    for filename in os.listdir(folder_path):
        if filename.lower().endswith(('.jpg', '.jpeg', '.png')):
            filepath = os.path.join(folder_path, filename)

            with open(filepath, 'rb') as f:
                file_data = f.read()
                file_hash = hashlib.md5(file_data).hexdigest()

            hashes[file_hash].append(filename)

    duplicates = {h: files for h, files in hashes.items() if len(files) > 1}

    return duplicates


def print_duplicates(duplicates):
    if not duplicates:
        print("Дубликаты не найдены.")
        return

    print(f"Найдено {len(duplicates)} групп дубликатов:")
    for i, (file_hash, files) in enumerate(duplicates.items(), 1):
        print(f"\nГруппа {i} (хеш: {file_hash}):")
        for file in files:
            print(f"  - {file}")


def main():
    captcha_folder = "captcha_collection"

    if not os.path.exists(captcha_folder):
        print(f"Папка {captcha_folder} не существует!")
        return

    print(f"Поиск дубликатов в папке {captcha_folder}...")
    duplicates = find_duplicate_captchas(captcha_folder)
    print_duplicates(duplicates)


if __name__ == "__main__":
    main()