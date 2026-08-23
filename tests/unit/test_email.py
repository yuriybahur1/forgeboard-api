from email.message import EmailMessage

import pytest

from workstream.core.config import Settings
from workstream.infrastructure import email

pytestmark = pytest.mark.unit


def test_send_email_renders_action_message_and_sends_via_configured_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[EmailMessage] = []
    connections: list[tuple[str, int, int]] = []

    class SMTP:
        def __init__(self, host: str, port: int, timeout: int) -> None:
            connections.append((host, port, timeout))

        def __enter__(self) -> "SMTP":
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def send_message(self, message: EmailMessage) -> None:
            messages.append(message)

    monkeypatch.setattr(email.smtplib, "SMTP", SMTP)
    settings = Settings(
        _env_file=None,
        smtp_host="mail.example.com",
        smtp_port=2525,
        email_from="notifications@example.com",
    )
    action_url = "https://workstream.example/accept-invitation?token=secret"

    email.send_email(
        settings,
        "action",
        "invitee@example.com",
        "Workstream account action",
        {"action_url": action_url},
    )

    assert connections == [("mail.example.com", 2525, 10)]
    assert len(messages) == 1
    message = messages[0]
    assert message["From"] == "notifications@example.com"
    assert message["To"] == "invitee@example.com"
    assert message["Subject"] == "Workstream account action"
    assert action_url in message.get_body(preferencelist=("plain",)).get_content()
    assert action_url in message.get_body(preferencelist=("html",)).get_content()
