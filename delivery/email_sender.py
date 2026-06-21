"""
Send the daily NewsFlow episode (Drive link + review report) via Resend.
Reads RESEND_API_KEY from environment. Sends from hello@newsflow.ink.
"""
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=False)

import structlog

log = structlog.get_logger(__name__)

FROM = "NewsFlow <hello@newsflow.ink>"


def _build_html(episode_metadata: dict, review_md: str | None, drive_link: str | None) -> str:
    title = episode_metadata.get("title", "NewsFlow Daily")
    duration_sec = episode_metadata.get("duration_sec", 0)
    duration_min = duration_sec // 60
    article_count = episode_metadata.get("article_count", "?")
    run_date = episode_metadata.get("date", str(date.today()))

    segments_html = ""
    for seg in episode_metadata.get("segments", []):
        seg_title = seg.get("title", "")
        seg_priority = seg.get("priority", "")
        segments_html += f"<tr><td style='padding:4px 8px'>{seg_title}</td><td style='padding:4px 8px;color:#666'>{seg_priority}</td></tr>\n"

    listen_html = ""
    if drive_link:
        listen_html = f"""
<p style="margin:24px 0">
  <a href="{drive_link}" style="background:#1a73e8;color:#fff;padding:12px 24px;border-radius:4px;text-decoration:none;font-size:16px">
    Listen on Google Drive
  </a>
</p>"""
    else:
        listen_html = "<p style='color:#c00'>Episode audio not available — check pipeline logs.</p>"

    review_html = ""
    if review_md:
        review_html = f"""
<hr style="margin:32px 0">
<h2 style="color:#333">Quality Report</h2>
<pre style="background:#f5f5f5;padding:16px;border-radius:4px;font-size:13px;white-space:pre-wrap">{review_md}</pre>
"""

    return f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;max-width:700px;margin:0 auto;padding:24px;color:#222">
  <h1 style="color:#1a1a1a">NewsFlow — {run_date}</h1>
  <p style="font-size:16px">{title}</p>
  <table style="border-collapse:collapse;margin:16px 0">
    <tr>
      <td style="padding:4px 8px;font-weight:bold">Duration</td>
      <td style="padding:4px 8px">{duration_min} min</td>
    </tr>
    <tr>
      <td style="padding:4px 8px;font-weight:bold">Articles</td>
      <td style="padding:4px 8px">{article_count}</td>
    </tr>
  </table>
  {"<h2>Segments</h2><table style='border-collapse:collapse'>" + segments_html + "</table>" if segments_html else ""}
  {listen_html}
  {review_html}
</body>
</html>"""


def send_episode_email(
    recipient: str,
    mp3_path: Path,
    review_md_path: Path | None,
    episode_metadata: dict,
    drive_link: str | None = None,
) -> None:
    import resend

    api_key = os.environ.get("RESEND_API_KEY")
    if not api_key:
        raise RuntimeError("RESEND_API_KEY not set in .env")
    resend.api_key = api_key

    run_date = episode_metadata.get("date", str(date.today()))
    title = episode_metadata.get("title", "NewsFlow Daily")

    review_text: str | None = None
    if review_md_path and review_md_path.exists():
        review_text = review_md_path.read_text(encoding="utf-8")

    attachments = []
    if review_text and review_md_path:
        import base64
        attachments.append({
            "filename": "review_report.md",
            "content": base64.b64encode(review_text.encode()).decode(),
        })

    params: dict = {
        "from": FROM,
        "to": [recipient],
        "subject": f"NewsFlow {run_date} — {title}",
        "html": _build_html(episode_metadata, review_text, drive_link),
    }
    if attachments:
        params["attachments"] = attachments

    resend.Emails.send(params)
    log.info("email_sent", recipient=recipient, date=run_date, drive_link=drive_link)
