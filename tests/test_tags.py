import pytest

from binctl_tui.tags import normalize_tag_names


def test_normalizes_unicode_separators_and_duplicates() -> None:
    assert normalize_tag_names(
        "Électronique & Outils, 工具 箱, électronique-outils, ,  cables---usb",
    ) == [
        "électronique-outils",
        "工具-箱",
        "cables-usb",
    ]


def test_rejects_nonempty_tag_that_has_no_letters_or_numbers() -> None:
    with pytest.raises(ValueError, match="contains no letters or numbers"):
        normalize_tag_names("tools, !!!")
