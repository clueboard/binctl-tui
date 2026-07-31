"""Textual application orchestration and inventory workflows."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from binctl_client import Client
from binctl_client.models.node import Node
from binctl_client.models.node_create import NodeCreate
from binctl_client.models.node_update import NodeUpdate
from binctl_client.models.server_config import ServerConfig
from binctl_client.models.tag import Tag
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive

from . import config
from .cache import InventoryCache
from .modals.confirm import ConfirmModal
from .modals.message import MessageModal
from .modals.node_edit import NodeDraft, NodeEditModal
from .modals.picker import PickerModal
from .modals.settings import ConfigModal
from .screens.help import HelpScreen
from .screens.main import MainScreen
from .service import (
    build_client,
    create_node,
    delete_node,
    fetch_all_nodes,
    fetch_all_tags,
    fetch_node,
    fetch_server_config,
    get_or_create_tag,
    update_node,
)
from .tags import normalize_tag_name


class BinctlApp(App[None]):
    """A responsive Textual frontend backed by binctl's asynchronous API."""

    TITLE = "binctl-tui"
    CSS_PATH = "tcss/app.tcss"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("n", "new_node", "New"),
        Binding("m", "move_node", "Move"),
        Binding("e", "edit_node", "Edit"),
        Binding("d", "delete_node", "Delete"),
        Binding("/", "search", "Search"),
        Binding("space", "toggle_container", "Toggle"),
        Binding("grave", "toggle_sidebar", "Sidebar", key_display="~"),
        Binding("tilde", "toggle_sidebar", "Sidebar", show=False),
        Binding("q", "quit_gracefully", "Quit"),
        Binding("ctrl+c", "interrupt", "Quit", show=False),
        Binding("f1", "help", "Help"),
        Binding("f2", "configuration", "Config"),
        Binding("f5", "refresh", "Refresh"),
        Binding("pageup", "scroll_description_up", "Description", show=False),
        Binding("pagedown", "scroll_description_down", "Description", show=False),
    ]

    active_operations = reactive(0)

    def __init__(self) -> None:
        super().__init__()
        self.client: Client | None = None
        self.server_config: ServerConfig | None = None
        self.cache = InventoryCache()
        self.tag_index: dict[str, Tag] = {}
        self.expansion: dict[str, bool] = {}
        self.shutdown_started = False

    def compose(self) -> ComposeResult:
        yield MainScreen()

    def on_mount(self) -> None:
        settings = config.load_config()

        if not settings:
            self.push_screen(ConfigModal(settings), self._initial_configuration_saved)
            return

        self.run_worker(self._initialize(), group="startup", exclusive=True)

    def watch_active_operations(self, count: int) -> None:
        if self.is_mounted:
            self.query_one(MainScreen).set_loading(count > 0)

    @asynccontextmanager
    async def operation(self) -> AsyncIterator[None]:
        self.active_operations += 1
        try:
            yield
        finally:
            self.active_operations -= 1

    async def _initialize(self) -> None:
        try:
            self.client = build_client(config.CONFIG)
            async with self.operation():
                self.server_config = await fetch_server_config(self.client)
            await self.refresh_inventory()
        except Exception as error:
            self.push_screen(
                ConfirmModal(
                    f"Could not connect to binctl: {error}\n\nOpen configuration?",
                    default_affirmative=True,
                ),
                self._startup_error_choice,
            )

    def _startup_error_choice(self, configure: object | None) -> None:
        if configure:
            self.action_configuration()
        else:
            self.exit()

    async def refresh_inventory(self, selected_id: str | None = None) -> None:
        if self.client is None:
            raise RuntimeError("The API client has not been configured")
        async with self.operation():
            nodes, tags = await asyncio.gather(
                fetch_all_nodes(self.client),
                fetch_all_tags(self.client),
            )
        self.cache.build(nodes)
        self.tag_index = {normalize_tag_name(tag.name): tag for tag in tags}
        self.query_one(MainScreen).set_cache(
            self.cache,
            self.expansion,
            selected_id,
        )

    async def load_node_detail(self, node_id: str) -> Node:
        if self.client is None:
            raise RuntimeError("The API client has not been configured")
        async with self.operation():
            node = await fetch_node(self.client, node_id)

        return node

    def action_refresh(self) -> None:
        self.run_worker(
            self._refresh_with_message(),
            group="refresh",
            exclusive=True,
        )

    async def _refresh_with_message(self) -> None:
        selected_id = self.query_one(MainScreen).selected_id
        try:
            if self.client is not None:
                async with self.operation():
                    self.server_config = await fetch_server_config(self.client)
            await self.refresh_inventory(selected_id)
        except Exception as error:
            self.show_message(f"Could not refresh inventory: {error}")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_configuration(self) -> None:
        self.push_screen(ConfigModal(config.CONFIG), self._configuration_saved)

    def _initial_configuration_saved(self, values: object | None) -> None:
        """Exit if the mandatory first-run configuration is cancelled or empty."""
        if not isinstance(values, dict) or not values.get("url", "").strip():
            self.exit()
            return

        self._configuration_saved(values)

    def _configuration_saved(self, values: object | None) -> None:
        if not isinstance(values, dict):
            return
        self.run_worker(self._apply_configuration(values), group="configuration", exclusive=True)

    async def _apply_configuration(self, values: dict[str, str]) -> None:
        try:
            config.save_config(values)
            self.client = build_client(config.CONFIG)
            async with self.operation():
                self.server_config = await fetch_server_config(self.client)
            await self.refresh_inventory()
        except Exception as error:
            self.show_message(f"Could not apply configuration: {error}")

    def action_search(self) -> None:
        self.push_screen(
            PickerModal("Search", self.cache),
            self._search_picked,
        )

    def _search_picked(self, node_id: object | None) -> None:
        if not isinstance(node_id, str) or node_id not in self.cache.nodes:
            return
        self._select_with_ancestors(node_id)

    def action_toggle_sidebar(self) -> None:
        self.query_one(MainScreen).toggle_sidebar()

    def action_toggle_container(self) -> None:
        self.query_one(MainScreen).toggle_selected_container()

    def action_new_node(self) -> None:
        selected_id = self.query_one(MainScreen).selected_id
        parent_id = self._default_parent(selected_id)
        initial: NodeDraft = {
            "label": "",
            "is_container": False,
            "parent_id": parent_id,
            "tag_names": [],
            "description": "",
        }
        self.push_screen(NodeEditModal(self.cache, title="New Node", initial=initial))

    def action_edit_node(self) -> None:
        node_id = self.query_one(MainScreen).selected_id
        if node_id is None:
            return
        self.run_worker(self._open_edit(node_id), group="edit-form", exclusive=True)

    async def _open_edit(self, node_id: str) -> None:
        try:
            node = await self.load_node_detail(node_id)
        except Exception as error:
            self.show_message(f"Could not load node for editing: {error}")
            return
        tags = [] if not isinstance(node.tags, list) else [
            normalize_tag_name(tag.name) for tag in node.tags
        ]
        parent_id = node.parent_id if isinstance(node.parent_id, str) else None
        description = node.description if isinstance(node.description, str) else ""
        initial: NodeDraft = {
            "label": node.label,
            "is_container": node.is_container,
            "parent_id": parent_id,
            "tag_names": tags,
            "description": description,
        }
        self.push_screen(
            NodeEditModal(self.cache, title="Edit Node", initial=initial),
        )

    def submit_node_draft(self, modal: NodeEditModal, draft: NodeDraft) -> None:
        selected_id = self.query_one(MainScreen).selected_id
        modal.set_busy(True)
        self.run_worker(
            self._save_node_draft(modal, draft, selected_id),
            group="node-save",
            exclusive=True,
        )

    async def _save_node_draft(
        self,
        modal: NodeEditModal,
        draft: NodeDraft,
        node_id: str | None,
    ) -> None:
        mutation_succeeded = False
        refresh_succeeded = False
        try:
            if self.client is None:
                raise RuntimeError("The API client has not been configured")
            async with self.operation():
                tag_ids = [
                    (await get_or_create_tag(self.client, self.tag_index, name)).id
                    for name in draft["tag_names"]
                ]
                if node_id is None:
                    saved = await create_node(
                        self.client,
                        NodeCreate(
                            label=draft["label"],
                            description=draft["description"],
                            is_container=draft["is_container"],
                            parent_id=draft["parent_id"],
                            tag_ids=tag_ids,
                        ),
                    )
                else:
                    saved = await update_node(
                        self.client,
                        node_id,
                        NodeUpdate(
                            label=draft["label"],
                            description=draft["description"],
                            is_container=draft["is_container"],
                            parent_id=draft["parent_id"],
                            tag_ids=tag_ids,
                        ),
                    )
                mutation_succeeded = True
            await self.refresh_inventory(saved.id)
            refresh_succeeded = True
        except Exception as error:
            if mutation_succeeded:
                modal.dismiss(None)
                self.show_message(
                    "Saved, but could not refresh the inventory. Press F5 to reload.",
                )
            else:
                self.show_message(f"Could not save node: {error}")
        finally:
            if modal.is_mounted:
                modal.set_busy(False)

        if mutation_succeeded and refresh_succeeded and modal.is_mounted:
            modal.dismiss(None)

    def action_move_node(self) -> None:
        node_id = self.query_one(MainScreen).selected_id
        if node_id is None:
            return
        self.push_screen(
            PickerModal(
                "Move",
                self.cache,
                containers_only=True,
                include_no_parent=True,
            ),
            lambda parent_id: self._move_picked(node_id, parent_id),
        )

    def _move_picked(self, node_id: str, parent_id: object | None) -> None:
        if parent_id is PickerModal.NO_PARENT:
            self.run_worker(
                self._move_node(node_id, None),
                group="move",
                exclusive=True,
            )
            return
        if parent_id is not None and not isinstance(parent_id, str):
            return
        self.run_worker(
            self._move_node(node_id, parent_id),
            group="move",
            exclusive=True,
        )

    async def _move_node(self, node_id: str, parent_id: str | None) -> None:
        try:
            if self.client is None:
                raise RuntimeError("The API client has not been configured")
            async with self.operation():
                await update_node(self.client, node_id, NodeUpdate(parent_id=parent_id))
            await self.refresh_inventory(node_id)
            self._select_with_ancestors(node_id)
        except Exception as error:
            self.show_message(f"Could not move node: {error}")

    def action_delete_node(self) -> None:
        node_id = self.query_one(MainScreen).selected_id
        if node_id is None:
            return
        node = self.cache.get_node(node_id)
        fallback = self._delete_fallback(node_id)
        message = f"Delete {node.label!r}? This cannot be undone."

        if node.is_container:
            orphan = (
                self.server_config.orphan_location
                if self.server_config and self.server_config.orphan_location
                else "root"
            )
            message = (
                f"Delete {node.label!r}? Any items inside will be moved to "
                f"{orphan!r}."
            )
        self.push_screen(
            ConfirmModal(message),
            lambda confirmed: self._delete_confirmed(node_id, fallback, confirmed),
        )

    def _delete_confirmed(
        self,
        node_id: str,
        fallback: str | None,
        confirmed: object | None,
    ) -> None:
        if confirmed:
            self.run_worker(
                self._delete_node(node_id, fallback),
                group="delete",
                exclusive=True,
            )

    async def _delete_node(self, node_id: str, fallback: str | None) -> None:
        try:
            if self.client is None:
                raise RuntimeError("The API client has not been configured")
            async with self.operation():
                await delete_node(self.client, node_id)
            await self.refresh_inventory(fallback)
        except Exception as error:
            self.show_message(f"Could not delete node: {error}")

    def action_scroll_description_up(self) -> None:
        self._scroll_description(-1)

    def action_scroll_description_down(self) -> None:
        self._scroll_description(1)

    def _scroll_description(self, direction: int) -> None:
        screen = self.query_one(MainScreen)
        node_id = screen.selected_id
        if node_id and node_id in screen.details:
            screen.details[node_id].query_one(
                f"#description-{node_id}",
            ).scroll_relative(y=direction * 5)

    def action_quit_gracefully(self) -> None:
        if self.shutdown_started:
            return
        self.shutdown_started = True
        self.run_worker(self._graceful_quit(), group="shutdown", exclusive=True)

    def action_interrupt(self) -> None:
        if self.shutdown_started:
            raise SystemExit(130)
        self.action_quit_gracefully()

    async def _graceful_quit(self) -> None:
        try:
            await asyncio.wait_for(self._wait_for_operations(), timeout=5)
            self.exit()
        except TimeoutError:
            self.push_screen(
                ConfirmModal(
                    "Operations are still running. Exit now?",
                    default_affirmative=False,
                ),
                self._quit_timeout_choice,
            )

    async def _wait_for_operations(self) -> None:
        while self.active_operations:
            await asyncio.sleep(0.05)

    def _quit_timeout_choice(self, exit_now: object | None) -> None:
        if exit_now:
            self.exit()
        else:
            self.shutdown_started = False

    def show_message(self, message: str) -> None:
        self.push_screen(MessageModal(message))

    def _default_parent(self, selected_id: str | None) -> str | None:
        if selected_id is None:
            return None
        node = self.cache.get_node(selected_id)
        if node.is_container:
            return selected_id

        return node.parent_id if isinstance(node.parent_id, str) else None

    def _select_with_ancestors(self, node_id: str) -> None:
        path = self.cache.get_path(node_id)
        for ancestor in path[:-1]:
            if ancestor.is_container:
                self.expansion[ancestor.id] = True
        screen = self.query_one(MainScreen)
        screen._build_tree(self.expansion)
        screen.select_node(node_id)

    def _delete_fallback(self, node_id: str) -> str | None:
        node = self.cache.get_node(node_id)
        parent_id = node.parent_id if isinstance(node.parent_id, str) else None
        siblings = (
            self.cache.children.get(parent_id, [])
            if parent_id
            else self.cache.roots
        )
        index = siblings.index(node_id)

        if index > 0:
            return siblings[index - 1]
        if parent_id:
            return parent_id
        if index + 1 < len(siblings):
            return siblings[index + 1]

        return None
