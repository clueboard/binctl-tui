# binctl-tui Implementation Plan

## Project Structure

```
binctl_tui/
    __init__.py
    app.py                  # BinctlApp entry point
    config.py               # Config dataclass + ConfigManager
    cache.py                # InventoryCache + Node model
    service.py              # InventoryService (async API wrapper)
    screens/
        __init__.py
        main.py             # MainScreen
        help.py             # HelpScreen
    widgets/
        __init__.py
        container_tree.py   # ContainerTree
        node_metadata.py    # NodeMetadataPane
        node_description.py # NodeDescriptionPane
    modals/
        __init__.py
        base.py             # BaseModal
        picker.py           # PickerModal (search + move)
        node_edit.py        # NodeEditModal (new + edit)
        confirm.py          # ConfirmModal
        message.py          # MessageModal
        config.py           # ConfigModal
    styles/
        main.tcss           # All TCSS styles
    help.md                 # Help content (placeholder)
```

Add `pyproject.toml` dependencies: `textual`, `platformdirs`. Install `binctl-client` as editable (`pip install -e ../binctl/binctl-client`). Add a `[project.scripts]` entry pointing to `binctl_tui.app:main`.

---

## Layer 1: Configuration (`config.py`)

### `Config` (dataclass)
Fields: `url: str`, `token: str | None`, `username: str | None`, `password: str | None`.

### `ConfigManager`
- Use `platformdirs.user_config_dir("binctl-tui")` to find the config directory.
- Persist as TOML. Structure the file to support multiple named profiles in the future: `[profiles.default]` holds the current config. Only implement the `default` profile now.
- Methods:
  - `load() -> Config` — reads from disk, returns defaults if file is absent.
  - `save(config: Config)` — writes the `default` profile to disk.

---

## Layer 2: Data Model (`cache.py`)

### `Node` (dataclass)
Fields mirroring the binctl API: `id: str`, `name: str`, `is_container: bool`, `description: str`, `tags: list[str]`, `parent_id: str | None`, `created_at: datetime`, `updated_at: datetime`.

### `InventoryCache`
The single source of truth for the UI. Holds the full DAG in memory and pre-builds indexes for fast lookup.

Internal structures:
- `_nodes: dict[str, Node]` — all nodes by ID
- `_children: dict[str, list[str]]` — parent_id → list of child IDs
- `_search_index: list[tuple[str, str]]` — list of `(node_id, "Home / Office / Bookshelf")` path strings, pre-built for search

Methods:
- `rebuild(nodes: list[Node])` — replace all internal state atomically from a fresh list of nodes. This also rebuilds `_children` and `_search_index`.
- `get_node(id: str) -> Node | None`
- `get_children(id: str) -> list[Node]` — sorted by name
- `get_roots() -> list[Node]` — nodes with no parent, sorted by name
- `get_path(id: str) -> list[Node]` — ordered ancestor list from root to node
- `get_path_string(id: str) -> str` — `"Home / Office / Bookshelf"`
- `search(query: str, containers_only: bool = False) -> list[tuple[str, str]]` — case-insensitive substring match against path strings; returns matching `(node_id, path_string)` pairs

`rebuild()` is the only mutating method. Call it on the main thread (or via `call_from_thread`) after a full DAG fetch.

---

## Layer 3: Service Layer (`service.py`)

### `InventoryService`
Wraps the binctl-client. Takes a reference to `BinctlApp` so it can increment/decrement `app.active_operations` and call `app.call_from_thread` when needed.

All public methods are `async`. Each one:
1. Increments `app.active_operations`.
2. Performs the API call(s).
3. Decrements `app.active_operations` in a `finally` block.

Methods:
- `fetch_token(username: str, password: str) -> str` — requests and returns a bearer token; stores it only in memory.
- `fetch_all_nodes() -> list[Node]` — fetches all pages from the API and returns a flat node list. Uses the binctl-client's node list endpoint, handling `next_cursor` pagination manually.
- `get_orphan_location() -> str | None` — fetches server config to get the orphan container ID.
- `create_node(name, is_container, parent_id, tags, description) -> Node`
- `update_node(id, **fields) -> Node`
- `delete_node(id: str)`
- `move_node(id: str, new_parent_id: str | None)`

