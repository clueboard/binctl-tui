"""Server configuration modal."""

from __future__ import annotations

from typing import TypedDict

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.widgets import Button, Input, Label, OptionList, RadioButton, RadioSet, Select

from .base import BaseModal


class ConfigValues(TypedDict):
    url: str
    token: str
    username: str
    password: str
    theme: str


class ConfigModal(BaseModal):
    """Edit persisted connection settings."""

    def __init__(self, config: dict[str, str]) -> None:
        super().__init__()
        self.config = config
        self.auth_method = (
            "token"
            if config.get("token") or not (config.get("username") or config.get("password"))
            else "password"
        )
        self.auth_cursor_index = 0
        self.original_theme: str | None = None
        self.themes: list[str] = []

    def compose(self) -> ComposeResult:
        themes = sorted(self.app.available_themes)
        self.themes = themes
        configured_theme = self.config.get("theme", "textual-light")
        selected_theme = configured_theme if configured_theme in themes else "textual-light"
        yield Vertical(
            Label("Configuration", classes="modal-title"),
            Label("binctl URL"),
            Input(self.config.get("url", ""), id="url"),
            Label("Authentication"),
            RadioSet(
                RadioButton(
                    "Token",
                    value=self.auth_method == "token",
                    id="token-method",
                ),
                RadioButton(
                    "Username/Password",
                    value=self.auth_method == "password",
                    id="password-method",
                ),
                id="auth-method",
            ),
            Vertical(
                Label("Token"),
                Input(self.config.get("token", ""), id="token", password=True),
                id="token-fields",
            ),
            Vertical(
                Label("Username"),
                Input(self.config.get("username", ""), id="username"),
                Label("Password"),
                Input(self.config.get("password", ""), id="password", password=True),
                id="password-fields",
            ),
            Label("Theme"),
            Select(
                [(theme, theme) for theme in themes],
                value=selected_theme,
                allow_blank=False,
                id="theme",
            ),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Save", id="save", variant="primary"),
                classes="modal-buttons",
            ),
            classes="settings modal-body",
        )

    def on_mount(self) -> None:
        self.original_theme = self.app.theme
        self._set_auth_method(self.auth_method)
        theme_options = self.query_one("#theme", Select).query_one(OptionList)
        self.watch(theme_options, "highlighted", self._preview_theme, init=False)
        self.query_one("#url", Input).focus()

    def action_cancel(self) -> None:
        self._restore_original_theme()
        self.dismiss(None)

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "auth-method":
            return

        self.auth_cursor_index = event.index
        self._set_auth_method(
            "token" if event.pressed.id == "token-method" else "password",
        )

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self._restore_original_theme()

        selector = self.query_one("#auth-method", RadioSet)
        focused = self.focused

        if focused is selector:
            if event.key == "down" and self.auth_cursor_index == 0:
                selector.action_next_button()
                self.auth_cursor_index = 1
                event.prevent_default()
                event.stop()
                return
            if event.key == "down" and self.auth_cursor_index == 1:
                self._focus_credentials()
                event.prevent_default()
                event.stop()
                return
            if event.key == "up" and self.auth_cursor_index == 1:
                selector.action_previous_button()
                self.auth_cursor_index = 0
                event.prevent_default()
                event.stop()
                return
            if event.key == "up" and self.auth_cursor_index == 0:
                self.query_one("#url", Input).focus()
                event.prevent_default()
                event.stop()
                return
        elif event.key == "down" and focused is self.query_one("#url", Input):
            if self.auth_cursor_index == 1:
                selector.action_previous_button()
                self.auth_cursor_index = 0
            selector.focus()
            event.prevent_default()
            event.stop()
            return
        elif event.key == "up" and focused is self._credential_input():
            if self.auth_cursor_index == 0:
                selector.action_next_button()
                self.auth_cursor_index = 1
            selector.focus()
            event.prevent_default()
            event.stop()
            return

        super().on_key(event)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.action_cancel()
            return

        values: ConfigValues = {
            "url": self.query_one("#url", Input).value.strip(),
            "token": "",
            "username": "",
            "password": "",
            "theme": str(self.query_one("#theme", Select).value),
        }

        if self.auth_method == "token":
            values["token"] = self.query_one("#token", Input).value.strip()
        else:
            values["username"] = self.query_one("#username", Input).value.strip()
            values["password"] = self.query_one("#password", Input).value

        self.dismiss(values)

    def _set_auth_method(self, method: str) -> None:
        self.auth_method = method
        self.query_one("#token-fields").display = method == "token"
        self.query_one("#password-fields").display = method == "password"

    def _credential_input(self) -> Input:
        input_id = "token" if self.auth_method == "token" else "username"
        field = self.query_one(f"#{input_id}", Input)

        return field

    def _focus_credentials(self) -> None:
        self._credential_input().focus()

    def _preview_theme(self, highlighted: int | None) -> None:
        if highlighted is not None and 0 <= highlighted < len(self.themes):
            self.app.theme = self.themes[highlighted]

    def _restore_original_theme(self) -> None:
        if self.original_theme in self.app.available_themes:
            self.app.theme = self.original_theme
