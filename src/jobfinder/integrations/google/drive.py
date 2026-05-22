"""Google Drive helpers for saving generated CV PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jobfinder.integrations.google.client import (
    build_google_drive_oauth_service,
    google_execute,
)
from jobfinder.integrations.google.credentials import (
    GOOGLE_OAUTH_SCOPES,
    GoogleAuthConfig,
)

GOOGLE_DRIVE_SCOPES = GOOGLE_OAUTH_SCOPES
"""Google OAuth scopes required to create folders and upload PDFs to Drive."""

DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class DriveFolder:
    """Small value object for a Google Drive folder."""

    id: str
    name: str
    web_view_link: str = ""


@dataclass(frozen=True)
class DriveFile:
    """Small value object for an uploaded Google Drive file."""

    id: str
    name: str
    web_view_link: str


def build_google_drive_service(
    *,
    error_cls: type[RuntimeError],
    token_file: Path | None = None,
    client_secret_file: Path | None = None,
    auth_config: GoogleAuthConfig | None = None,
) -> Any:
    """Build an OAuth-authenticated Google Drive API service."""
    return build_google_drive_oauth_service(
        "v3",
        error_cls=error_cls,
        token_file=token_file,
        client_secret_file=client_secret_file,
        auth_config=auth_config,
        scopes=GOOGLE_DRIVE_SCOPES,
    )


def drive_query_literal(value: str) -> str:
    """Escape a string for use inside a Drive API query literal."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def parent_query(parent_id: str | None) -> str:
    """Return a Drive query clause restricting files to a parent folder."""
    if not parent_id:
        return ""
    return f"'{drive_query_literal(parent_id)}' in parents"


def find_drive_folder(
    service: Any,
    name: str,
    *,
    parent_id: str | None = None,
) -> DriveFolder | None:
    """Find the first non-trashed Drive folder with the requested name."""
    clauses = [
        f"name = '{drive_query_literal(name)}'",
        f"mimeType = '{DRIVE_FOLDER_MIME_TYPE}'",
        "trashed = false",
    ]
    parent_clause = parent_query(parent_id)
    if parent_clause:
        clauses.append(parent_clause)

    response = google_execute(
        service.files().list(
            q=" and ".join(clauses),
            spaces="drive",
            fields="files(id,name,webViewLink)",
            pageSize=10,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
    )
    files = response.get("files", [])
    if not files:
        return None
    folder = files[0]
    return DriveFolder(
        id=str(folder["id"]),
        name=str(folder.get("name", name)),
        web_view_link=str(folder.get("webViewLink", "")),
    )


def create_drive_folder(
    service: Any,
    name: str,
    *,
    parent_id: str | None = None,
) -> DriveFolder:
    """Create a Google Drive folder and return its metadata."""
    body: dict[str, Any] = {"name": name, "mimeType": DRIVE_FOLDER_MIME_TYPE}
    if parent_id:
        body["parents"] = [parent_id]
    response = google_execute(
        service.files().create(
            body=body,
            fields="id,name,webViewLink",
            supportsAllDrives=True,
        ),
        retries=0,
    )
    return DriveFolder(
        id=str(response["id"]),
        name=str(response.get("name", name)),
        web_view_link=str(response.get("webViewLink", "")),
    )


def get_drive_folder(service: Any, folder_id: str) -> DriveFolder:
    """Return a Drive folder by ID, raising a clear error when it is unusable."""
    normalized_folder_id = folder_id.strip()
    if not normalized_folder_id:
        raise RuntimeError(
            "Missing Google Drive folder ID. Set JOB_EVAL_CV_DRIVE_FOLDER_ID to "
            "the ID of the Drive folder where JobFinder should create timestamped "
            "PDF run folders."
        )

    try:
        response = google_execute(
            service.files().get(
                fileId=normalized_folder_id,
                fields="id,name,mimeType,webViewLink",
                supportsAllDrives=True,
            ),
            retries=0,
        )
    except Exception as exc:
        raise RuntimeError(
            f"Could not access Google Drive folder ID '{normalized_folder_id}'. "
            "Check that the ID is a folder in the authorized user's Drive account "
            "or a folder shared with that account, and that the Drive API is "
            f"enabled. Details: {exc}"
        ) from exc

    if response.get("mimeType") != DRIVE_FOLDER_MIME_TYPE:
        raise RuntimeError(
            f"Google Drive ID '{normalized_folder_id}' is not a folder. Set "
            "JOB_EVAL_CV_DRIVE_FOLDER_ID to a folder ID from a Drive URL."
        )

    return DriveFolder(
        id=str(response["id"]),
        name=str(response.get("name", normalized_folder_id)),
        web_view_link=str(response.get("webViewLink", "")),
    )


def get_or_create_drive_folder(
    service: Any,
    name: str,
    *,
    parent_id: str | None = None,
) -> DriveFolder:
    """Return an existing Drive folder by name, creating it when absent."""
    existing = find_drive_folder(service, name, parent_id=parent_id)
    if existing is not None:
        return existing
    return create_drive_folder(service, name, parent_id=parent_id)


def upload_pdf_to_drive(
    service: Any,
    pdf_path: Path,
    *,
    folder_id: str,
    filename: str,
) -> DriveFile:
    """Upload one PDF into a Drive folder and return its user-facing link."""
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise RuntimeError(
            "Missing Google API upload support. Install dependencies with: "
            "python -m pip install -r requirements.txt"
        ) from exc

    media = MediaFileUpload(
        str(pdf_path),
        mimetype="application/pdf",
        resumable=False,
    )
    response = google_execute(
        service.files().create(
            body={
                "name": filename,
                "parents": [folder_id],
                "mimeType": "application/pdf",
            },
            media_body=media,
            fields="id,name,webViewLink,webContentLink",
            supportsAllDrives=True,
        ),
        retries=0,
    )
    file_id = str(response["id"])
    link = str(
        response.get("webViewLink")
        or response.get("webContentLink")
        or f"https://drive.google.com/file/d/{file_id}/view"
    )
    return DriveFile(
        id=file_id,
        name=str(response.get("name", filename)),
        web_view_link=link,
    )
