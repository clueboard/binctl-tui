# binctl-tui Implementation Plan

## Overview

A Textual TUI frontend for binctl. Layered architecture: binctl API client → async service layer → DAG cache → Textual UI.

## Project Structure

```
binctl_tui/
├── __init__.py
├── __main__.py          # Entry point: `python -m binctl_tui`
├── app.py               # Textual App class, keybindings, main screen
├── config.py            # Config read/write using platformdirs, TOML format
├── service.py           # Async service layer (wraps binctl-client, handles pagination)
├── cache.py             # DAG model: node lookup, parent/child/path/search index
├── screens/
│   ├── __init__.py
│   ├── main.py          # MainScreen: 3-pane layout (Tree | Metadata | Description)
│   └── help.py          # HelpScreen: full-screen Markdown help
├── modals/
│   ├── __init__.py
│   ├── base.py          # BaseModal helper class
│   ├── settings.py      # ConfigModal: URL, Token, Username, Password
│   ├── confirm.py       # ConfirmModal: Cancel / Ok
│   ├── message.py       # MessageModal: Ok only
│   ├── picker.py        # PickerModal: search + OptionList (used for Move & Search)
│   └── node_edit.py     # NodeEditModal: New/Edit node form
└── tcss/
    └── app.tcss         # Textual CSS: layout, sidebar hide animation
```

## Data Storage

### Persistent (disk)

| What | Format | Location |
|:-----|:-------|:---------|
| User config (URL, credentials) | TOML | `platformdirs.user_config_dir("binctl-tui") / config.toml` |

Config file structure supports multiple named profiles for future use; V1 reads/writes only `[profiles.default]`.

No other state is persisted to disk. The DAG, expansion state, and search index are rebuilt from the API on each startup.

### In-memory (runtime)

| What | Lives in | Notes |
|:-----|:---------|:------|
| Loaded config | Module-level singleton in `config.py` | Loaded once at startup via `load_config()`; `save_config()` updates both disk and the in-memory singleton; all other modules import from `config.py` to read it |
| API client | `app.py` app instance | Rebuilt on config change or auth refresh |
| Bearer token | `app.py` app instance | Never written to disk when obtained via username+password login |
| Server config (orphan location) | `app.py` app instance | Fetched once at startup, refreshed on F5 |
| DAG + search index | `InventoryCache` (cache.py) | Rebuilt from API on startup and after any mutating operation |
| Tree expansion state | `app.py` app instance (`dict[str, bool]`) | Preserved across DAG rebuilds so the UI doesn't jolt |
| Active operations counter | `MainScreen` reactive | Drives `LoadingIndicator` visibility |



- Add 'binctl-client', `textual`, `platformdirs`, `tomli-w` to `pyproject.toml`
- Create package skeleton with `__main__.py` entry point
- Create stub `app.py` that launches with `textual run`

## Phase 2: Config Module (`config.py`)

- Use `platformdirs.user_config_dir("binctl-tui")` for config path
- Store as TOML: `config.toml` with `[profiles.default]` section (future-proof for multiple profiles)
- Fields per profile: `url`, `token`, `username`, `password`
- Functions: `load_config(profile="default")`, `save_config(data, profile="default")`

## Phase 3: Async Service Layer (`service.py`)

Wraps binctl-client API functions. Network calls are always async; never block the main thread.

- Handles **pagination** for `get_nodes_list` (loop until `offset + len(items) >= total`)
- Handles **auth**: if token provided use directly; else call login endpoint to get bearer token; on error surface to caller
- Async functions:
  - `build_client(config)` → authenticated `Client`
  - `fetch_all_nodes(client)` → paginated `list[Node]`
  - `fetch_node(client, node_id)` → single `Node` with full detail (metadata + tags)
  - `fetch_server_config(client)` → `ServerConfig` (orphan location)
  - `create_node(client, data: NodeCreate)` → `Node`
  - `update_node(client, node_id, data: NodeUpdate)` → `Node`
  - `delete_node(client, node_id)` → deleted ids
  - `get_or_create_tag(client, label)` → `Tag`

## Phase 4: DAG Cache (`cache.py`)

`InventoryCache` class (justified: long-lived mutable state).

```
nodes:        dict[str, Node]         # id → Node
children:     dict[str, list[str]]    # parent_id → [child_ids]
roots:        list[str]               # ids of nodes with no parent
search_index: list[tuple[str, str]]   # (path_string, node_id) — pre-built flat index
```

Methods:
- `build(nodes: list[Node])` — populate all structures from a flat node list
- `get_node(id)` → `Node`
- `get_children(id)` → `list[Node]`
- `get_path(id)` → `list[Node]` (root → node)
- `get_path_string(id)` → `"Home / Office / Bookshelf 2"`
- `search(query)` → `list[tuple[str, str]]` — case-insensitive substring, returns (path_string, node_id)

The search index is pre-built on `build()` so search is O(n) scan with no per-query tree traversal.

## Phase 5: Main Screen (`screens/main.py`)

Layout via Textual CSS — a horizontal 25/75 split:

- **Left pane (25%):** A self-contained box with a header `Static` and a `Tree` below it — the Containers sidebar; always has focus even when visually hidden
- **Right pane (75%):** A single container with a shared header `Static` (showing the selected node title), inside which the space is split left/right:
  - **Left half:** `ListView` (focusable=False) — node metadata (label, created, modified, tags)
  - **Right half:** `Markdown` — node description

Loading indicator:
- `active_operations: reactive[int]` — atomic counter, incremented on work start, decremented on complete
- `LoadingIndicator` visibility bound to `active_operations > 0`
- All background tasks increment/decrement via a context manager or helper

