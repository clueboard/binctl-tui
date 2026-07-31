"""Shared behavior for modal screens."""

from __future__ import annotations

from textual.binding import Binding
from textual.events import Key
from textual.screen import ModalScreen


class BaseModal(ModalScreen[object | None]):
    """Modal base class with global help and configuration shortcuts."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "interrupt", "Quit", show=False),
        Binding("f1", "help", "Help", show=False),
        Binding("f2", "configuration", "Configuration", show=False),
    ]

    def action_cancel(self) -> None:
        """Dismiss the modal without taking action."""
        self.dismiss(None)

    def action_interrupt(self) -> None:
        """Delegate shutdown to the application while a modal has focus."""
        self.app.action_interrupt()

    def action_help(self) -> None:
        """Display full-screen help above the current modal."""
        self.app.action_help()

    def action_configuration(self) -> None:
        """Discard this modal and open configuration."""
        self.dismiss(None)
        self.app.call_after_refresh(self.app.action_configuration)

    def on_key(self, event: Key) -> None:
        """Use vertical arrows to traverse form controls without tabbing."""
        if event.key == "up":
            self.focus_previous()
        elif event.key == "down":
            self.focus_next()
        else:
            return

        event.prevent_default()
        event.stop()
