from __future__ import annotations

import logging
import os
from typing import Protocol


logger = logging.getLogger("jobhunter.email")


class EmailSender(Protocol):
    """
    Swappable email-delivery boundary (see architecture principle #19:
    external services behind interfaces). Nothing in authentication/
    should import a concrete provider directly — only this protocol.
    """

    def send(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> None:
        ...


class LoggingEmailSender:
    """
    Development-only fallback. Logs the email instead of delivering it.

    This exists so the reset/signup flow is runnable and testable before
    a real provider is wired up — NOT because logging is an acceptable
    delivery mechanism. A reset token written to a log file is a reset
    token an attacker with log access can use. Before any real user
    relies on password reset, EMAIL_PROVIDER must point at a real
    implementation (SMTP, SES, Postmark, etc.) and this class must not
    be reachable in that configuration.
    """

    def send(
        self,
        to: str,
        subject: str,
        body: str,
    ) -> None:
        logger.warning(
            "EMAIL NOT SENT (no provider configured) to=%s subject=%r "
            "— wire up a real EmailSender via EMAIL_PROVIDER before "
            "relying on this in anything but local development.",
            to,
            subject,
        )


def get_email_sender() -> EmailSender:
    provider = os.getenv("EMAIL_PROVIDER", "").strip().lower()

    if not provider:
        return LoggingEmailSender()

    raise RuntimeError(
        f"EMAIL_PROVIDER={provider!r} is set but no implementation is "
        "registered for it. Add a concrete EmailSender for this provider "
        "in core/email.py and register it here before deploying with "
        "email-dependent features (signup confirmation, password reset) "
        "enabled for real users."
    )