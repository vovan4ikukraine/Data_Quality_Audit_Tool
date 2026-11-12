import pytest

from data_quality_auditor.patterns import (
    is_date_name,
    is_email_name,
    is_epoch_name,
    is_identifier_name,
    tokenize,
)


@pytest.mark.parametrize(
    ("name", "tokens"),
    [
        ("userId", ("user", "id")),
        ("Order ID", ("order", "id")),
        ("Order-ID", ("order", "id")),
        ("rule_id", ("rule", "id")),
        ("createdAt", ("created", "at")),
    ],
)
def test_tokenize_splits_a_column_name(name, tokens):
    assert tokenize(name) == tokens


@pytest.mark.parametrize("name", ["userId", "Order ID", "Order-ID", "rule_id"])
def test_identifier_names(name):
    assert is_identifier_name(name) is True


@pytest.mark.parametrize("name", ["status", "category", "paid", "userid"])
def test_ordinary_words_are_not_identifiers(name):
    assert is_identifier_name(name) is False


@pytest.mark.parametrize(
    "name",
    ["createdAt", "updated_at", "order_date", "event_time", "ts", "timestamp", "datetime"],
)
def test_date_names(name):
    assert is_date_name(name) is True


@pytest.mark.parametrize("name", ["at", "At", "status", "paid"])
def test_words_that_are_not_dates(name):
    assert is_date_name(name) is False


@pytest.mark.parametrize("name", ["ts", "timestamp", "event_ts", "created_timestamp"])
def test_epoch_names(name):
    assert is_epoch_name(name) is True
    assert is_date_name(name) is True


@pytest.mark.parametrize("name", ["time", "datetime", "createdAt"])
def test_dates_that_are_not_epochs(name):
    assert is_date_name(name) is True
    assert is_epoch_name(name) is False


@pytest.mark.parametrize("name", ["email", "Email Address", "user_email"])
def test_email_names(name):
    assert is_email_name(name) is True


@pytest.mark.parametrize("name", ["emails", "mail", "status"])
def test_words_that_are_not_emails(name):
    assert is_email_name(name) is False
