#!/usr/bin/env python3
import asyncio
import os
import time
from urllib.parse import urlencode

import httpx
from dotenv import load_dotenv

from token_store import OAuthTokens, build_token_store

load_dotenv()

CLIENT_ID = os.getenv("HH_CLIENT_ID")
CLIENT_SECRET = os.getenv("HH_CLIENT_SECRET")
REDIRECT_URI = os.getenv("HH_REDIRECT_URI")


def get_auth_url():
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": "negotiations",
    }
    return f"https://hh.ru/oauth/authorize?{urlencode(params)}"


async def exchange_code(code: str):
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.hh.ru/token",
            data={
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "code": code,
                "redirect_uri": REDIRECT_URI,
            },
        )
        response.raise_for_status()
        return response.json()


async def main():
    print("=" * 60)
    print("HeadHunter OAuth Authorization")
    print("=" * 60)
    print("\n1. Откройте эту ссылку в браузере:\n")
    print(get_auth_url())
    print("\n2. Авторизуйтесь и разрешите доступ")
    print("3. Скопируйте код из URL (после ?code=)\n")

    code = input("Введите код авторизации: ").strip()

    print("\nОбмен кода на токены...")
    tokens = await exchange_code(code)

    token_pair = OAuthTokens(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        expires_at=time.time() + tokens["expires_in"],
    )
    build_token_store().save(token_pair)
    print("\n✅ OAuth tokens stored securely in the system credential store")


if __name__ == "__main__":
    asyncio.run(main())
