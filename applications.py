"""One-time, two-step confirmation for HeadHunter applications."""

from __future__ import annotations

import asyncio
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from hh_client import HHClient
from output_safety import external_field
from validation import InvalidInputError, validate_cover_letter, validate_decimal_id, validate_resume_id


CONFIRMATION_TTL_SECONDS = 10 * 60


class ApplicationDisabledError(RuntimeError):
    """Raised when write operations are disabled by configuration."""


@dataclass(frozen=True)
class PendingApplication:
    vacancy_id: str
    resume_id: str
    letter: str | None
    expires_at: float


class ApplicationConfirmationStore:
    """Keep short-lived confirmations in memory and consume them atomically."""

    def __init__(self, ttl_seconds: int = CONFIRMATION_TTL_SECONDS):
        self._ttl_seconds = ttl_seconds
        self._pending: dict[str, PendingApplication] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        vacancy_id: str,
        resume_id: str,
        letter: str | None,
    ) -> tuple[str, PendingApplication]:
        pending = PendingApplication(
            vacancy_id=vacancy_id,
            resume_id=resume_id,
            letter=letter,
            expires_at=time.monotonic() + self._ttl_seconds,
        )
        token = secrets.token_urlsafe(32)
        async with self._lock:
            self._remove_expired_locked()
            self._pending[token] = pending
        return token, pending

    async def consume(self, token: str) -> PendingApplication:
        if not isinstance(token, str) or not token or len(token) > 128:
            raise InvalidInputError("confirmation_token is invalid")

        async with self._lock:
            pending = self._pending.pop(token, None)
            if pending is None:
                raise InvalidInputError(
                    "confirmation_token is unknown, expired, or already used"
                )
            if pending.expires_at <= time.monotonic():
                raise InvalidInputError("confirmation_token has expired")
            return pending

    def _remove_expired_locked(self) -> None:
        now = time.monotonic()
        expired = [
            token
            for token, pending in self._pending.items()
            if pending.expires_at <= now
        ]
        for token in expired:
            del self._pending[token]


def applications_enabled() -> bool:
    """Require an explicit true value before any real application is sent."""
    return os.getenv("HH_ENABLE_APPLICATIONS", "").lower() == "true"


class ApplicationService:
    def __init__(
        self,
        client: HHClient,
        store: ApplicationConfirmationStore | None = None,
    ):
        self._client = client
        self._store = store or ApplicationConfirmationStore()

    async def prepare(
        self,
        vacancy_id: str,
        resume_id: str,
        letter: str | None = None,
    ) -> dict[str, Any]:
        vacancy_id = validate_decimal_id(vacancy_id, "vacancy_id")
        resume_id = validate_resume_id(resume_id)
        letter = validate_cover_letter(letter)

        vacancy = await self._client.get_vacancy(vacancy_id)
        resume = await self._client.get_resume(resume_id)
        token, _ = await self._store.create(vacancy_id, resume_id, letter)

        return {
            "confirmation_token": token,
            "expires_in_seconds": CONFIRMATION_TTL_SECONDS,
            "sending_enabled": applications_enabled(),
            "vacancy": {
                "id": vacancy.get("id", vacancy_id),
                "name": external_field(vacancy.get("name")),
                "employer": external_field(
                    vacancy.get("employer", {}).get("name")
                ),
                "url": vacancy.get("alternate_url"),
            },
            "resume": {
                "id": resume.get("id", resume_id),
                "title": external_field(resume.get("title")),
            },
            "letter": letter or "",
        }

    async def confirm(self, confirmation_token: str) -> dict[str, Any]:
        if not applications_enabled():
            raise ApplicationDisabledError(
                "Application sending is disabled. Set HH_ENABLE_APPLICATIONS=true "
                "to enable confirmed applications."
            )

        pending = await self._store.consume(confirmation_token)
        return await self._client.apply_to_vacancy(
            vacancy_id=pending.vacancy_id,
            resume_id=pending.resume_id,
            letter=pending.letter,
        )
