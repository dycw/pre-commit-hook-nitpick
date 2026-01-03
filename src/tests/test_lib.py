from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pytest import mark, param
from utilities.iterables import one

if TYPE_CHECKING:
    from conformalize.types import StrDict


from conformalize.lib import get_partial_dict, is_partial_dict


class TestGetPartialDict:
    def test_main(self) -> None:
        url = "https://github.com/owner/repo"
        repos_list = [
            {"repo": url, "rev": "v6.0.0", "hooks": [{"id": "id1"}, {"id": "id2"}]}
        ]
        result = get_partial_dict(repos_list, {"repo": url})
        assert result == one(repos_list)


class TestIsPartialDict:
    @mark.parametrize(
        ("obj", "dict_", "expected"),
        [
            param(None, {}, False),
            param({}, {}, True),
            param({}, {"a": 1}, True),
            param({"a": 1}, {}, False),
            param({"a": 1}, {"a": 1}, True),
            param({"a": 1}, {"a": 2}, False),
            param({"a": 1, "b": 2}, {"a": 1}, False),
            param({"a": 1}, {"a": 1, "b": 2}, True),
            param({"a": 1, "b": 2}, {"a": 1, "b": 2}, True),
            param({"a": 1, "b": 2}, {"a": 1, "b": 3}, False),
            param({"a": 1, "b": {}}, {"a": 1, "b": {}}, True),
            param({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {}}, False),
            param({"a": 1, "b": {}}, {"a": 1, "b": {"c": 2}}, True),
            param({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 2}}, True),
            param({"a": 1, "b": {"c": 2}}, {"a": 1, "b": {"c": 3}}, False),
        ],
    )
    def test_main(self, *, obj: Any, dict_: StrDict, expected: bool) -> None:
        assert is_partial_dict(obj, dict_) is expected
