import pytest

from workstream.core.config import get_settings

pytestmark = pytest.mark.unit


def test_test_settings_do_not_inherit_local_compose_hosts() -> None:
    settings = get_settings()

    assert settings.environment == "test"
    assert "testserver" in settings.allowed_hosts
    assert settings.public_url == "http://testserver"
