"""Full-screen placeholder help."""

from __future__ import annotations

from textual.binding import Binding
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Markdown


class HelpScreen(Screen[None]):
    """Display keyboard help."""

    BINDINGS = [Binding("escape", "dismiss_help", "Back", show=False)]

    def compose(self) -> ComposeResult:
        yield Markdown(
            """# binctl-tui

Navigate inventory with the arrow keys.

* **N** New node
* **M** Move node
* **E** Edit node
* **D** Delete node
* **/** Search
* **Space** Toggle a container
* **F2** Configure the server
* **F5** Refresh inventory
* **Q** Quit
""",
        )

    def action_dismiss_help(self) -> None:
        self.app.pop_screen()
