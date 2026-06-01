# binctl-tui Implementation Plan

## Project Structure

```
binctl_tui/
    __init__.py
    app.py                  # BinctlApp entry point
    config.py               # load_config() / save_config()
    nodes.py                # Pure functions over the node dict
    service.py              # Async API functions
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

## Configuration (`config.py`)

Config is a plain dict with keys: `url`, `token`, `username`, `password`. All values are strings or `None`.

Two module-level functions:
- `load_config() -> dict` — reads from disk using `platformdirs.user_config_dir("binctl-tui")`. Persists as TOML structured as `[profiles.default]` to support multiple profiles in the future. Returns a dict with all keys present (defaulting absent keys to `None`).
- `save_config(config: dict)` — writes the `default` profile to disk.

---

## Node Data (`nodes.py`)

The app holds all nodes in memory as `app.nodes: dict[str, dict]`, where each value is a plain dict with keys matching the API fields: `id`, `label`, `is_container`, `description`, `parent_id`, `tags`, `created_at`, `updated_at`. `description` and `parent_id` are `str | None`. `tags` is `list[tuple[str, str]]` (id, name pairs).

`nodes.py` contains pure functions that take the nodes dict and return results. None of these functions mutate state.

Functions:
- `get_children(nodes, parent_id) -> list[dict]` — sorted by label
- `get_roots(nodes) -> list[dict]` — nodes where `parent_id` is `None`, sorted by label
- `get_path(nodes, node_id) -> list[dict]` — ordered ancestor list from root to node
- `get_path_string(nodes, node_id) -> str` — `"Home / Office / Bookshelf"`
- `build_search_index(nodes) -> list[tuple[str, str]]` — computes `(node_id, path_string)` pairs for all nodes; call once after a fetch and store as `app.search_index`
- `search(index, query, containers_only=False) -> list[tuple[str, str]]` — case-insensitive substring match against the pre-built index; returns matching `(node_id, path_string)` pairs

---

## Service Layer (`service.py`)

Module-level async functions that wrap the binctl-client. Each function increments `app.active_operations` on entry and decrements it in a `finally` block.

The binctl-client returns `attrs` objects with `Unset` sentinel values on optional fields. All service functions normalize these at the boundary before returning: `Unset` becomes `None`. The rest of the app never sees `Unset`. The client's `Node` and `NodeChild` types are both normalized into the same plain dict shape.

Functions:
- `fetch_token(app, username, password) -> str` — returns a bearer token, stored in memory only
- `fetch_all_nodes(app) -> dict[str, dict]` — fetches all pages (handling pagination manually), normalizes each node, returns the full `nodes` dict ready to assign to `app.nodes`
- `get_orphan_location(app) -> str | None`
- `create_node(app, label, is_container, parent_id, tags, description) -> dict`
- `update_node(app, node_id, **fields) -> dict`
- `delete_node(app, node_id)`
- `move_node(app, node_id, new_parent_id)`

Tags: `create_node` and `update_node` receive tags as a list of name strings. The service layer resolves these against the API — fetching existing tags by name, creating new ones as needed — and submits the correct tag IDs.

On 4xx responses, raise `APIError(message)`. The UI catches this and shows a `MessageModal`, keeping the originating modal open.

---

## Application (`app.py`)

### `BinctlApp(App)`

Reactives:
- `active_operations: int = 0` — bind the loading indicator's visibility to `active_operations > 0`
- `selected_node_id: str | None = None`

Plain state:
- `nodes: dict[str, dict]` — the full node set, replaced wholesale on each fetch
- `search_index: list[tuple[str, str]]` — pre-built `(node_id, path_string)` pairs, rebuilt after each fetch via `build_search_index()`
- `config: dict` — current config, loaded from disk on startup
- `expansion_state: dict[str, bool]` — tree expand/collapse state, keyed by node ID, persisted across node refreshes
- `_quitting: bool = False`

Lifecycle:
- `on_mount()`: call `load_config()` → if `config['url']` is absent, push `ConfigModal` → else call `startup_flow()`
- `startup_flow()`: use token if present, else call `fetch_token()`; verify by calling `get_orphan_location()`; on any error push a two-button dialog offering "Exit" / "Configuration". On success call `load_nodes()`.
- `load_nodes()`: calls `fetch_all_nodes()`, assigns result to `app.nodes`, calls `build_search_index()` and stores result as `app.search_index`, posts `NodesLoaded` message.
- `refresh_nodes(focus_id=None)`: same as `load_nodes()` but after assignment, restores `expansion_state` and navigates to `focus_id` if provided.

Quit flow: set `_quitting = True`. Once `active_operations == 0`, exit immediately. Wait for a timeout (5 seconds) then push a modal with "Wait" / "Exit Now". If waiting, exit when `active_operations` hits 0. Hard timeout of ~10 seconds, then prompt "Still busy. Force exit?".

Key bindings (active when no modal is focused):
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
- `F5` → `refresh_nodes()`

### `main` entry point
Instantiate `BinctlApp` and call `app.run()`.

---

## Screens

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

Sidebar hide/show: toggle a `.hidden` CSS class on `#sidebar`. Never use `display = False`. See design doc for the CSS using `width: 0` and `overflow: hidden hidden`.

The `ContainerTree` always retains focus, even when the sidebar is visually hidden.

### `HelpScreen(Screen)` (`screens/help.py`)

Full-screen push. Contains a `Markdown` widget rendering `help.md`. Dismiss with `Esc` or `Q`.

---

## Widgets

### `ContainerTree(Tree)` (`widgets/container_tree.py`)

