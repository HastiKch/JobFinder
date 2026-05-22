"""Compatibility facade for Google Drive helpers.

New code should import from ``jobfinder.integrations.google.drive``.
"""

from __future__ import annotations

from jobfinder.integrations.google.drive import (
    DRIVE_FOLDER_MIME_TYPE,
    GOOGLE_DRIVE_SCOPES,
    DriveFile,
    DriveFolder,
    build_google_drive_service,
    create_drive_folder,
    drive_query_literal,
    find_drive_folder,
    get_drive_folder,
    get_or_create_drive_folder,
    parent_query,
    upload_pdf_to_drive,
)

__all__ = [
    "DRIVE_FOLDER_MIME_TYPE",
    "GOOGLE_DRIVE_SCOPES",
    "DriveFile",
    "DriveFolder",
    "build_google_drive_service",
    "create_drive_folder",
    "drive_query_literal",
    "find_drive_folder",
    "get_drive_folder",
    "get_or_create_drive_folder",
    "parent_query",
    "upload_pdf_to_drive",
]
