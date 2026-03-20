"""Flickr API client and OAuth authentication."""

import json
import os
import time
import webbrowser
from pathlib import Path
from typing import Any

import flickrapi  # type: ignore[import-untyped]
from rich.console import Console

# Rate limiting constants
MIN_REQUEST_INTERVAL: float = 1.0  # seconds between requests
MAX_RETRIES: int = 5
INITIAL_BACKOFF: float = 2.0

TOKEN_DIR: Path = Path.home() / ".negclone"
TOKEN_FILE: Path = TOKEN_DIR / "flickr_tokens.json"

console = Console()


class FlickrAuthError(Exception):
    """Raised when Flickr authentication fails."""


class FlickrRateLimitError(Exception):
    """Raised when Flickr rate limit is hit after retries exhausted."""


def _get_api_credentials() -> tuple[str, str]:
    """Read Flickr API key and secret from environment variables.

    Returns:
        Tuple of (api_key, api_secret).

    Raises:
        FlickrAuthError: If environment variables are not set.
    """
    api_key = os.environ.get("FLICKR_API_KEY")
    api_secret = os.environ.get("FLICKR_API_SECRET")

    if not api_key or not api_secret:
        raise FlickrAuthError(
            "FLICKR_API_KEY and FLICKR_API_SECRET environment variables must be set. "
            "Get a key at https://www.flickr.com/services/apps/create/"
        )
    return api_key, api_secret


def _save_tokens(
    token: str,
    token_secret: str,
    username: str,
    user_nsid: str = "",
    fullname: str = "",
) -> None:
    """Save OAuth tokens securely to disk.

    Args:
        token: OAuth access token.
        token_secret: OAuth access token secret.
        username: Authenticated Flickr username.
        user_nsid: Flickr user NSID.
        fullname: User's full name.
    """
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    TOKEN_DIR.chmod(0o700)
    data = {
        "token": token,
        "token_secret": token_secret,
        "username": username,
        "user_nsid": user_nsid,
        "fullname": fullname,
    }
    # Write with restricted permissions from the start (no world-readable window)
    fd = os.open(TOKEN_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _load_tokens() -> dict[str, str] | None:
    """Load saved OAuth tokens from disk.

    Returns:
        Token dict with keys 'token', 'token_secret', 'username', or None.
    """
    if not TOKEN_FILE.exists():
        return None
    with open(TOKEN_FILE, encoding="utf-8") as f:
        data: dict[str, str] = json.load(f)
    return data


def authenticate(verifier_code: str | None = None) -> str:
    """Run the Flickr OAuth 1.0a 3-legged flow.

    Args:
        verifier_code: If provided, skip the interactive prompt and use this
            verifier directly. Useful for scripted/non-interactive auth.

    Returns:
        The authenticated Flickr username.

    Raises:
        FlickrAuthError: If authentication fails.
    """
    api_key, api_secret = _get_api_credentials()

    flickr = flickrapi.FlickrAPI(api_key, api_secret, format="parsed-json")

    console.print("[bold]Starting Flickr OAuth authentication...[/bold]")

    flickr.get_request_token(oauth_callback="oob")

    authorize_url: str = flickr.auth_url(perms="read")
    console.print(f"\nOpening authorization URL in your browser:\n[link]{authorize_url}[/link]")
    webbrowser.open(authorize_url)

    if verifier_code:
        verifier = verifier_code.strip()
    else:
        verifier = input("Enter the verifier code from Flickr: ").strip()

    if not verifier:
        raise FlickrAuthError("No verifier code provided.")

    try:
        flickr.get_access_token(verifier)
    except flickrapi.exceptions.FlickrError as e:
        raise FlickrAuthError(f"Failed to get access token: {e}") from e

    access_token = flickr.token_cache.token
    username: str = access_token.username

    _save_tokens(
        token=access_token.token,
        token_secret=access_token.token_secret,
        username=username,
        user_nsid=access_token.user_nsid,
        fullname=access_token.fullname,
    )

    return username


def get_authenticated_client() -> flickrapi.FlickrAPI:
    """Get an authenticated Flickr API client.

    Returns:
        Authenticated FlickrAPI instance.

    Raises:
        FlickrAuthError: If no saved tokens or credentials are missing.
    """
    api_key, api_secret = _get_api_credentials()
    tokens = _load_tokens()

    if tokens is None:
        raise FlickrAuthError("Not authenticated. Run 'negclone auth' first.")

    access_token = flickrapi.auth.FlickrAccessToken(
        tokens["token"],
        tokens["token_secret"],
        "read",
        fullname=tokens.get("fullname", ""),
        username=tokens.get("username", ""),
        user_nsid=tokens.get("user_nsid", ""),
    )

    flickr = flickrapi.FlickrAPI(
        api_key,
        api_secret,
        token=access_token,
        store_token=False,
        format="parsed-json",
    )

    return flickr


def get_authenticated_user_nsid() -> str | None:
    """Get the NSID of the authenticated user from saved tokens.

    Returns:
        User NSID string, or None if not available.
    """
    tokens = _load_tokens()
    if tokens is None:
        return None
    return tokens.get("user_nsid") or None


class RateLimiter:
    """Simple rate limiter for Flickr API calls."""

    def __init__(self) -> None:
        self._last_request: float = 0.0

    def wait(self) -> None:
        """Wait if needed to respect rate limit."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request = time.monotonic()


def flickr_call_with_retry(
    func: Any,
    rate_limiter: RateLimiter,
    **kwargs: Any,
) -> Any:
    """Call a Flickr API method with rate limiting and exponential backoff.

    Args:
        func: Flickr API method to call.
        rate_limiter: RateLimiter instance.
        **kwargs: Arguments to pass to the API method.

    Returns:
        The API response.

    Raises:
        FlickrRateLimitError: If retries are exhausted.
    """
    backoff = INITIAL_BACKOFF

    for attempt in range(MAX_RETRIES):
        rate_limiter.wait()
        try:
            result: Any = func(**kwargs)
            return result
        except flickrapi.exceptions.FlickrError as e:
            error_str = str(e)
            if "429" in error_str or "503" in error_str:
                if attempt < MAX_RETRIES - 1:
                    console.print(
                        f"[yellow]Rate limited, retrying in {backoff:.1f}s "
                        f"(attempt {attempt + 1}/{MAX_RETRIES})...[/yellow]"
                    )
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise FlickrRateLimitError(
                    f"Rate limit exceeded after {MAX_RETRIES} retries"
                ) from e
            raise

    raise FlickrRateLimitError(f"Failed after {MAX_RETRIES} retries")
