from __future__ import annotations

import os
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "Kommune <hello@kommune.app>")


def send_agent_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    reply_to: str | None = None,
) -> dict:
    """Send an email drafted by an agent (e.g. Lex) on the user's behalf.

    `body` is plain text; converted to simple HTML for delivery. Returns a
    dict with status and the Resend response (or an error message).

    Fails closed in the sense that callers (agent tool-loop) should log the
    attempt to the Vault regardless of success/failure.
    """
    if not resend.api_key:
        return {"status": "error", "error": "RESEND_API_KEY not configured"}

    html_body = "<br>".join(body.split("\n"))

    try:
        result = resend.Emails.send(
            {
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": subject,
                "html": f"<div style='font-family: sans-serif; line-height: 1.6;'>{html_body}</div>",
                **({"reply_to": reply_to} if reply_to else {}),
            }
        )
        return {"status": "sent", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
