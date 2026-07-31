import asyncio

import httpx
from binctl_client import Client
from binctl_client.models.node_create import NodeCreate

from binctl_tui.service import create_node, fetch_all_nodes, fetch_all_tags


def client_for(handler) -> Client:
    client = Client(
        base_url="https://inventory.example",
        token="test-token",
        raise_on_unexpected_status=True,
    )
    client.set_async_httpx_client(
        httpx.AsyncClient(
            base_url="https://inventory.example",
            transport=httpx.MockTransport(handler),
        ),
    )

    return client


def node_payload(node_id: str) -> dict[str, object]:
    return {
        "id": node_id,
        "label": node_id,
        "is_container": False,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "parent_id": None,
    }


def test_fetches_every_node_and_tag_page() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        offset = int(request.url.params.get("offset", 0))
        if request.url.path == "/v1/nodes":
            items = [node_payload("one")] if offset == 0 else [node_payload("two")]
            return httpx.Response(
                200,
                json={"total": 2, "limit": 1, "offset": offset, "items": items},
            )
        if request.url.path == "/v1/tags":
            items = [
                {
                    "id": "tag",
                    "name": "tools",
                    "created_at": "2026-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                },
            ]
            return httpx.Response(
                200,
                json={"total": 1, "limit": 1, "offset": offset, "items": items},
            )
        raise AssertionError(request.url.path)

    client = client_for(handler)
    nodes = asyncio.run(fetch_all_nodes(client))
    tags = asyncio.run(fetch_all_tags(client))

    assert [node.id for node in nodes] == ["one", "two"]
    assert [tag.name for tag in tags] == ["tools"]
    asyncio.run(client.get_async_httpx_client().aclose())


def test_creates_node_with_generated_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1/nodes"
        return httpx.Response(201, json=node_payload("created"))

    client = client_for(handler)
    created = asyncio.run(create_node(client, NodeCreate(label="Created")))

    assert created.id == "created"
    asyncio.run(client.get_async_httpx_client().aclose())
