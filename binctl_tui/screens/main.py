"""Main inventory tree and lazy node-detail presentation."""

from __future__ import annotations

from datetime import datetime

from binctl_client.models.node import Node
from binctl_client.types import Unset
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.timer import Timer
from textual.widgets import Footer, LoadingIndicator, Markdown, Static, Tree

from ..cache import InventoryCache


class NodeDetailWidget(Horizontal):
    """A lazily populated, node-specific metadata and description view."""

    def __init__(self, node_id: str) -> None:
        super().__init__(id=f"detail-{node_id}", classes="node-detail")
        self.node_id = node_id
        self.last_access = datetime.now().timestamp()

    def compose(self) -> ComposeResult:
        yield Static("", id=f"metadata-{self.node_id}", classes="metadata")
        yield Vertical(
            Static("Description", classes="detail-section-title"),
            Markdown("", id=f"description-{self.node_id}", classes="description-content"),
            classes="description",
        )

    def update_node(self, node: Node) -> None:
        tags = [] if isinstance(node.tags, Unset) else [tag.name for tag in node.tags]
        metadata = "\n".join(
            (
                f"Label: {node.label}",
                f"Created: {node.created_at:%Y-%m-%d %H:%M}",
                f"Modified: {node.updated_at:%Y-%m-%d %H:%M}",
                "Tags: " + (", ".join(tags) if tags else "-"),
            )
        )
        description = "" if isinstance(node.description, Unset) else node.description or ""
        self.query_one(f"#metadata-{self.node_id}", Static).update(metadata)
        self.query_one(f"#description-{self.node_id}", Markdown).update(
            description.replace("\n", "  \n"),
        )


