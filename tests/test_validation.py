"""Tests for rejecting unsafe values before any HTTP request is attempted."""

import sys
import types
import unittest
from unittest.mock import patch

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    httpx_stub = types.ModuleType("httpx")
    httpx_stub.AsyncClient = None
    sys.modules["httpx"] = httpx_stub

from hh_client import HHClient
from validation import (
    InvalidInputError,
    validate_decimal_id,
    validate_pagination,
    validate_resume_id,
)


class EmptyTokenStore:
    def load(self):
        return None

    def save(self, tokens):
        self.tokens = tokens


class IdentifierValidationTests(unittest.TestCase):
    def test_valid_identifiers_are_returned_unchanged(self):
        self.assertEqual(validate_decimal_id("126209046", "vacancy_id"), "126209046")
        resume_id = "7b7f2ea6ff0838f1ea0039ed1f704b31506463"
        self.assertEqual(validate_resume_id(resume_id), resume_id)

    def test_unsafe_decimal_identifiers_are_rejected(self):
        invalid_values = (
            "",
            "0",
            "01",
            " 123",
            "123 ",
            "123/456",
            r"123\456",
            "..",
            "%2f",
            "１２３",
            "123\n456",
            123,
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(InvalidInputError):
                    validate_decimal_id(value, "vacancy_id")

    def test_unsafe_resume_identifiers_are_rejected(self):
        invalid_values = (
            "short",
            "ABCDEF1234567890",
            "01234567/abcdef",
            "01234567..abcdef",
            "01234567 abcdef",
            "01234567\x00abcdef",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(InvalidInputError):
                    validate_resume_id(value)


class ParameterValidationTests(unittest.TestCase):
    def test_pagination_rejects_bool_and_out_of_range_values(self):
        invalid_values = (
            (True, 0),
            (20, False),
            (0, 0),
            (101, 0),
            (20, -1),
            (20, 2_000),
        )
        for per_page, page in invalid_values:
            with self.subTest(per_page=per_page, page=page):
                with self.assertRaises(InvalidInputError):
                    validate_pagination(per_page, page)

    def test_vacancy_search_depth_is_limited(self):
        self.assertEqual(
            validate_pagination(10, 199, enforce_search_depth=True),
            (10, 199),
        )
        with self.assertRaises(InvalidInputError):
            validate_pagination(10, 200, enforce_search_depth=True)


class RejectBeforeHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_invalid_path_identifier_does_not_create_http_client(self):
        client = HHClient(token_store=EmptyTokenStore())
        with patch("hh_client.httpx.AsyncClient") as async_client:
            with self.assertRaises(InvalidInputError):
                await client.get_vacancy("../negotiations")
        async_client.assert_not_called()

    async def test_invalid_search_parameters_do_not_create_http_client(self):
        client = HHClient(token_store=EmptyTokenStore())
        with patch("hh_client.httpx.AsyncClient") as async_client:
            with self.assertRaises(InvalidInputError):
                await client.search_vacancies(per_page=100, page=20)
        async_client.assert_not_called()

    async def test_invalid_resume_id_precedes_authentication_and_http(self):
        client = HHClient(token_store=EmptyTokenStore())
        client.access_token = None
        with patch("hh_client.httpx.AsyncClient") as async_client:
            with self.assertRaises(InvalidInputError):
                await client.get_resume("../../token")
        async_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
