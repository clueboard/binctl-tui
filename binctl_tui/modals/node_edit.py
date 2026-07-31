"""New and edit node form."""

from __future__ import annotations

from typing import TypedDict

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Checkbox, Input, Label, TextArea

from ..cache import InventoryCache
from ..tags import normalize_tag_names
from .base import BaseModal
from .picker import PickerModal


class NodeDraft(TypedDict):
    label: str
    is_container: bool
    parent_id: str | None
    tag_names: list[str]
    description: str


class NodeEditModal(BaseModal):
    """Collect a create or update request while preserving drafts after errors."""

    def __init__(
        self,
        cache: InventoryCache,
        *,
        title: str,
        initial: NodeDraft,
    ) -> None:
        super().__init__()
        self.cache = cache
        self.title = title
        self.initial = initial
        self.parent_id = initial["parent_id"]
        self.busy = False

    def compose(self) -> ComposeResult:
        parent_path = (
            self.cache.get_path_string(self.parent_id)
            if self.parent_id and self.parent_id in self.cache.nodes
            else "<No Parent>"
        )
        yield Vertical(
            Label(self.title, classes="modal-title"),
            Label("Name"),
            Input(self.initial["label"], id="name"),
            Checkbox("Is Container", value=self.initial["is_container"], id="is-container"),
            Label("Parent"),
            Horizontal(
                Input(parent_path, id="parent", disabled=True),
                Button("Choose", id="choose-parent"),
            ),
            Label("Tags (comma-separated)"),
            Input(", ".join(self.initial["tag_names"]), id="tags"),
            Label("Description"),
            TextArea(self.initial["description"], id="description"),
            Horizontal(
                Button("Cancel", id="cancel"),
                Button("Submit", id="submit", variant="primary"),
                classes="modal-buttons",
            ),
            classes="node-edit modal-body",
        )

    def on_mount(self) -> None:
        self.query_one("#name", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if self.busy:
            return
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "choose-parent":
            self.app.push_screen(
                PickerModal(
                    "Parent",
                    self.cache,
                    containers_only=True,
                    include_no_parent=True,
                ),
                self._parent_picked,
            )
        elif event.button.id == "submit":
            self._submit()

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget_id in ("cancel", "submit", "choose-parent"):
            self.query_one(f"#{widget_id}", Button).disabled = busy

    def _parent_picked(self, parent_id: object | None) -> None:
        if parent_id is PickerModal.NO_PARENT:
            self.parent_id = None
            self.query_one("#parent", Input).value = "<No Parent>"
            return
        if parent_id is not None and not isinstance(parent_id, str):
            return
        self.parent_id = parent_id
        path = (
            self.cache.get_path_string(parent_id)
            if parent_id and parent_id in self.cache.nodes
            else "<No Parent>"
        )
        self.query_one("#parent", Input).value = path

    def _submit(self) -> None:
        name = self.query_one("#name", Input).value.strip()
        tags = self.query_one("#tags", Input).value
        description = self.query_one("#description", TextArea).text

        if not name:
            self.app.show_message("A node name is required.")
            return
        try:
            tag_names = normalize_tag_names(tags)
        except ValueError as error:
            self.app.show_message(str(error))
            return

        draft: NodeDraft = {
            "label": name,
            "is_container": self.query_one("#is-container", Checkbox).value,
            "parent_id": self.parent_id,
            "tag_names": tag_names,
            "description": description,
        }
        self.app.submit_node_draft(self, draft)
