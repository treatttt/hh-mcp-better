"""Strict validation for values accepted by the HeadHunter client."""

from __future__ import annotations

import re
from collections.abc import Collection
from typing import Any


class InvalidInputError(ValueError):
    """Raised when a value must not be sent to the HeadHunter API."""


DECIMAL_ID_PATTERN = r"[1-9][0-9]{0,19}"
RESUME_ID_PATTERN = r"[0-9a-f]{8,50}"

DECIMAL_ID_SCHEMA_PATTERN = rf"^{DECIMAL_ID_PATTERN}$"
RESUME_ID_SCHEMA_PATTERN = rf"^{RESUME_ID_PATTERN}$"

MAX_PAGE = 1_999
MAX_PER_PAGE = 100
MAX_SEARCH_DEPTH = 2_000
MAX_SEARCH_TEXT_LENGTH = 3_000
MAX_COVER_LETTER_LENGTH = 10_000
MAX_SKIP_REASON_LENGTH = 500
MAX_AREA_ID = 2_147_483_647
MAX_SALARY = 1_000_000_000

EXPERIENCE_VALUES = frozenset(
    {"noExperience", "between1And3", "between3And6", "moreThan6"}
)
EMPLOYMENT_VALUES = frozenset({"full", "part", "project", "volunteer", "probation"})
SCHEDULE_VALUES = frozenset({"fullDay", "shift", "flexible", "remote", "flyInFlyOut"})

_DECIMAL_ID_RE = re.compile(DECIMAL_ID_PATTERN, re.ASCII)
_RESUME_ID_RE = re.compile(RESUME_ID_PATTERN, re.ASCII)


def _type_name(value: Any) -> str:
    return type(value).__name__


def _validate_int(
    value: Any,
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidInputError(f"{name} must be an integer, got {_type_name(value)}")
    if not minimum <= value <= maximum:
        raise InvalidInputError(
            f"{name} must be between {minimum} and {maximum}, got {value}"
        )
    return value


def _validate_text(
    value: Any,
    name: str,
    *,
    minimum_length: int,
    maximum_length: int,
) -> str:
    if not isinstance(value, str):
        raise InvalidInputError(f"{name} must be a string, got {_type_name(value)}")
    if not minimum_length <= len(value) <= maximum_length:
        raise InvalidInputError(
            f"{name} length must be between {minimum_length} and "
            f"{maximum_length} characters"
        )

    for character in value:
        codepoint = ord(character)
        if (
            codepoint == 0
            or (codepoint < 32 and character not in "\t\n\r")
            or codepoint == 127
        ):
            raise InvalidInputError(f"{name} contains control characters")
    return value


def validate_decimal_id(value: Any, name: str) -> str:
    """Validate a positive decimal identifier used in an API path."""
    if not isinstance(value, str):
        raise InvalidInputError(f"{name} must be a string, got {_type_name(value)}")
    if _DECIMAL_ID_RE.fullmatch(value) is None:
        raise InvalidInputError(
            f"{name} must contain only 1 to 20 ASCII digits and must not start "
            "with zero"
        )
    return value


def validate_resume_id(value: Any) -> str:
    """Validate a HeadHunter resume hash used in an API path or request."""
    if not isinstance(value, str):
        raise InvalidInputError(f"resume_id must be a string, got {_type_name(value)}")
    if _RESUME_ID_RE.fullmatch(value) is None:
        raise InvalidInputError(
            "resume_id must contain 8 to 50 lowercase ASCII hexadecimal characters"
        )
    return value


def validate_pagination(
    per_page: Any,
    page: Any,
    *,
    enforce_search_depth: bool = False,
) -> tuple[int, int]:
    """Validate pagination and, for vacancy search, its API depth limit."""
    valid_per_page = _validate_int(
        per_page, "per_page", minimum=1, maximum=MAX_PER_PAGE
    )
    valid_page = _validate_int(page, "page", minimum=0, maximum=MAX_PAGE)
    if enforce_search_depth and (valid_page + 1) * valid_per_page > MAX_SEARCH_DEPTH:
        raise InvalidInputError(
            f"page and per_page exceed the maximum search depth of "
            f"{MAX_SEARCH_DEPTH} results"
        )
    return valid_per_page, valid_page


def validate_area(value: Any) -> int | None:
    if value is None:
        return None
    return _validate_int(value, "area", minimum=1, maximum=MAX_AREA_ID)


def validate_salary(value: Any) -> int | None:
    if value is None:
        return None
    return _validate_int(value, "salary", minimum=0, maximum=MAX_SALARY)


def validate_search_text(value: Any) -> str | None:
    if value is None:
        return None
    return _validate_text(
        value,
        "text",
        minimum_length=1,
        maximum_length=MAX_SEARCH_TEXT_LENGTH,
    )


def validate_cover_letter(value: Any) -> str | None:
    if value is None:
        return None
    return _validate_text(
        value,
        "letter",
        minimum_length=0,
        maximum_length=MAX_COVER_LETTER_LENGTH,
    )


def validate_skip_reason(value: Any) -> str | None:
    """Validate an agent-supplied reason for excluding a batch candidate."""
    if value is None:
        return None
    return _validate_text(
        value,
        "skip_reason",
        minimum_length=1,
        maximum_length=MAX_SKIP_REASON_LENGTH,
    )


def validate_choice(
    value: Any,
    name: str,
    allowed_values: Collection[str],
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed_values:
        allowed = ", ".join(sorted(allowed_values))
        raise InvalidInputError(f"{name} must be one of: {allowed}")
    return value


def validate_boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise InvalidInputError(f"{name} must be a boolean, got {_type_name(value)}")
    return value
