"""Tests for Flickr API client — auth, rate limiting, and API calls."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from negclone.flickr import (
    FlickrAuthError,
    FlickrRateLimitError,
    RateLimiter,
    _get_api_credentials,
    _load_tokens,
    _save_tokens,
    flickr_call_with_retry,
)


class TestApiCredentials:
    """Tests for API credential loading from environment."""

    def test_reads_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FLICKR_API_KEY", "test_key")
        monkeypatch.setenv("FLICKR_API_SECRET", "test_secret")

        key, secret = _get_api_credentials()
        assert key == "test_key"
        assert secret == "test_secret"

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("FLICKR_API_KEY", raising=False)
        monkeypatch.delenv("FLICKR_API_SECRET", raising=False)

        with pytest.raises(FlickrAuthError, match="FLICKR_API_KEY"):
            _get_api_credentials()

    def test_raises_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("FLICKR_API_KEY", "")
        monkeypatch.setenv("FLICKR_API_SECRET", "")

        with pytest.raises(FlickrAuthError):
            _get_api_credentials()


class TestTokenStorage:
    """Tests for OAuth token save/load."""

    def test_save_and_load(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        token_dir = tmp_path / ".negclone"
        token_file = token_dir / "flickr_tokens.json"

        monkeypatch.setattr("negclone.flickr.TOKEN_DIR", token_dir)
        monkeypatch.setattr("negclone.flickr.TOKEN_FILE", token_file)

        _save_tokens("tok123", "sec456", "testuser")

        assert token_file.exists()
        # Check permissions (600)
        mode = token_file.stat().st_mode & 0o777
        assert mode == 0o600

        tokens = _load_tokens()
        assert tokens is not None
        assert tokens["token"] == "tok123"
        assert tokens["token_secret"] == "sec456"
        assert tokens["username"] == "testuser"

    def test_load_missing_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        token_file = tmp_path / "nonexistent" / "tokens.json"
        monkeypatch.setattr("negclone.flickr.TOKEN_FILE", token_file)

        assert _load_tokens() is None


class TestRateLimiter:
    """Tests for rate limiter."""

    def test_first_call_no_wait(self) -> None:
        limiter = RateLimiter()
        # First call should not wait (or wait minimally)
        import time

        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        # Should be nearly instant (less than 0.1s)
        assert elapsed < 0.1


class TestFlickrCallWithRetry:
    """Tests for API call retry logic."""

    def test_successful_call(self) -> None:
        mock_func = MagicMock(return_value={"stat": "ok"})
        rate_limiter = RateLimiter()

        result = flickr_call_with_retry(mock_func, rate_limiter, photo_id="123")

        assert result == {"stat": "ok"}
        mock_func.assert_called_once_with(photo_id="123")

    def test_retries_on_rate_limit(self) -> None:
        import flickrapi.exceptions

        mock_func = MagicMock(
            side_effect=[
                flickrapi.exceptions.FlickrError("429 Too Many Requests"),
                {"stat": "ok"},
            ]
        )
        rate_limiter = RateLimiter()

        with patch("negclone.flickr.INITIAL_BACKOFF", 0.01):
            result = flickr_call_with_retry(mock_func, rate_limiter)

        assert result == {"stat": "ok"}
        assert mock_func.call_count == 2

    def test_raises_after_max_retries(self) -> None:
        import flickrapi.exceptions

        mock_func = MagicMock(side_effect=flickrapi.exceptions.FlickrError("429 Too Many Requests"))
        rate_limiter = RateLimiter()

        with (
            patch("negclone.flickr.INITIAL_BACKOFF", 0.01),
            patch("negclone.flickr.MAX_RETRIES", 2),
            pytest.raises(FlickrRateLimitError),
        ):
            flickr_call_with_retry(mock_func, rate_limiter)

    def test_non_rate_limit_error_not_retried(self) -> None:
        import flickrapi.exceptions

        mock_func = MagicMock(side_effect=flickrapi.exceptions.FlickrError("1: Photo not found"))
        rate_limiter = RateLimiter()

        with pytest.raises(flickrapi.exceptions.FlickrError, match="Photo not found"):
            flickr_call_with_retry(mock_func, rate_limiter)

        mock_func.assert_called_once()