On 4xx responses, raise a typed exception (e.g., `APIError(message: str)`) that the UI catches and shows via `MessageModal`.

---

## Layer 4: Application (`app.py`)

### `BinctlApp(App)`

Reactives:
- `active_operations: int = 0` — atomic counter. Bind the loading indicator's visibility to `active_operations > 0`.
- `selected_node_id: str | None = None`

Non-reactive state:
- `inventory_cache: InventoryCache`
- `inventory_service: InventoryService`
- `config: Config`
- `expansion_state: dict[str, bool]` — persists tree expand/collapse state across DAG refreshes. Keyed by node ID.
- `_quitting: bool = False`

Lifecycle:
- `on_mount()`: load config → if no URL configured, push `ConfigModal` → else proceed to `startup_flow()`.
- `startup_flow()`: if token provided use it; else call `fetch_token()`; verify by calling `get_orphan_location()`; if any error, push a `ConfirmModal`-style dialog offering "Exit" / "Configuration" as the two choices. On success, call `load_dag()`.
- `load_dag()`: calls `service.fetch_all_nodes()`, then `cache.rebuild(nodes)`, then posts `DagLoaded` message to update the tree.
- `refresh_dag(focus_id: str | None = None)`: same as `load_dag()` but after rebuild, restores `expansion_state` and calls `main_screen.tree.navigate_to(focus_id)` if provided.

Quit flow:
- On `Q` or app close: set `_quitting = True`. If `active_operations == 0`, exit. Otherwise push a modal offering "Wait" / "Exit Now". If wait is chosen, watch `active_operations` and exit when it hits 0 (with a hard timeout of ~10 seconds, after which show a second "still waiting / force exit" prompt).

Key bindings defined on the App (active when no modal is focused):
- `N` → `action_new_node()`
- `M` → `action_move_node()`
- `E` → `action_edit_node()`
- `D` → `action_delete_node()`
- `/` → `action_search()`
- `space` → `action_toggle_container()`
- `` ` ``, `~` → `action_toggle_sidebar()`
- `Q` → `action_quit()`
- `F1` → `push_screen(HelpScreen())`
- `F2` → `action_open_config()` (dismiss open modal first if any)
- `F5` → `refresh_dag()`

### `main` entry point
Load config, instantiate `BinctlApp`, call `app.run()`.

---

## Layer 5: Screens

### `MainScreen(Screen)` (`screens/main.py`)

Layout (TCSS):
- Horizontal split: `#sidebar` (25%) + `#right-panel` (75%).
- `#right-panel` vertical split: `#metadata-pane` (top half) + `#description-pane` (bottom half).
- `Footer` spans full width at the bottom.

Composed of:
- `Static` header bar above the tree (shows loading indicator + "Containers" title).
- `ContainerTree` inside `#sidebar`.
- `NodeMetadataPane` in top-right.
- `NodeDescriptionPane` in bottom-right.

Sidebar hide/show: controlled by toggling a `.hidden` CSS class on `#sidebar`. Never use `display = False`. See design doc for the CSS using `width: 0` and `overflow: hidden hidden`.

The `ContainerTree` always retains focus, even when the sidebar is visually hidden.

### `HelpScreen(Screen)` (`screens/help.py`)

Full-screen push. Contains a `Markdown` widget rendering `help.md`. Dismiss with `Esc` or `Q`. No other interaction.

---

## Layer 6: Widgets

### `ContainerTree(Tree)` (`widgets/container_tree.py`)

Subclass of `Textual.Tree`. Responsible for all tree rendering and navigation.

