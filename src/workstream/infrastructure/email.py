import smtplib
from email.message import EmailMessage

from jinja2 import Environment, PackageLoader, select_autoescape

from workstream.core.config import Settings

templates = Environment(
    loader=PackageLoader("workstream", "templates"), autoescape=select_autoescape()
)


def send_email(
    settings: Settings, template: str, recipient: str, subject: str, context: dict[str, str]
) -> None:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(templates.get_template(f"{template}.txt").render(**context))
    message.add_alternative(
        templates.get_template(f"{template}.html").render(**context), subtype="html"
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        smtp.send_message(message)
