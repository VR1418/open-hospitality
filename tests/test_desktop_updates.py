"""Telling the owner about a newer version (PRD I-5, adapted).

No database and no network: the comparison and the refusals are the whole
surface, and both matter — an app that nags because of a typo in a published
file, or that breaks when the hotel's internet is down, is worse than one
that says nothing.
"""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from usali.desktop import updates


@pytest.mark.parametrize(
    ("latest", "current", "newer"),
    [
        ("0.2.0", "0.1.0", True),
        ("0.1.1", "0.1.0", True),
        ("1.0", "0.9.9", True),
        ("0.1.0", "0.1.0", False),
        ("0.1.0", "0.2.0", False),
        # A longer version is not automatically a newer one.
        ("0.1.0.0", "0.1.0", False),
        ("0.1.0", "0.1.0.0", False),
        # A leading v is read; anything after the numbers is ignored.
        ("v0.3.0", "0.2.9", True),
        # Nonsense never nags.
        ("soon", "0.1.0", False),
        ("0.2.0", "", False),
    ],
)
def test_which_version_is_newer(latest: str, current: str, newer: bool) -> None:
    assert updates.is_newer(latest, current) is newer


def test_with_nowhere_published_it_says_so_and_asks_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(updates.UPDATE_URL_ENV, raising=False)

    def refuse(*args: object, **kwargs: object) -> object:
        raise AssertionError("no request should be made")

    monkeypatch.setattr(httpx, "get", refuse)
    result = updates.check("0.1.0")
    assert result.configured is False
    assert result.update_available is False and result.latest is None


def _answer(monkeypatch: pytest.MonkeyPatch, body: str, status: int = 200) -> None:
    def fake_get(url: str, **kwargs: object) -> httpx.Response:
        return httpx.Response(status, text=body, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx, "get", fake_get)


def test_a_published_version_is_compared_with_this_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _answer(
        monkeypatch,
        '{"version": "0.2.0", "url": "https://example.test/dl", "notes": "Backups."}',
    )
    result = updates.check("0.1.0", url="https://example.test/latest.json")
    assert result.configured and result.latest == "0.2.0"
    assert result.url == "https://example.test/dl" and result.notes == "Backups."
    assert result.update_available is True and result.error is None


def test_the_same_version_is_not_an_update(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, '{"version": "0.1.0"}')
    result = updates.check("0.1.0", url="https://example.test/latest.json")
    assert result.latest == "0.1.0" and result.update_available is False


def test_a_hotel_with_no_internet_is_told_nothing_is_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(url: str, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", refuse)
    result = updates.check("0.1.0", url="https://example.test/latest.json")
    # Reported, never raised: the books do not depend on this.
    assert result.error is not None and "refused" in result.error
    assert result.update_available is False and result.latest is None


@pytest.mark.parametrize("body", ['{"notes": "no version here"}', "not json at all", "{}"])
def test_a_published_file_that_says_nothing_useful_is_refused(
    monkeypatch: pytest.MonkeyPatch, body: str,
) -> None:
    _answer(monkeypatch, body)
    with pytest.raises(updates.UpdateCheckFailed):
        updates.fetch("https://example.test/latest.json")


def test_an_http_error_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _answer(monkeypatch, "nope", status=404)
    with pytest.raises(updates.UpdateCheckFailed):
        updates.fetch("https://example.test/latest.json")


def test_it_asks_about_once_a_day() -> None:
    now = datetime(2026, 9, 11, 12, tzinfo=UTC)
    assert updates.due(None, now) is True
    assert updates.due(now - timedelta(hours=2), now) is False
    assert updates.due(now - timedelta(hours=21), now) is True
