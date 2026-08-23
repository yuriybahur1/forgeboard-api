import pytest

from workstream.modules.auth.schemas import LoginRequest
from workstream.seed import DEMO_USER_EMAILS

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("email", DEMO_USER_EMAILS)
def test_demo_user_email_is_accepted_by_login_schema(email: str) -> None:
    request = LoginRequest(email=email, password="DemoPassword123!")

    assert str(request.email) == email
