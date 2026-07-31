# binctl-tui

This is a [Textual](https://textual.textualize.io/) TUI frontend for
[binctl](https://github.com/clueboard/binctl).

## Running

Install dependencies and start the interface with:

```sh
uv sync
uv run binctl-tui
```

On first run, enter the binctl server URL and either a bearer token or username
and password in the configuration dialog. Configuration is stored securely in
the platform-specific `binctl-tui` configuration directory.

## Testing

Run the unit suite with:

```sh
uv run pytest -q
```
