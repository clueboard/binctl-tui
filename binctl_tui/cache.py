"""In-memory navigation and search structures for binctl node summaries."""

from __future__ import annotations

from binctl_client.models.node_child import NodeChild


class InventoryCache:
    """Long-lived mutable cache built from a flat node-list response."""

    def __init__(self) -> None:
        self.nodes: dict[str, NodeChild] = {}
        self.children: dict[str, list[str]] = {}
        self.roots: list[str] = []
        self.search_index: list[tuple[str, str]] = []

    def build(self, nodes: list[NodeChild]) -> None:
        """Rebuild every lookup and the flattened path search index."""
        self.nodes = {node.id: node for node in nodes}
        self.children = {node_id: [] for node_id in self.nodes}
        self.roots = []
        self.search_index = []

        for node in nodes:
            parent_id = node.parent_id if isinstance(node.parent_id, str) else None

            if parent_id and parent_id in self.nodes:
                self.children[parent_id].append(node.id)
            else:
                self.roots.append(node.id)

        for node_id in self.nodes:
            self.search_index.append((self.get_path_string(node_id), node_id))

    def get_node(self, node_id: str) -> NodeChild:
        """Return a cached node summary."""
        node = self.nodes[node_id]

        return node

    def get_children(self, node_id: str) -> list[NodeChild]:
        """Return direct child summaries in server response order."""
        children = [self.nodes[child_id] for child_id in self.children.get(node_id, [])]

        return children

    def get_path(self, node_id: str) -> list[NodeChild]:
        """Return the root-to-node lineage, tolerating malformed cyclic input."""
        path: list[NodeChild] = []
        seen: set[str] = set()
        current_id: str | None = node_id

        while current_id and current_id not in seen and current_id in self.nodes:
            node = self.nodes[current_id]
            path.append(node)
            seen.add(current_id)
            current_id = node.parent_id if isinstance(node.parent_id, str) else None

        path.reverse()

        return path

    def get_path_string(self, node_id: str) -> str:
        """Return a readable slash-separated lineage."""
        path = self.get_path(node_id)
        path_string = " / ".join(node.label for node in path)

        return path_string

    def search(self, query: str) -> list[tuple[str, str]]:
        """Find paths containing a case-insensitive literal substring."""
        needle = query.casefold()
        results = [
            entry
            for entry in self.search_index
            if needle in entry[0].casefold()
        ]

        return results

