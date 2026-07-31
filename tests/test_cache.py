from datetime import datetime

from binctl_client.models.node_child import NodeChild

from binctl_tui.cache import InventoryCache


def node(
    node_id: str,
    label: str,
    parent_id: str | None = None,
    is_container: bool = True,
) -> NodeChild:
    now = datetime(2026, 1, 1)

    return NodeChild(
        id=node_id,
        label=label,
        is_container=is_container,
        created_at=now,
        updated_at=now,
        parent_id=parent_id,
    )


def test_builds_navigation_paths_and_search_index() -> None:
    cache = InventoryCache()
    cache.build(
        [
            node("home", "Home"),
            node("office", "Office", "home"),
            node("cable", "USB Cable", "office", False),
            node("orphan", "Orphan", "missing"),
        ],
    )

    assert [item.id for item in cache.get_children("home")] == ["office"]
    assert [item.id for item in cache.get_path("cable")] == [
        "home",
        "office",
        "cable",
    ]
    assert cache.get_path_string("cable") == "Home / Office / USB Cable"
    assert cache.roots == ["home", "orphan"]
    assert cache.search("OFFICE") == [
        ("Home / Office", "office"),
        ("Home / Office / USB Cable", "cable"),
    ]


def test_tolerates_cyclic_data_from_an_invalid_server() -> None:
    cache = InventoryCache()
    cache.build([node("first", "First", "second"), node("second", "Second", "first")])

    assert [item.id for item in cache.get_path("first")] == ["second", "first"]
