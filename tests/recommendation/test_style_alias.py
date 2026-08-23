"""妝容映射:styleId 與顯示名稱互轉。"""
import pytest

from recommendation.style_alias import (
    STYLE_ALIAS,
    UnknownMakeupStyle,
    normalize_style,
    style_id_of,
)


def test_all_seven_styles_present():
    assert len(STYLE_ALIAS) == 7


@pytest.mark.parametrize("style_id,name", list(STYLE_ALIAS.items()))
def test_normalize_accepts_style_id(style_id, name):
    assert normalize_style(style_id) == name


@pytest.mark.parametrize("name", list(STYLE_ALIAS.values()))
def test_normalize_accepts_display_name(name):
    assert normalize_style(name) == name


def test_normalize_is_case_insensitive_on_id():
    assert normalize_style("richgirl") == "千金"
    assert normalize_style("RICHGIRL") == "千金"


@pytest.mark.parametrize("bad", ["", "  ", "notAStyle", "richGril", None])
def test_unknown_style_raises(bad):
    with pytest.raises(UnknownMakeupStyle):
        normalize_style(bad)


def test_round_trip_id_name():
    assert style_id_of("千金") == "richGirl"
