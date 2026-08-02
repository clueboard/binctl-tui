"""Module entry point."""

from __future__ import annotations

import argparse
from importlib.metadata import version

from . import config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Terminal interface for binctl.")
    parser.add_argument("-v", "--version", action="version", version=f"%(prog)s {version('binctl-tui')}")
    parser.add_argument("--show-config", action="store_true", help="show the configuration file location and current default profile")
    return parser


def _show_config() -> None:
    path = config.config_path()
    values = config.load_config()
    print(f"Configuration file: {path}")
    print(f"Status: {'found' if path.exists() else 'not found'}")

    if not values:
        print("Default profile: not configured")
        return

    authentication = "token" if values.get("token") else "username/password" if values.get("username") or values.get("password") else "not configured"
    print("Default profile:")
    print(f"  URL: {values.get('url') or '(not set)'}")
    print(f"  Theme: {values.get('theme') or 'textual-light (default)'}")
    print(f"  Authentication: {authentication}")
    if values.get("token"):
        print("  Token: (set, hidden)")
    else:
        print(f"  Username: {values.get('username') or '(not set)'}")
        print(f"  Password: {'(set, hidden)' if values.get('password') else '(not set)'}")


def main() -> None:
    """Run the Textual application."""
    arguments = _parser().parse_args()
    if arguments.show_config:
        _show_config()
        return

    from .app import BinctlApp

    BinctlApp().run()


if __name__ == "__main__":
    main()
