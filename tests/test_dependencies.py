import pytest

from delamain_backend.dependencies import assert_litellm_version_allowed
from delamain_backend.errors import DependencyBlockedError


@pytest.mark.parametrize("version", ["1.82.7", "1.82.8"])
def test_known_bad_litellm_versions_are_blocked(version):
    with pytest.raises(DependencyBlockedError):
        assert_litellm_version_allowed(version)


def test_known_good_litellm_version_is_allowed():
    assert assert_litellm_version_allowed("1.83.8") == "1.83.8"
