"""Tag-name normalization shared by editing and application workflows."""

from __future__ import annotations

import unicodedata


def normalize_tag_name(value: str) -> str:
    """Normalize arbitrary user input to a stable, Unicode-safe tag name."""
    normalized = unicodedata.normalize("NFC", value).lower()
    characters: list[str] = []
    separator_pending = False

    for character in normalized:
        if character.isalnum():
            if separator_pending and characters:
                characters.append("-")
            characters.append(character)
            separator_pending = False
        else:
            separator_pending = True

    return "".join(characters)


def normalize_tag_names(value: str) -> list[str]:
    """Split, normalize, validate, and de-duplicate comma-separated tag names."""
    names: list[str] = []
    seen: set[str] = set()

    for raw_name in value.split(","):
        name = normalize_tag_name(raw_name)

        if not raw_name.strip():
            continue
        if not name:
            raise ValueError(f"Tag {raw_name!r} contains no letters or numbers")
        if name not in seen:
            names.append(name)
            seen.add(name)

    return names

