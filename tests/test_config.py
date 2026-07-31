import os
import stat

from binctl_tui import config


def test_saves_atomically_loads_and_secures_credentials(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(config, "user_config_dir", lambda _: str(tmp_path / "settings"))

    saved = config.save_config(
        {
            "url": "https://inventory.example",
            "token": "secret",
            "username": "ignored",
            "password": "ignored",
        },
    )
    loaded = config.load_config()
    path = config.config_path()

    assert loaded == saved
    assert config.CONFIG == saved
    assert "[profiles.default]" in path.read_text()
    if os.name == "posix":
        assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_preserves_other_profiles_when_saving_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config, "user_config_dir", lambda _: str(tmp_path / "settings"))
    path = config.config_path()
    path.parent.mkdir()
    path.write_text("[profiles.other]\nurl = 'https://other.example'\n")

    config.load_config()
    config.save_config({"url": "https://default.example"})

    contents = path.read_text()
    assert "[profiles.default]" in contents
    assert "[profiles.other]" in contents
