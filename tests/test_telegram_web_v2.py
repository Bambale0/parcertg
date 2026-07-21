from app.telegram_web_v2 import (
    _matches_target,
    reset_telegram_web_browser_profile,
    telegram_web_chat_url,
)


def test_chat_url_uses_telegram_web_tgaddr_deep_link() -> None:
    url = telegram_web_chat_url(
        "https://web.telegram.org/k/",
        "@TelemetrioAlertBot",
    )

    assert url.startswith("https://web.telegram.org/k/#?tgaddr=")
    assert "TelemetrioAlertBot" in url
    assert "%3A%2F%2Fresolve%3Fdomain%3D" in url


def test_target_match_accepts_display_title_without_bot_suffix() -> None:
    assert _matches_target("Telemetrio Alerts", "TelemetrioAlertBot") is True


def test_profile_reset_preserves_seen_state_and_diagnostics(tmp_path) -> None:
    (tmp_path / "Default").mkdir()
    (tmp_path / "Default" / "Cookies").write_text("secret", encoding="utf-8")
    (tmp_path / "parcertg-seen.json").write_text("{}", encoding="utf-8")
    (tmp_path / "diagnostics").mkdir()
    (tmp_path / "diagnostics" / "state.json").write_text("{}", encoding="utf-8")

    reset_telegram_web_browser_profile(tmp_path)

    assert not (tmp_path / "Default").exists()
    assert (tmp_path / "parcertg-seen.json").exists()
    assert (tmp_path / "diagnostics" / "state.json").exists()