class MainScreen(Vertical):
    """The persistent sidebar and detail-widget host."""

    def __init__(self) -> None:
        super().__init__(id="main-screen")
        self.cache = InventoryCache()
        self.tree_nodes: dict[str, object] = {}
        self.details: dict[str, NodeDetailWidget] = {}
        self.selected_id: str | None = None
        self.detail_timer: Timer | None = None

    def compose(self) -> ComposeResult:
        inventory = Tree("", id="inventory", data=None)
        yield Horizontal(
            Vertical(
                LoadingIndicator(id="loading"),
                inventory,
                id="sidebar",
            ),
            Vertical(
                Static("", id="detail-title", classes="pane-header"),
                Vertical(id="detail-host"),
                id="detail-pane",
            ),
            id="workspace",
        )
        yield Footer()

    def on_mount(self) -> None:
        inventory = self.query_one("#inventory", Tree)
        inventory.show_root = False
        inventory.show_guides = False
        inventory.auto_expand = False
        inventory.unselect()

    def set_cache(
        self,
        cache: InventoryCache,
        expansion: dict[str, bool],
        selected_id: str | None = None,
    ) -> None:
        self.cache = cache
        self.tree_nodes = {}
        for detail in self.details.values():
            detail.remove()
        self.details = {}
        self._build_tree(expansion)
        if selected_id not in self.tree_nodes:
            selected_id = min(self.cache.roots, key=self._tree_sort_key) if self.cache.roots else None
        self.call_after_refresh(self.select_node, selected_id)

    def set_loading(self, is_loading: bool) -> None:
        self.query_one("#loading", LoadingIndicator).display = is_loading

    def select_node(self, node_id: str | None) -> None:
        tree = self.query_one("#inventory", Tree)
        tree_node = self.tree_nodes.get(node_id) if node_id else None

        if tree_node is None:
            tree.unselect()
            self._schedule_detail(None)
            return

        tree.select_node(tree_node)  # type: ignore[arg-type]

    def toggle_sidebar(self) -> None:
        self.query_one("#sidebar").toggle_class("hidden")

    def toggle_selected_container(self) -> None:
        node_id = self.selected_id
        tree_node = self.tree_nodes.get(node_id) if node_id else None

        if node_id and tree_node and self.cache.get_node(node_id).is_container:
            if tree_node.is_expanded:  # type: ignore[union-attr]
                tree_node.collapse()  # type: ignore[union-attr]
            else:
                tree_node.expand()  # type: ignore[union-attr]

    def on_key(self, event: Key) -> None:
        if event.key not in {"left", "right", "shift+left", "shift+right"}:
            return

        tree = self.query_one("#inventory", Tree)
        if tree.has_focus and event.key in {"shift+left", "shift+right"}:
            if event.key == "shift+left":
                tree.action_scroll_left()
            else:
                tree.action_scroll_right()
            event.prevent_default()
            event.stop()
            return

        tree_node = tree.cursor_node
        node_id = tree_node.data if tree_node is not None else None
        if not tree.has_focus or not isinstance(node_id, str):
            return
        if not self.cache.get_node(node_id).is_container:
            return

        if event.key == "left":
            tree_node.collapse()
        else:
            tree_node.expand()
        event.prevent_default()
        event.stop()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        node_id = event.node.data
        self._schedule_detail(node_id if isinstance(node_id, str) else None)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        node_id = event.node.data
        self._schedule_detail(node_id if isinstance(node_id, str) else None)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        node_id = event.node.data
        if isinstance(node_id, str):
            self.app.expansion[node_id] = True

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        node_id = event.node.data
        if isinstance(node_id, str):
            self.app.expansion[node_id] = False

    def _build_tree(self, expansion: dict[str, bool]) -> None:
        tree = self.query_one("#inventory", Tree)
        tree.clear()
        tree.root.expand()

        for root_id in sorted(self.cache.roots, key=self._tree_sort_key):
            self._add_tree_node(tree.root, root_id, expansion)

    def _add_tree_node(self, parent: object, node_id: str, expansion: dict[str, bool]) -> None:
        node = self.cache.get_node(node_id)
        children = self.cache.get_children(node_id)
        tree_node = parent.add(
            node.label,
            data=node_id,
            allow_expand=node.is_container,
            expand=expansion.get(node_id, False),
        )
        self.tree_nodes[node_id] = tree_node

        for child in sorted(children, key=lambda child: self._tree_sort_key(child.id)):
            self._add_tree_node(tree_node, child.id, expansion)

    def _tree_sort_key(self, node_id: str) -> tuple[str, str]:
        node = self.cache.get_node(node_id)
        return node.label.casefold(), node.id

    def _schedule_detail(self, node_id: str | None) -> None:
        if self.detail_timer is not None:
            self.detail_timer.stop()
            self.detail_timer = None
        if self.selected_id in self.details:
            self.details[self.selected_id].display = False
        self.selected_id = node_id

        if node_id is None:
            self.query_one("#detail-title", Static).update("")
            return

        self.detail_timer = self.set_timer(0.25, lambda: self._show_detail(node_id))

    def _show_detail(self, node_id: str) -> None:
        if self.selected_id != node_id:
            return
        detail = self.details.get(node_id)

        if detail is None:
            detail = NodeDetailWidget(node_id)
            self.details[node_id] = detail
            self.query_one("#detail-host").mount(detail)
            self.app.run_worker(self._load_detail(node_id), group=f"detail-{node_id}")
        detail.last_access = datetime.now().timestamp()
        detail.display = True
        self.query_one("#detail-title", Static).update(
            f"{'Container' if self.cache.get_node(node_id).is_container else 'Item'}: "
            f"{self.cache.get_node(node_id).label}"
        )
        self._evict_details()

    async def _load_detail(self, node_id: str) -> None:
        try:
            node = await self.app.load_node_detail(node_id)
        except Exception as error:
            self.app.show_message(f"Could not load node details: {error}")
            return

        detail = self.details.get(node_id)
        if detail is not None:
            detail.update_node(node)

    def _evict_details(self) -> None:
        now = datetime.now().timestamp()
        expired = [
            node_id
            for node_id, detail in self.details.items()
            if node_id != self.selected_id and now - detail.last_access > 300
        ]
        for node_id in expired:
            self.details.pop(node_id).remove()
