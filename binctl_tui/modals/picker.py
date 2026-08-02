"""Search and move target picker."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.events import Key
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..cache import InventoryCache
from .base import BaseModal


class PickerModal(BaseModal):
    """Filter cache paths and return the selected node ID, or ``None`` for root."""

    NO_PARENT = object()

    def __init__(
        self,
        title: str,
        cache: InventoryCache,
        *,
        containers_only: bool = False,
        include_no_parent: bool = False,
    ) -> None:
        super().__init__()
        self.title = title
        self.cache = cache
        self.containers_only = containers_only
        self.include_no_parent = include_no_parent
        self.results: list[tuple[str, str | None]] = []

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(self.title, classes="modal-title"),
            Input(placeholder="Type to filter", id="query"),
            OptionList(id="results", markup=False),
            classes="picker modal-body",
        )

    def on_mount(self) -> None:
        self._update_results("")
        self.query_one("#query", Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "query":
            self._update_results(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Choose the highlighted result while focus remains in the filter."""
        if event.input.id == "query":
            self.query_one("#results", OptionList).action_select()
            event.stop()

    def on_key(self, event: Key) -> None:
        if event.key in {"up", "down"}:
            results = self.query_one("#results", OptionList)
            if event.key == "up":
                results.action_cursor_up()
            else:
                results.action_cursor_down()
            event.prevent_default()
            event.stop()
            return

        super().on_key(event)

    def on_option_list_option_selected(
        self,
        event: OptionList.OptionSelected,
    ) -> None:
        value = event.option_id
        self.dismiss(self.NO_PARENT if value == "__no_parent__" else value)

    def _update_results(self, query: str) -> None:
        option_list = self.query_one("#results", OptionList)
        entries = self.cache.search(query)
        self.results = [
            (path, node_id)
            for path, node_id in entries
            if not self.containers_only or self.cache.get_node(node_id).is_container
        ]
        options: list[Option] = []

        if self.include_no_parent:
            options.append(Option("<No Parent>", id="__no_parent__"))
        for path, node_id in self.results:
            options.append(Option(self._formatted_path(path, query), id=node_id))

        option_list.set_options(options)

    def _formatted_path(self, path: str, query: str) -> Text:
        text = Text()
        query_start = path.casefold().find(query.casefold()) if query else -1

        if query_start < 0:
            text.append(path, style="dim")
            return text

        query_end = query_start + len(query)
        text.append(path[:query_start], style="dim")
        text.append(path[query_start:query_end], style="bold")
        text.append(path[query_end:], style="dim")

        return text
