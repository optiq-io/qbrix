"""validation for the names and slugs users choose for themselves.

names are echoed into outbound email, so a link in one turns an invite into an
ad sent from our own domain.
"""

from __future__ import annotations

import re
import unicodedata

from proxysvc.core.error import InvalidIdentityError

MAX_NAME_LENGTH = 64
MAX_SLUG_LENGTH = 64

_LINK = re.compile(r"://|\bwww\.|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}/", re.IGNORECASE)
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_NON_SLUG = re.compile(r"[^a-z0-9]+")


def clean_name(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > MAX_NAME_LENGTH:
        raise InvalidIdentityError(
            f"{field} must be at most {MAX_NAME_LENGTH} characters"
        )
    if any(unicodedata.category(char) == "Cc" for char in value):
        raise InvalidIdentityError(f"{field} must not contain control characters")
    # nfkc folds fullwidth and other lookalike forms back to ascii
    if _LINK.search(unicodedata.normalize("NFKC", value)):
        raise InvalidIdentityError(f"{field} must not contain a link")
    return value


def clean_slug(value: str) -> str:
    slug = value.strip().lower().strip("-")
    if len(slug) > MAX_SLUG_LENGTH or not _SLUG.fullmatch(slug):
        raise InvalidIdentityError(
            "workspace slug must be lowercase letters, digits and single hyphens, "
            f"at most {MAX_SLUG_LENGTH} characters"
        )
    return slug


def slug_from(text: str) -> str:
    """derive a valid slug from free text, such as an email's local part."""
    slug = _NON_SLUG.sub("-", text.lower()).strip("-")
    return slug[:MAX_SLUG_LENGTH].rstrip("-") or "workspace"
