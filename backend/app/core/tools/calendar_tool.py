from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
import resend

resend.api_key = os.environ.get("RESEND_API_KEY", "")
FROM_EMAIL = os.environ.get("RESEND_FROM_EMAIL", "Kommune <hello@kommune.app>")


def _format_ics_datetime(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%SZ")


def build_ics(
    *,
    title: str,
    description: str,
    location: str,
    start: datetime,
    duration_minutes: int = 30,
) -> str:
    """Build an iCalendar (.ics) file content for a single event.
    Works with Google Calendar, Apple Calendar, and Outlook."""
    end = start + timedelta(minutes=duration_minutes)
    uid = str(uuid.uuid4())
    now = datetime.utcnow()

    ics = "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Kommune//Legal Agent//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_format_ics_datetime(now)}",
            f"DTSTART:{_format_ics_datetime(start)}",
            f"DTEND:{_format_ics_datetime(end)}",
            f"SUMMARY:{title}",
            f"DESCRIPTION:{description}",
            f"LOCATION:{location}",
            "STATUS:CONFIRMED",
            "END:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    )
    return ics


def send_calendar_invite(
    *,
    to_email: str,
    title: str,
    description: str,
    location: str,
    start: datetime,
    duration_minutes: int = 30,
) -> dict:
    """Send a calendar invite (.ics attachment) to the user via email.

    Works without any calendar provider OAuth — the user's email client
    (Gmail, Apple Mail, Outlook) will offer to add it to their calendar.
    """
    if not resend.api_key:
        return {"status": "error", "error": "RESEND_API_KEY not configured"}

    ics_content = build_ics(
        title=title,
        description=description,
        location=location,
        start=start,
        duration_minutes=duration_minutes,
    )

    import base64

    ics_b64 = base64.b64encode(ics_content.encode("utf-8")).decode("utf-8")

    try:
        result = resend.Emails.send(
            {
                "from": FROM_EMAIL,
                "to": to_email,
                "subject": f"Appointment: {title}",
                "html": (
                    f"<div style='font-family: sans-serif; line-height: 1.6;'>"
                    f"<p>Your appointment has been scheduled:</p>"
                    f"<p><strong>{title}</strong><br>"
                    f"{start.strftime('%A, %d %B %Y at %H:%M')} (UTC)<br>"
                    f"{location}</p>"
                    f"<p>{description}</p>"
                    f"<p>Open the attached file to add this to your calendar.</p>"
                    f"</div>"
                ),
                "attachments": [
                    {
                        "filename": "appointment.ics",
                        "content": ics_b64,
                    }
                ],
            }
        )
        return {"status": "sent", "result": result}
    except Exception as e:
        return {"status": "error", "error": str(e)}