Sidebar hide/show:
- Toggle CSS class `.hidden` on the sidebar widget (never `display = False`)
- CSS handles `width: 0; overflow: hidden` with a 150ms transition

On cursor move: re-fetch node detail from API (`fetch_node`), update metadata and description panes.

## Phase 6: Keybindings

| Key       | Action                  | Notes                                                                 |
|:----------|:------------------------|:----------------------------------------------------------------------|
| N         | New Node                |                                                                       |
| M         | Move Node               |                                                                       |
| E         | Edit Node               |                                                                       |
| D         | Delete Node             |                                                                       |
| /         | Search                  |                                                                       |
| Space     | Toggle Container        | No-op if an item (non-container) is selected                          |
| ~ or `    | Toggle Sidebar          | Both keys do the same thing                                           |
| Q         | Quit                    | Graceful: wait for `active_operations == 0`, timeout ~5s              |
| ^C        | Quit                    | Works even in modals                                                  |
| F1        | Help                    | Works in modals; push HelpScreen                                      |
| F2        | Config                  | Works in modals; dismiss current modal first (may lose work)          |
| F5        | Refresh                 | Re-fetch DAG from server                                              |
| Enter     | Select / Submit         | In modal: acts on focused widget, not left pane                       |
| Up / Down | Cursor Navigation       | In modal: acts on focused widget                                      |
| PgUp/PgDn | Scroll Description      | Scrolls the description `Markdown` widget                             |

Graceful quit: set a quit sentinel, wait for `active_operations == 0` (or timeout), show ConfirmModal "Wait / Exit Now".

## Phase 7: Modals (`modals/`)

### BaseModal (`base.py`)
- Esc: dismiss with no action
- F1: push HelpScreen
- F2: dismiss self, then open ConfigModal

### PickerModal (`picker.py`)
Used for both **[/] Search** and **[M] Move**.

- Title: "Search" or "Move"
- `Input` field + `OptionList` showing path strings from cache
- Typing in Input filters the list via cache `search()`
- **Key intercept:** Down-arrow at modal level scrolls OptionList without leaving Input focus, so the user can type → arrow down → Enter without tabbing
- Rich inline markup: dim ancestor segments, bold the matching keyword
- For Move: containers only; first entry is `<No Parent>` → maps to `None`

### NodeEditModal (`node_edit.py`)
Used for both **[N] New** and **[E] Edit**.

- Fields: Name (`Input`), Is Container (`Checkbox`), Parent (`Input` + picker button), Tags (`Input`, comma-separated), Description (`TextArea`, grows + scrollable up to a max)
- Cancel / Submit buttons
- Parent defaults to: selected container, or parent of selected item
- Clicking Parent field opens PickerModal (containers only, with `<No Parent>`)
- On submit: split tags by comma, call `get_or_create_tag()` for each, send tag ids to API
- API 4xx errors: show MessageModal; keep NodeEditModal open so the user can correct

### ConfirmModal (`confirm.py`)
- Message area (grows to fit), Cancel (left) / Ok (right)
- Default focus: Cancel; can be constructed with `default_affirmative=True`
- Esc = Cancel, Enter on focused button = that button's action

### MessageModal (`message.py`)
- Message area (grows), single Ok button (right)
- Esc or Enter dismisses

### ConfigModal (`settings.py`)
- Inputs: URL, Token, Username, Password
- When Token field has a value: Username and Password are disabled and show `*disabled*`; their stored values are retained
- On submit: `save_config()`, rebuild API client, reload DAG
- Reloading DAG after config update will surface auth/connection errors naturally

## Phase 8: Help Screen (`screens/help.py`)

- `Screen.push()` — covers the entire screen
- Displays a Markdown help file (placeholder content for now)
- Dismiss with Esc

## Phase 9: Startup Flow

1. Load config from `platformdirs` path
2. If no config file exists → open ConfigModal immediately
3. Build API client (`build_client(config)`)
   - If token provided: use directly
   - If username+password: call login endpoint to get bearer token (stored in memory only, not persisted)
4. Fetch `ServerConfig` (orphan location)
   - On error (auth failure, connection error): show dialog with "Exit" / "Configuration" choices
5. Increment `active_operations`, fetch all nodes (paginated), decrement on complete
6. Build `InventoryCache` from fetched nodes
7. Populate Tree from `cache.roots`

## Phase 10: Node Operations

### Move
1. Open PickerModal (containers only, `<No Parent>` as first option)
2. On selection: increment `active_operations`
3. Note currently selected node id
4. Call `update_node` with new `parent_id`
5. Re-fetch full DAG, rebuild cache
6. Restore previous expansion state; move cursor to the moved node (expanding ancestors as needed)
7. Decrement `active_operations`

### Delete Item
1. Show ConfirmModal: "Delete `<label>`? This cannot be undone."
2. On confirm: `delete_node`, refresh tree

### Delete Container
1. Fetch server config for orphan location
2. Show ConfirmModal: "Delete `<label>`? Any items inside will be moved to `<orphan_location or 'root'>`."
3. On confirm: `delete_node`, refresh tree

## Phase 11: Thread Safety

- Textual's widget tree and reactive properties are not thread-safe for direct mutation from OS threads
- All background data processing hands results back to the main thread via `self.call_from_thread()` or by posting a Textual `Message`
- `active_operations` counter mutations go through the Textual event loop (not raw threads) wherever possible
- Use `blanket` to write deterministic tests when race conditions are found (do not exhaustively audit upfront)

## Phase 12: Testing

- Unit tests for `cache.py` — pure logic, no I/O
- Unit tests for `config.py` — read/write with temp dirs (covers `load_config`/`save_config`)
- Unit tests for `service.py` — mock httpx responses
- `blanket` tests added reactively when race conditions are identified
