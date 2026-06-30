import os
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")

FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "Kommunie <hello@kommunie.com>")


def send_waitlist_confirmation(to_email: str, name: str | None = None):
    """Send a waitlist confirmation email via Resend. Fails silently if
    RESEND_API_KEY is not configured (useful for local dev)."""
    if not resend.api_key:
        return None

    greeting = f"Hi {name}," if name else "Hi there,"

    html = f"""
    <div style="font-family: 'IBM Plex Mono', monospace; background:#0f0f0f; color:#f5f5f5; padding:32px;">
      <h2 style="color:#b8ff57;">You're on the list.</h2>
      <p>{greeting}</p>
      <p>Thanks for joining the Kommunie waitlist. We'll be in touch soon
      with next steps to activate your account for R300 — one-time, no
      subscription.</p>
      <p style="color:#6b6b6b;">Kommunie — technology made for real people.</p>
    </div>
    """

    return resend.Emails.send({
        "from": FROM_EMAIL,
        "to": to_email,
        "subject": "You're on the Kommunie waitlist",
        "html": html,
    })