Methods:
- `rebuild(nodes, expansion_state)` — clears and repopulates the tree. Each `TreeNode.data` holds the node's ID string. Applies expansion state.
- `navigate_to(node_id)` — expands ancestors, scrolls, and moves cursor to the target node, updating `app.expansion_state` along the way.
- `get_selected_node_id() -> str | None`

On cursor move, posts `NodeSelected(node_id)` for `MainScreen` to handle.

On `on_tree_node_expanded` / `on_tree_node_collapsed`, updates `app.expansion_state[node_id]`.

Node labels: `►` / `▼` prefix for containers, plain label for items.

### `NodeMetadataPane(Widget)` (`widgets/node_metadata.py`)

Non-focusable. Renders label, created, modified, and tags for the selected node. Updates when `selected_node_id` changes.

### `NodeDescriptionPane(Markdown)` (`widgets/node_description.py`)

Scrollable `Markdown` widget. `Page Up` / `Page Down` scroll it. Updates when `selected_node_id` changes.

---

## Modals

### `BaseModal(ModalScreen)` (`modals/base.py`)

Consistent width. Dismisses on `Esc` with `None`.

### `PickerModal(BaseModal)` (`modals/picker.py`)

Used for **Search** (`/`) and **Move** (`M`). Params: `title`, `items` (list of `(node_id, path_string)` tuples), `filter_to_containers`.

- `Input` at top, always focused.
- `OptionList` below, filtered as the user types.
- `Down` arrow intercepted at modal level: highlights next `OptionList` item without moving focus from `Input`.
- `Enter` dismisses with highlighted node ID. `Esc` dismisses with `None`.
- Rich markup: dim ancestor segments, highlight matching substring.

### `NodeEditModal(BaseModal)` (`modals/node_edit.py`)

Used for **New** (`N`) and **Edit** (`E`). Params: `node` (dict or `None`), `default_parent_id`.

Fields: Name (`Input`), Is Container (`Switch`), Parent (read-only display + button that opens `PickerModal`), Tags (`Input`, comma-separated), Description (`TextArea`), Cancel / Submit buttons.

First entry in the parent picker is `<No Parent>` → `None`.

On Submit: call `create_node` or `update_node`. On `APIError`, push `MessageModal` and keep this modal open. On success, dismiss with the returned node dict.

### `ConfirmModal(BaseModal)` (`modals/confirm.py`)

Params: `message`, `affirmative_default=False`. Auto-height message area. Cancel (left) / Ok (right). Dismisses with `True` or `False`.

### `MessageModal(BaseModal)` (`modals/message.py`)

Param: `message`. Auto-height message area. Ok button (right). Dismisses with `None`.

### `ConfigModal(BaseModal)` (`modals/config.py`)

Fields: URL, Token, Username, Password. When Token is non-empty, Username and Password are disabled and show `*disabled*` as placeholder (stored values are preserved). Pre-populated from `app.config`. On Ok: call `save_config()`, update `app.config`, call `app.refresh_nodes()`.

---

## Key Flows

### Startup
1. `on_mount()` calls `load_config()`.
2. If no URL, push `ConfigModal`.
3. Otherwise `startup_flow()`: authenticate, verify via `get_orphan_location()`, on error show Exit/Configuration dialog, on success call `load_nodes()`.

### Node Refresh
1. `fetch_all_nodes()` returns a fresh `dict[str, dict]`.
2. Assign to `app.nodes`.
3. Post `NodesLoaded` message.
4. `MainScreen` handles `NodesLoaded`: calls `tree.rebuild(app.nodes, app.expansion_state)`.
5. If `focus_id` provided, call `tree.navigate_to(focus_id)`.

### Move Node
1. Push `PickerModal` (containers only), built from `nodes.search(app.nodes, "", containers_only=True)`.
2. On result: call `move_node()`, then `refresh_nodes(focus_id=moved_node_id)`.

### Search
1. Push `PickerModal` (all nodes).
2. On result: call `tree.navigate_to(node_id)`.

### Delete Item
1. Push `ConfirmModal`.
2. On `True`: call `delete_node()`, then `refresh_nodes()`.

### Delete Container
1. Push `ConfirmModal` with orphan location note.
2. On `True`: call `delete_node()`, then `refresh_nodes()`.

### Quit
1. Set `_quitting = True`.
2. If `active_operations == 0`: exit.
3. Otherwise: "Wait" / "Exit Now" modal. On wait, exit when operations drain. Hard timeout ~10s, then force-exit prompt.

---

## Thread Safety Notes

- `app.nodes` is replaced atomically (single assignment) from the asyncio event loop — safe since asyncio is single-threaded.
- If `asyncio.to_thread()` is ever used for CPU-heavy work, hand results back via `call_from_thread()`.
- Never manipulate Textual widget state from outside the event loop.
- `app.expansion_state` is read/written only from the main thread.

---

## Styles (`styles/main.tcss`)

- Sidebar: `width: 25%`, `transition: width 150ms`. `.hidden` class: `width: 0`, `overflow: hidden hidden`, `border: none`, `padding: 0`, `margin: 0`.
- Loading indicator visibility bound to `active_operations > 0`.
- Consistent modal width across all modals.
- `NodeMetadataPane`: non-focusable, no scrollbar.

---

## Testing Notes

- Use `blanket` for async/concurrent tests when specific races are found — do not attempt to identify races exhaustively upfront.
- Unit-test `nodes.py` functions with fixture dicts.
- Unit-test `load_config` / `save_config` with a temp directory.
- Integration-test service functions against a mock HTTP server.
