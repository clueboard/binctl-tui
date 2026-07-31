"""Async adapter around the generated binctl API client."""

from __future__ import annotations

from typing import TypeVar

from binctl_client import Client
from binctl_client.api.config import get_config
from binctl_client.api.nodes import (
    delete_node_endpoint,
    get_node_detail,
    get_nodes_list,
    patch_node_update,
    post_node_create,
)
from binctl_client.api.tags import get_tags_list, post_tag_create
from binctl_client.models.delete_node_endpoint_response_200 import (
    DeleteNodeEndpointResponse200,
)
from binctl_client.models.node import Node
from binctl_client.models.node_child import NodeChild
from binctl_client.models.node_create import NodeCreate
from binctl_client.models.node_update import NodeUpdate
from binctl_client.models.server_config import ServerConfig
from binctl_client.models.tag import Tag
from binctl_client.models.tag_create import TagCreate
from binctl_client.types import Response

PAGE_SIZE = 100
T = TypeVar("T")


def build_client(config: dict[str, str]) -> Client:
    """Build an authenticated client from a token or username/password."""
    url = config.get("url", "").strip().rstrip("/")
    token = config.get("token", "").strip()
    username = config.get("username", "").strip()
    password = config.get("password", "")

    if not url:
        raise ValueError("A binctl server URL is required")

    if token:
        client = Client(base_url=url, token=token, raise_on_unexpected_status=True)
    else:
        if not username or not password:
            raise ValueError("Provide a token or both username and password")
        client = Client(
            base_url=url,
            username=username,
            password=password,
            raise_on_unexpected_status=True,
        )

    return client


def _parsed(response: Response[T], operation: str) -> T:
    result = response.parsed

    if result is None:
        raise RuntimeError(f"{operation} returned no result")

    return result


async def fetch_all_nodes(client: Client) -> list[NodeChild]:
    """Fetch every paginated node summary."""
    nodes: list[NodeChild] = []
    offset = 0

    while True:
        response = await get_nodes_list.asyncio_detailed(
            client=client,
            limit=PAGE_SIZE,
            offset=offset,
        )
        page = _parsed(response, "Listing nodes")
        nodes.extend(page.items)
        offset += len(page.items)

        if offset >= page.total or not page.items:
            break

    return nodes


async def fetch_node(client: Client, node_id: str) -> Node:
    """Fetch full metadata for one node."""
    response = await get_node_detail.asyncio_detailed(node_id, client=client)
    node = _parsed(response, "Fetching node")

    if not isinstance(node, Node):
        raise RuntimeError("Fetching node returned an invalid result")

    return node


async def fetch_all_tags(client: Client) -> list[Tag]:
    """Fetch every paginated tag."""
    tags: list[Tag] = []
    offset = 0

    while True:
        response = await get_tags_list.asyncio_detailed(
            client=client,
            limit=PAGE_SIZE,
            offset=offset,
        )
        page = _parsed(response, "Listing tags")
        tags.extend(page.items)
        offset += len(page.items)

        if offset >= page.total or not page.items:
            break

    return tags


async def fetch_server_config(client: Client) -> ServerConfig:
    """Fetch server settings used by destructive-operation messaging."""
    response = await get_config.asyncio_detailed(client=client)
    config = _parsed(response, "Fetching server configuration")

    return config


async def create_node(client: Client, data: NodeCreate) -> Node:
    """Create a node."""
    response = await post_node_create.asyncio_detailed(client=client, body=data)
    node = _parsed(response, "Creating node")

    return node


async def update_node(client: Client, node_id: str, data: NodeUpdate) -> Node:
    """Update a node."""
    response = await patch_node_update.asyncio_detailed(
        node_id,
        client=client,
        body=data,
    )
    node = _parsed(response, "Updating node")

    if not isinstance(node, Node):
        raise RuntimeError("Updating node returned an invalid result")

    return node


async def delete_node(
    client: Client,
    node_id: str,
) -> DeleteNodeEndpointResponse200:
    """Delete a node and return server-reported affected IDs."""
    response = await delete_node_endpoint.asyncio_detailed(node_id, client=client)
    result = _parsed(response, "Deleting node")

    if not isinstance(result, DeleteNodeEndpointResponse200):
        raise RuntimeError("Deleting node returned an invalid result")

    return result


async def get_or_create_tag(
    client: Client,
    tag_index: dict[str, Tag],
    name: str,
) -> Tag:
    """Resolve a normalized tag name, creating it only when absent."""
    tag = tag_index.get(name)

    if tag is not None:
        return tag

    response = await post_tag_create.asyncio_detailed(
        client=client,
        body=TagCreate(name=name),
    )
    tag = _parsed(response, "Creating tag")
    tag_index[name] = tag

    return tag