Methods:
- `rebuild(cache: InventoryCache, expansion_state: dict[str, bool])` — clears and repopulates the tree from the cache. Each `TreeNode`'s `data` attribute holds the node's ID string. Applies expansion state, expanding nodes that were previously expanded.
- `navigate_to(node_id: str)` — walks the ancestor path, expands each ancestor (updating `app.expansion_state`), scrolls the tree, and sets focus/cursor to the target node.
- `get_selected_node_id() -> str | None` — returns the node ID of the currently highlighted tree node.

On cursor move, post a message `NodeSelected(node_id: str)` that `MainScreen` handles to update the metadata and description panes, and to trigger a node detail fetch.

Node labels: show a `►` (collapsed) or `▼` (expanded) prefix for containers. Items have no prefix glyph (or a simple space indent for alignment).

On `on_tree_node_expanded` / `on_tree_node_collapsed`, update `app.expansion_state[node_id]`.

### `NodeMetadataPane(Widget)` (`widgets/node_metadata.py`)

A non-focusable display widget. Renders: Label, Created, Modified, Tags as a formatted list. Updates reactively when the selected node changes.

### `NodeDescriptionPane(Markdown)` (`widgets/node_description.py`)

A scrollable `Markdown` widget. `Page Up` / `Page Down` scroll it. Updates when the selected node changes.

---

## Layer 7: Modals

### `BaseModal(ModalScreen)` (`modals/base.py`)

Base class for all modals. Sets a consistent width. Dismisses on `Esc` with `None` as the result. Does not dismiss on `Enter` by default (subclasses handle that).

### `PickerModal(BaseModal)` (`modals/picker.py`)

Used for both **Search** (`/`) and **Move** (`M`). Constructor params: `title: str`, `items: list[tuple[str, str]]` (node_id, path_string pairs), `filter_to_containers: bool = False`.

Layout:
- `Input` at top (always focused).
- `OptionList` below showing filtered path strings.

Behavior:
- Typing in `Input` filters the `OptionList` via case-insensitive substring match.
- `Down` arrow key is intercepted at the modal level: do not move focus; instead programmatically scroll/highlight the next item in `OptionList`.
- `Enter` dismisses with the highlighted `node_id`, or `None` if nothing is highlighted.
- `Esc` dismisses with `None`.

Formatting: use Textual Rich markup to dim ancestor path segments and brightly highlight the substring that matched the query.

### `NodeEditModal(BaseModal)` (`modals/node_edit.py`)

Used for both **New** (`N`) and **Edit** (`E`). Constructor params: `node: Node | None`, `default_parent_id: str | None`.

Fields (in order):
1. `Input` — Name
2. `Switch` / `Checkbox` — Is Container
3. Parent display (read-only `Static` showing path string + a `Button` to change it). Clicking the button pushes `PickerModal(containers_only=True)` and updates the field on return. First entry in the picker list is `<No Parent>` mapping to `None`.
4. `Input` — Tags (comma-separated raw string)
5. `TextArea` — Description (grows to a max height, then scrolls)
6. Cancel (left) / Submit (right) buttons

Pre-populate all fields from `node` when editing. Default Parent to `default_parent_id` when creating.

On Submit:
- Compose API call (`create_node` or `update_node`).
- If `APIError` is raised, push `MessageModal(error.message)` and keep this modal open.
- On success, dismiss with the returned `Node`.

Tags: split on commas to build a list for the API. The service layer handles creating new tag objects as needed.

### `ConfirmModal(BaseModal)` (`modals/confirm.py`)

Constructor params: `message: str`, `affirmative_default: bool = False`.

Layout:
- `Static` message area (auto-height).
- Cancel button (left) / Ok button (right).

Default focus is on Cancel unless `affirmative_default=True`. `Enter` activates the focused button. Dismisses with `True` (Ok) or `False` (Cancel/Esc).

### `MessageModal(BaseModal)` (`modals/message.py`)

Constructor param: `message: str`.

Layout:
- `Static` message area (auto-height).
- Ok button (right only).

Dismisses with `None` on Ok or Esc.

### `ConfigModal(BaseModal)` (`modals/config.py`)

