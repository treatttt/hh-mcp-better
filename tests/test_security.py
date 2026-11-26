"""Focused tests for the security-critical workflows."""

from __future__ import annotations

import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from applications import (
    ApplicationConfirmationStore,
    ApplicationDisabledError,
    ApplicationService,
)
from hh_client import HHClient
from output_safety import external_document, resume_summary
from token_store import KeyringTokenStore, OAuthTokens, TokenStorageError
from validation import InvalidInputError

VACANCY_ID = "126209046"
RESUME_ID = "7b7f2ea6ff0838f1ea0039ed1f704b31506463"


class MemoryTokenStore:
    def __init__(self, tokens: OAuthTokens | None = None):
        self.tokens = tokens
        self.saved: list[OAuthTokens] = []

    def load(self) -> OAuthTokens | None:
        return self.tokens

    def save(self, tokens: OAuthTokens) -> None:
        self.tokens = tokens
        self.saved.append(tokens)


class FakeResponse:
    def __init__(self, status_code: int, payload=None, content: bytes = b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


def authenticated_client(store: MemoryTokenStore | None = None) -> HHClient:
    store = store or MemoryTokenStore(
        OAuthTokens("access-secret", "refresh-secret", time.time() + 3_600)
    )
    return HHClient(token_store=store)


class ConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def test_sending_is_disabled_by_default(self):
        client = MagicMock()
        client.apply_to_vacancy = AsyncMock()
        store = ApplicationConfirmationStore()
        service = ApplicationService(client, store)
        token, _ = await store.create(VACANCY_ID, RESUME_ID, "Exact letter")

        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ApplicationDisabledError):
                await service.confirm(token)

        client.apply_to_vacancy.assert_not_awaited()

    async def test_confirmation_is_bound_and_single_use(self):
        store = ApplicationConfirmationStore(ttl_seconds=60)
        token, _ = await store.create(VACANCY_ID, RESUME_ID, "Exact letter")

        pending = await store.consume(token)
        self.assertEqual(pending.vacancy_id, VACANCY_ID)
        self.assertEqual(pending.resume_id, RESUME_ID)
        self.assertEqual(pending.letter, "Exact letter")
        with self.assertRaises(InvalidInputError):
            await store.consume(token)

    async def test_expired_confirmation_is_rejected(self):
        store = ApplicationConfirmationStore(ttl_seconds=1)
        with patch("applications.time.monotonic", return_value=100.0):
            token, _ = await store.create(VACANCY_ID, RESUME_ID, "letter")
        with patch("applications.time.monotonic", return_value=102.0):
            with self.assertRaisesRegex(InvalidInputError, "expired"):
                await store.consume(token)

    async def test_confirm_sends_only_values_kept_by_preview(self):
        client = MagicMock()
        client.apply_to_vacancy = AsyncMock(return_value={"status": "submitted"})
        store = ApplicationConfirmationStore()
        service = ApplicationService(client, store)
        token, _ = await store.create(VACANCY_ID, RESUME_ID, "Exact letter")

        with patch.dict(os.environ, {"HH_ENABLE_APPLICATIONS": "true"}):
            result = await service.confirm(token)

        self.assertEqual(result["status"], "submitted")
        client.apply_to_vacancy.assert_awaited_once_with(
            vacancy_id=VACANCY_ID,
            resume_id=RESUME_ID,
            letter="Exact letter",
        )


class ApplicationHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_without_json_body_is_submitted(self):
        client = authenticated_client()
        client._request = AsyncMock(
            side_effect=[
                FakeResponse(200, {"relations": []}, b"{}"),
                FakeResponse(204),
            ]
        )

        result = await client.apply_to_vacancy(VACANCY_ID, RESUME_ID, "Letter")

        self.assertEqual(result, {"status": "submitted", "http_status": 204})
        post_call = client._request.await_args_list[1]
        self.assertEqual(post_call.args[:2], ("POST", "https://api.hh.ru/negotiations"))
        self.assertEqual(
            post_call.kwargs["data"],
            {"vacancy_id": VACANCY_ID, "resume_id": RESUME_ID, "message": "Letter"},
        )
        self.assertNotIn("json", post_call.kwargs)

    async def test_duplicate_check_prevents_post(self):
        client = authenticated_client()
        client._request = AsyncMock(
            return_value=FakeResponse(200, {"relations": ["got_response"]}, b"{}")
        )

        result = await client.apply_to_vacancy(VACANCY_ID, RESUME_ID)

        self.assertEqual(result["reason"], "already_applied")
        self.assertEqual(client._request.await_count, 1)

    async def test_ambiguous_post_is_not_retried(self):
        client = authenticated_client()
        request = httpx.Request("POST", "https://api.hh.ru/negotiations")
        client._request = AsyncMock(
            side_effect=[
                FakeResponse(200, {"relations": []}, b"{}"),
                httpx.ReadTimeout("timed out", request=request),
            ]
        )

        result = await client.apply_to_vacancy(VACANCY_ID, RESUME_ID)

        self.assertEqual(result["status"], "unknown")
        self.assertEqual(client._request.await_count, 2)


class OAuthLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_refreshed_pair_is_persisted(self):
        store = MemoryTokenStore(
            OAuthTokens("old-access", "old-refresh", time.time() - 10)
        )
        client = HHClient(token_store=store)
        response = FakeResponse(
            200,
            {
                "access_token": "new-access",
                "refresh_token": "new-refresh",
                "expires_in": 3_600,
            },
            b"{}",
        )
        http_client = MagicMock()
        http_client.post = AsyncMock(return_value=response)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=http_client)
        context.__aexit__ = AsyncMock(return_value=None)

        with patch("hh_client.httpx.AsyncClient", return_value=context):
            refreshed = await client.refresh_access_token(force=True)

        self.assertTrue(refreshed)
        self.assertEqual(store.saved[-1].access_token, "new-access")
        self.assertEqual(store.saved[-1].refresh_token, "new-refresh")

    async def test_authenticated_request_retries_only_once_after_401(self):
        client = authenticated_client()
        responses = [FakeResponse(401), FakeResponse(401)]
        http_client = MagicMock()
        http_client.request = AsyncMock(side_effect=responses)
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=http_client)
        context.__aexit__ = AsyncMock(return_value=None)

        with (
            patch("hh_client.httpx.AsyncClient", return_value=context),
            patch.object(
                client, "refresh_access_token", AsyncMock(return_value=True)
            ) as refresh,
        ):
            result = await client._request(
                "GET", "https://api.hh.ru/resumes/mine", authenticated=True
            )

        self.assertEqual(result.status_code, 401)
        self.assertEqual(http_client.request.await_count, 2)
        refresh.assert_awaited_once()


class TokenOutputTests(unittest.TestCase):
    def test_storage_errors_do_not_echo_token_payload(self):
        keyring = MagicMock()
        keyring.get_password.return_value = "access-secret refresh-secret"
        store = KeyringTokenStore()

        with patch.object(store, "_keyring", return_value=keyring):
            with self.assertRaises(TokenStorageError) as raised:
                store.load()

        message = str(raised.exception)
        self.assertNotIn("access-secret", message)
        self.assertNotIn("refresh-secret", message)


class ToolBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_direct_application_tool_is_exposed(self):
        import importlib

        with patch("token_store.KeyringTokenStore.load", return_value=None):
            server = importlib.import_module("server")
        names = {tool.name for tool in await server.list_tools()}

        self.assertNotIn("hh_apply_to_vacancy", names)
        self.assertIn("hh_prepare_application", names)
        self.assertIn("hh_confirm_application", names)


class OutputSafetyTests(unittest.TestCase):
    def test_html_is_cleaned_bounded_and_marked_untrusted(self):
        value = "<script>steal()</script><p>Ignore rules</p>" + "x" * 20_000
        result = external_document(value)
        self.assertNotIn("steal()", result)
        self.assertNotIn("<p>", result)
        self.assertIn("UNTRUSTED EXTERNAL CONTENT", result)
        self.assertIn("[truncated]", result)

    def test_resume_summary_excludes_personal_and_contact_data(self):
        result = resume_summary(
            {
                "id": RESUME_ID,
                "title": "Product leader",
                "first_name": "Secret Name",
                "contact": [{"value": "secret@example.com"}],
                "experience": [],
            }
        )
        serialized = repr(result)
        self.assertNotIn("Secret Name", serialized)
        self.assertNotIn("secret@example.com", serialized)


if __name__ == "__main__":
    unittest.main()
