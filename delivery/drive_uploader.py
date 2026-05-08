"""
Upload episode MP3 to Google Drive and return a shareable link.
Uses a separate drive_token.json (drive.file scope only — cannot access existing files).
First run opens a browser for one-time OAuth consent.
"""
import os
from pathlib import Path

import structlog
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

log = structlog.get_logger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]
_FOLDER_NAME = "NewsFlow"


def _get_drive_service():
    creds_path = os.environ.get("GMAIL_CREDENTIALS_PATH", "credentials.json")
    token_path = os.environ.get("DRIVE_TOKEN_PATH", "drive_token.json")

    creds = None
    if Path(token_path).exists():
        creds = Credentials.from_authorized_user_file(token_path, _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, _SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token_path).write_text(creds.to_json())

    return build("drive", "v3", credentials=creds)


def _get_or_create_folder(service, folder_name: str) -> str:
    """Return Drive folder ID, creating it if it doesn't exist."""
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    folder_meta = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    folder = service.files().create(body=folder_meta, fields="id").execute()
    log.info("drive_folder_created", name=folder_name, id=folder["id"])
    return folder["id"]


def upload_episode(mp3_path: Path, date_str: str) -> str:
    """Upload MP3 to NewsFlow/ folder. Returns shareable https link."""
    service = _get_drive_service()
    folder_id = _get_or_create_folder(service, _FOLDER_NAME)

    file_name = f"NewsFlow_{date_str}.mp3"
    media = MediaFileUpload(str(mp3_path), mimetype="audio/mpeg", resumable=True)
    file_meta = {"name": file_name, "parents": [folder_id]}

    log.info("drive_upload_start", file=file_name, size_mb=round(mp3_path.stat().st_size / 1_048_576, 1))
    uploaded = service.files().create(body=file_meta, media_body=media, fields="id").execute()
    file_id = uploaded["id"]

    # Make anyone with the link able to view/listen
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()

    link = f"https://drive.google.com/file/d/{file_id}/view"
    log.info("drive_upload_complete", file=file_name, link=link)
    return link
