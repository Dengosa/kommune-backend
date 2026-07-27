from __future__ import annotations

from datetime import date


def draft_letter(
    *,
    recipient_name: str,
    recipient_address: str,
    subject: str,
    body: str,
    sender_name: str | None = None,
) -> dict:
    """Format a formal letter document from agent-provided content.

    This does not send or mail anything - it produces a properly formatted
    letter as text, which the agent shows to the user (e.g. to print, attach
    to an email, or take to Home Affairs in person). No external API call is
    needed, so this can never fail due to a missing key/config - it's a pure
    formatting operation.
    """
    today = date.today().strftime("%d %B %Y")
    sender_line = f"{sender_name}\n" if sender_name else ""

    formatted = (
        f"{today}\n\n"
        f"{recipient_name}\n"
        f"{recipient_address}\n\n"
        f"RE: {subject}\n\n"
        f"Dear {recipient_name},\n\n"
        f"{body}\n\n"
        f"Yours sincerely,\n\n"
        f"{sender_line}"
    ).strip()

    return {"status": "drafted", "letter_text": formatted, "subject": subject}