Fields:
- `Input` — binctl URL
- `Input` (password mode) — Token
- `Input` — Username
- `Input` (password mode) — Password
- Ok button

When Token has a value, Username and Password inputs are disabled and display `*disabled*` as placeholder text. The actual stored values are preserved; they are re-enabled if Token is cleared.

Pre-populate from current `Config`. On Ok: save via `ConfigManager`, update `app.config`, trigger `app.refresh_dag()`.

---

## Key Flows

### Startup
1. `BinctlApp.on_mount()` loads config from disk.
2. If URL is empty, push `ConfigModal`.
3. Otherwise call `startup_flow()`:
   - If token present, use it. Else call `service.fetch_token(username, password)`, store in memory only.
   - Call `service.get_orphan_location()` to validate the token.
   - On any error, push a two-button dialog: "Exit" dismisses the app, "Configuration" pushes `ConfigModal`.
4. Call `load_dag()`.

### DAG Refresh
1. Call `service.fetch_all_nodes()` (async, increments `active_operations`).
2. On completion: `cache.rebuild(nodes)`.
3. Post `DagLoaded` message (or call `call_from_thread`).
4. `MainScreen` handles `DagLoaded`: calls `tree.rebuild(cache, expansion_state)`.
5. If a `focus_id` was provided, call `tree.navigate_to(focus_id)`.

### Move Node
1. Push `PickerModal(title="Move", items=containers_only_paths)`.
2. On result (new parent ID or None for no parent): call `service.move_node(selected_id, new_parent_id)`.
3. Call `refresh_dag(focus_id=moved_node_id)`.

### Search
1. Push `PickerModal(title="Search", items=all_node_paths)`.
2. On result (selected node ID): call `tree.navigate_to(node_id)`.

### Delete Item
1. Push `ConfirmModal("Delete '<name>'? This cannot be undone.")`.
2. On `True`: call `service.delete_node(id)`, then `refresh_dag()`.

### Delete Container
1. Fetch orphan location name from cache (or service).
2. Push `ConfirmModal("Delete '<name>'? Children will be moved to '<orphan_location>' (or root if none).")`.
3. On `True`: call `service.delete_node(id)`, then `refresh_dag()`.

### Quit
1. Set `app._quitting = True`.
2. If `active_operations == 0`: call `app.exit()`.
3. Otherwise push a modal with "Wait" and "Exit Now".
   - "Exit Now": `app.exit()` immediately.
   - "Wait": watch `active_operations`; exit when 0. If not zero after 10 seconds, push "Still busy. Force exit?" prompt.

---

## Thread Safety Notes

- `InventoryCache.rebuild()` must only be called from the main asyncio thread (use `call_from_thread` if called from a background OS thread).
- Increment/decrement of `active_operations` must be done atomically. Use `app.active_operations += 1` in the asyncio event loop; asyncio is single-threaded so this is safe for async tasks. If ever using `asyncio.to_thread()` for CPU-heavy work, use `call_from_thread` to update `active_operations`.
- Never manipulate Textual widget state from outside the event loop.
- The `expansion_state` dict is read/written only from the main thread.

---

## Styles (`styles/main.tcss`)

Key rules to implement:
- Sidebar hide/show via `.hidden` class: `width: 0`, `overflow: hidden hidden`, `border: none`, `padding/margin: 0`. Normal state: `width: 25%`, `transition: width 150ms`.
- Loading indicator shown/hidden via reactive binding to `active_operations > 0`.
- Modal widths: consistent across all modals (e.g., `width: 60`).
- NodeMetadataPane: non-focusable, no scrollbar.

---

## Testing Notes

- Use `blanket` for any tests involving async/concurrent behavior once race conditions are discovered.
- Unit-test `InventoryCache` methods independently with fixture node lists.
- Unit-test `ConfigManager` load/save with a temp directory.
- Integration-test `InventoryService` against a mock HTTP server.
- Do not attempt to exhaustively identify race conditions upfront; write blanket tests when specific races are found.
