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
V1 stores credentials in this TOML file rather than integrating with the OS keyring. On POSIX, create and enforce `0700` permissions on the config directory and `0600` on `config.toml`. Save atomically so a partial write cannot expose or corrupt credentials. Never include credential values in logs, errors, or diagnostic output.

No other state is persisted to disk. The DAG, expansion state, and search index are rebuilt from the API on each startup.

### In-memory (runtime)

| What | Lives in | Notes |
|:-----|:---------|:------|
| Loaded config | Module-level singleton in `config.py` | Loaded once at startup via `load_config()`; `save_config()` updates both disk and the in-memory singleton; all other modules import from `config.py` to read it |
| API client | `app.py` app instance | Rebuilt on config change or auth refresh |
| Bearer token | `app.py` app instance | Never written to disk when obtained via username+password login |
| Server config (orphan location) | `app.py` app instance | Fetched once at startup, refreshed on F5 |
| DAG + search index | `InventoryCache` (cache.py) | Rebuilt from API on startup and after any mutating operation |
| Tag index | `app.py` app instance (`dict[str, Tag]`) | Normalized tag name → tag; loaded at startup and used for autocomplete and tag-ID resolution |
| Tree expansion state | `app.py` app instance (`dict[str, bool]`) | Preserved across DAG rebuilds so the UI doesn't jolt |
| Node detail widgets | `MainScreen` widget cache (`dict[str, NodeDetailWidget]`) | Created lazily after selection settles; hidden when inactive and unmounted after a last-access TTL |
| Active operations counter | `MainScreen` reactive | Drives `LoadingIndicator` visibility |



- Add 'binctl-client', `textual`, `platformdirs`, `tomli-w` to `pyproject.toml`
- Create package skeleton with `__main__.py` entry point
- Create stub `app.py` that launches with `textual run`

## Phase 2: Config Module (`config.py`)

- Use `platformdirs.user_config_dir("binctl-tui")` for config path
- Store as TOML: `config.toml` with `[profiles.default]` section (future-proof for multiple profiles)
- Fields per profile: `url`, `token`, `username`, `password`
- Functions: `load_config(profile="default")`, `save_config(data, profile="default")`
- On POSIX, create and enforce `0700` for the config directory and `0600` for the file; `save_config()` writes atomically

## Phase 3: Service Layer (`service.py`)

Wraps binctl-client API functions. All API operations after client construction use the generated client's async functions and never block the main thread.

Authentication during `build_client()` is intentionally synchronous when the user provides a username and password: `binctl-client` obtains the bearer token while constructing its `Client`. This may briefly block during startup or after a configuration change, which is acceptable for V1 and avoids duplicating the client's authentication implementation.

- Handles **pagination** for `get_nodes_list` (loop until `offset + len(items) >= total`)
- Handles **auth**: if token provided use directly; otherwise construct the client with username/password so it synchronously obtains a bearer token; surface errors to caller
- Functions:
  - `build_client(config)` → authenticated `Client`
  - `fetch_all_nodes(client)` → paginated `list[NodeChild]` summaries
  - `fetch_node(client, node_id)` → single `Node` with full detail (metadata + tags)
  - `fetch_all_tags(client)` → paginated `list[Tag]`
  - `fetch_server_config(client)` → `ServerConfig` (orphan location)
  - `create_node(client, data: NodeCreate)` → `Node`
  - `update_node(client, node_id, data: NodeUpdate)` → `Node`
  - `delete_node(client, node_id)` → deleted ids
  - `get_or_create_tag(client, tag_index, name)` → `Tag`, adding newly created tags to the index

## Phase 4: DAG Cache (`cache.py`)

`InventoryCache` class (justified: long-lived mutable state).

```
nodes:        dict[str, NodeChild]    # id → paginated node-list summary
children:     dict[str, list[str]]    # parent_id → [child_ids]
roots:        list[str]               # ids of nodes with no parent
search_index: list[tuple[str, str]]   # (path_string, node_id) — pre-built flat index
```

