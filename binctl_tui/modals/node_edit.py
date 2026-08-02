"""New and edit node form."""

from __future__ import annotations

from typing import TypedDict

from textual.app import ComposeResult
from textual.content import Content
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.widgets import Button, Checkbox, Input, Label, Select, TextArea

from ..cache import InventoryCache
from ..tags import normalize_tag_names
from .base import BaseModal


class StateCheckbox(Checkbox):
    """Render distinct checked and unchecked glyphs without relying on color."""

    @property
    def _button(self) -> Content:
        symbol = "[X]" if self.value else "[ ]"
        return Content.assemble((symbol, self.get_visual_style("toggle--button")))


class NodeDraft(TypedDict):
    label: str
    is_container: bool
    parent_id: str | None
    tag_names: list[str]
    description: str


class NodeEditModal(BaseModal):
    """Collect a create or update request while preserving drafts after errors."""

    NO_PARENT = "__no_parent__"

    def __init__(
        self,
        cache: InventoryCache,
        *,
        title: str,
        initial: NodeDraft,
        node_id: str | None = None,
    ) -> None:
        super().__init__()
        self.cache = cache
        self.title = title
        self.initial = initial
        self.node_id = node_id
        self.parent_id = initial["parent_id"]
        self.busy = False
        self.advance_after_parent_selection = False

    def compose(self) -> ComposeResult:
        parent_path = (
            self.cache.get_path_string(self.parent_id)
            if self.parent_id and self.parent_id in self.cache.nodes
            else "<No Parent>"
        )
        parent_options = [("<No Parent>", self.NO_PARENT)]
        parent_options.extend(
            (path, node_id)
            for path, node_id in self.cache.search("")
            if self.cache.get_node(node_id).is_container
        )
        parent_value = self.parent_id if self.parent_id in self.cache.nodes else self.NO_PARENT
        yield Vertical(
            Label(self.title, classes="modal-title"),
            Label("Name"),
            Input(self.initial["label"], id="name"),
            StateCheckbox("Is Container", value=self.initial["is_container"], id="is-container"),
            Label("Parent"),
            Select(
                parent_options,
                value=parent_value,
                allow_blank=False,
                id="parent",
                tooltip=parent_path,
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
        elif event.button.id == "submit":
            self._submit()

    def on_key(self, event: Key) -> None:
        if event.key == "shift+enter":
            if not self.busy:
                self._submit()
            event.prevent_default()
            event.stop()
            return

        if event.key == "enter":
            parent = self.query_one("#parent", Select)
            if parent.expanded:
                self.advance_after_parent_selection = True
                return
            self.focus_next()
            event.prevent_default()
            event.stop()
            return

        super().on_key(event)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "parent":
            self.parent_id = None if event.value == self.NO_PARENT else str(event.value)
            if self.advance_after_parent_selection:
                self.advance_after_parent_selection = False
                self.call_after_refresh(self.focus_next)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for widget_id in ("cancel", "submit"):
            self.query_one(f"#{widget_id}", Button).disabled = busy
        self.query_one("#parent", Select).disabled = busy

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
