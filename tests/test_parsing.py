import json

import pytest

from newsbot.parsing import coerce_index, extract_json


def test_extract_json_plain():
    assert extract_json('[{"a": 1}]') == [{"a": 1}]


def test_extract_json_fenced():
    assert extract_json('```json\n[1, 2, 3]\n```') == [1, 2, 3]


def test_extract_json_bare_fence():
    assert extract_json('```\n{"x": true}\n```') == {"x": True}


def test_extract_json_wrapped_in_prose():
    assert extract_json('Here are the items: [{"i": 0}] hope that helps') == [{"i": 0}]


def test_extract_json_raises_when_absent():
    with pytest.raises(json.JSONDecodeError):
        extract_json("no json here")


@pytest.mark.parametrize("value,expected", [
    (0, 0),
    (3, 3),
    ("5", 5),
    ("[2]", 2),
    ("item 7", 7),
    (True, None),
    (False, None),
    ("none", None),
])
def test_coerce_index(value, expected):
    assert coerce_index(value) == expected
