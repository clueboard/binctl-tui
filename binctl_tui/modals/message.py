"""Informational modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from .base import BaseModal


class MessageModal(BaseModal):
    """Show an error or status message."""

    def __init__(self, message: str) -> None:
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.message, classes="modal-message"),
            Horizontal(Button("Ok", id="ok", variant="primary"), classes="modal-buttons"),
            classes="modal-body",
        )

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)
