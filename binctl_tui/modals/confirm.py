"""Confirmation modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Static

from .base import BaseModal


class ConfirmModal(BaseModal):
    """Ask the user to explicitly confirm a destructive operation."""

    def __init__(
        self,
        message: str,
        *,
        default_affirmative: bool = False,
    ) -> None:
        super().__init__()
        self.message = message
        self.default_affirmative = default_affirmative

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.message, classes="modal-message"),
            Horizontal(
                Button("Cancel", id="cancel", variant="default"),
                Button("Ok", id="ok", variant="error"),
                classes="modal-buttons",
            ),
            classes="modal-body",
        )

    def on_mount(self) -> None:
        button_id = "ok" if self.default_affirmative else "cancel"
        self.query_one(f"#{button_id}", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "ok")