Methods:
- `build(nodes: list[NodeChild])` — populate all structures from a flat node-list response
- `get_node(id)` → `NodeChild`
- `get_children(id)` → `list[NodeChild]`
- `get_path(id)` → `list[NodeChild]` (root → node)
- `get_path_string(id)` → `"Home / Office / Bookshelf 2"`
- `search(query)` → `list[tuple[str, str]]` — case-insensitive substring, returns (path_string, node_id)

The cache stores only `NodeChild` summaries from `fetch_all_nodes()`; it never eagerly fetches full `Node` objects. The search index is pre-built on `build()` so search is O(n) scan with no per-query tree traversal.

## Phase 5: Main Screen (`screens/main.py`)

Layout via Textual CSS — a horizontal 25/75 split:

- **Left pane (25%):** A self-contained box with a header `Static` and a `Tree` below it — the Containers sidebar; always has focus even when visually hidden
- **Right pane (75%):** A detail-widget host with a shared header `Static` (showing the selected node title). The visible node detail widget is split left/right:
  - **Left half:** `ListView` (focusable=False) — node metadata (label, created, modified, tags)
  - **Right half:** `Markdown` — node description

Loading indicator:
- `active_operations: reactive[int]` — atomic counter, incremented on work start, decremented on complete
- `LoadingIndicator` visibility bound to `active_operations > 0`
- All background tasks increment/decrement via a context manager or helper

Sidebar hide/show:
- Toggle CSS class `.hidden` on the sidebar widget (never `display = False`)
- CSS handles `width: 0; overflow: hidden` with a 150ms transition

Detail widgets:
- Key widgets by node ID. On selection change, hide the outgoing widget and reset a 250ms selection debounce.
- Only after the selected node remains unchanged for the full debounce period, show its cached widget or create it and fetch its full `Node` detail from the API (`fetch_node`). This is the only place full nodes are fetched.
- A detail response updates only the widget keyed by its node ID. It is shown only when that node remains selected, so late responses populate their own hidden widget instead of replacing the current display.
- Keep inactive widgets hidden and unmount them after a last-access TTL. Rebuilding the DAG invalidates detail widgets and restarts the debounce for the current selection.

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
| ^C        | Quit / Hard Quit         | Works even in modals; graceful first press, unsafe immediate exit during shutdown |
| F1        | Help                    | Works in modals; push HelpScreen                                      |
| F2        | Config                  | Works in modals; dismiss current modal first (may lose work)          |
| F5        | Refresh                 | Re-fetch DAG and tag index from server                                |
| Enter     | Select / Submit         | In modal: acts on focused widget, not left pane                       |
| Up / Down | Cursor Navigation       | In modal: acts on focused widget                                      |
| PgUp/PgDn | Scroll Description      | Scrolls the description `Markdown` widget                             |

Graceful quit: set a shutdown sentinel, wait for `active_operations == 0` (or timeout), then show ConfirmModal "Wait / Exit Now". `Q` and the first `^C` initiate this graceful path. A subsequent `^C` while shutdown is in progress immediately terminates the process without waiting for active operations.

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
- Tags autocomplete from the in-memory tag index and are normalized as the user types or pastes:
  1. Normalize Unicode text to NFC.
  2. Convert letters to lowercase with `str.lower()`.
  3. Preserve Unicode letters and numbers; turn every run of whitespace, punctuation, symbols, and other separators into one hyphen.
  4. Strip leading and trailing hyphens.
  5. Ignore empty comma-separated entries; reject a non-empty entry that normalizes to an empty tag; deduplicate normalized tags.
- On submit: resolve normalized names through the tag index, call `get_or_create_tag()` only for missing names, send the resulting tag IDs to the API, then use the shared mutation lifecycle below
- Disable Cancel and Submit while tag resolution, the create/update request, and its refresh are in progress
- API or tag-resolution errors: show MessageModal; keep NodeEditModal open with its draft intact so the user can correct it

### ConfirmModal (`confirm.py`)
- Message area (grows to fit), Cancel (left) / Ok (right)
- Default focus: Cancel; can be constructed with `default_affirmative=True`
- Esc = Cancel, Enter on focused button = that button's action

