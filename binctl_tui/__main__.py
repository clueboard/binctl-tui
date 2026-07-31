"""Module entry point."""

from .app import BinctlApp


def main() -> None:
    """Run the Textual application."""
    BinctlApp().run()


if __name__ == "__main__":
    main()
