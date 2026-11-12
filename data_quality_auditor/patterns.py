import re

IDENTIFIER_TOKENS = frozenset({"id", "uuid", "guid"})
DATE_TOKENS = frozenset({"date", "time", "timestamp", "datetime", "ts"})
EMAIL_TOKEN = "email"
EPOCH_TOKENS = frozenset({"ts", "timestamp"})
DATE_SUFFIX_TOKEN = "at"

_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_SEPARATORS = re.compile(r"[\s_-]+")


def tokenize(name: str) -> tuple[str, ...]:
    text = name.strip()
    text = _ACRONYM_BOUNDARY.sub(r"\1_\2", text)
    text = _CAMEL_BOUNDARY.sub(r"\1_\2", text)
    parts = _SEPARATORS.split(text)
    return tuple(part.lower() for part in parts if part)


def is_identifier_name(name: str) -> bool:
    return any(part in IDENTIFIER_TOKENS for part in tokenize(name))


def is_email_name(name: str) -> bool:
    return EMAIL_TOKEN in tokenize(name)


def is_epoch_name(name: str) -> bool:
    return any(part in EPOCH_TOKENS for part in tokenize(name))


def is_date_name(name: str) -> bool:
    parts = tokenize(name)
    if any(part in DATE_TOKENS for part in parts):
        return True
    return len(parts) > 1 and parts[-1] == DATE_SUFFIX_TOKEN