### MessageModal (`message.py`)
- Message area (grows), single Ok button (right)
- Esc or Enter dismisses

### ConfigModal (`settings.py`)
- Inputs: URL, Token, Username, Password
- Password uses masked input
- When Token field has a value: Username and Password are disabled and show `*disabled*`; their stored values are retained
- On submit: `save_config()`, rebuild API client, reload the DAG and tag index
- Reloading after config update will surface auth/connection errors naturally

## Phase 8: Help Screen (`screens/help.py`)

- `Screen.push()` — covers the entire screen
- Displays a Markdown help file (placeholder content for now)
- Dismiss with Esc

## Phase 9: Startup Flow

1. Load config from `platformdirs` path
2. If no config file exists → open ConfigModal immediately
3. Build API client (`build_client(config)`)
   - If token provided: use directly
   - If username+password: synchronously obtain a bearer token during client construction; it is stored in memory only, not persisted
4. Fetch `ServerConfig` (orphan location)
   - On error (auth failure, connection error): show dialog with "Exit" / "Configuration" choices
5. Increment `active_operations`, fetch all nodes and tags (paginated), decrement on complete
6. Build `InventoryCache` from node summaries and the normalized tag index separately from tags
7. Populate Tree from `cache.roots`

## Phase 10: Node Operations

### Shared Mutation Lifecycle
Used by Create, Edit, and Move.

1. Disable the initiating modal's controls as applicable and increment `active_operations` once for the complete operation.
2. Perform the API mutation, retaining the returned node ID.
3. Re-fetch the full `NodeChild` summary DAG and rebuild `InventoryCache`; do not patch the cache from the full `Node` mutation response.
4. Restore expansion state, expand the target's ancestors as needed, rebuild the tree, and select the target node.
5. On successful refresh, dismiss the initiating modal. The selected node's 250ms detail debounce then loads its full detail widget.
6. On a tag-resolution or API error, preserve the old cache and keep NodeEditModal's draft open. Show MessageModal so the user can correct the error.
7. If the API mutation succeeds but the DAG refresh fails, dismiss NodeEditModal and show MessageModal: "Saved, but could not refresh the inventory. Press F5 to reload." Keep the old cache visible; do not offer a retry that could duplicate a Create.
8. Decrement `active_operations` and re-enable controls in `finally`.

### Create
1. Submit NodeEditModal using `create_node`.
2. Use the returned node ID as the shared lifecycle target so the newly created node is selected after the DAG refresh.

### Edit
1. Submit NodeEditModal using `update_node`.
2. Use the original node ID as the shared lifecycle target, including if its parent changed.

### Move
1. Open PickerModal (containers only, `<No Parent>` as first option)
2. On selection: call `update_node` with the new `parent_id`, using the selected node ID as the shared lifecycle target

### Delete Item
1. Before confirmation, capture the selected node's direct previous sibling ID and parent ID from `InventoryCache`. If the selected node is the first root, also capture its next root ID.
2. Show ConfirmModal: "Delete `<label>`? This cannot be undone."
3. On confirm, increment `active_operations`, call `delete_node`, and re-fetch the full `NodeChild` summary DAG.
4. Rebuild `InventoryCache` and restore expansion state.
5. Select the captured previous sibling if it remains in the refreshed cache; otherwise select the captured parent. When deleting the first root, select its captured next root if it remains instead. If no fallback remains, leave the tree unselected.
6. On an API or refresh error, keep the old cache and tree visible and show MessageModal.
7. Decrement `active_operations` in `finally`.

### Delete Container
1. Fetch server config for orphan location
2. Before confirmation, capture the selected node's direct previous sibling ID and parent ID from `InventoryCache`. If the selected node is the first root, also capture its next root ID.
3. Show ConfirmModal: "Delete `<label>`? Any items inside will be moved to `<orphan_location or 'root'>`."
4. On confirm, use the Delete Item lifecycle above.

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
