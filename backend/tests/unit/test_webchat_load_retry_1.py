"""LOAD-RETRY-1 / POLL-401-1: static guards on the frontend sources (no browser needed)."""
import pathlib

SRC = pathlib.Path(__file__).resolve().parents[3] / "frontend" / "src"


def _t(rel):
    return (SRC / rel).read_text(encoding="utf-8")


def test_catalog_get_uses_timeout_and_retry():
    s = _t("catalog/catalog.service.js")
    assert "return withRetry(async () => {" in s
    assert "await fetchWithTimeout(`${BASE}${path}`)" in s


def test_shell_shows_slow_message_with_retry_button():
    s = _t("catalog/PublicCatalogShell.jsx")
    assert "setTimeout(() => setSlow(true), SLOW_AFTER_MS)" in s
    assert "Taking longer than usual." in s
    assert "Tap to retry" in s
    assert "return () => clearTimeout(slowTimer)" in s


def test_poll_skips_public_pages_and_bad_token():
    s = _t("main.jsx")
    assert "if (_PUBLIC_PATH.test(window.location.pathname)) return" in s
    assert "if (token === _badToken) return" in s
    assert "if (res.status === 401) { _badToken = token;" in s
    assert "catalog|shop" in s
