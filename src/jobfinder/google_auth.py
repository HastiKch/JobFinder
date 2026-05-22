"""Compatibility facade for Google API client helpers.

New code should import from ``jobfinder.integrations.google.client``.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from jobfinder.env import EnvSettings
from jobfinder.evaluator.storage import read_google_spreadsheet_id
from jobfinder.integrations.google.client import (
    DEFAULT_GOOGLE_API_RETRIES,
    DEFAULT_GOOGLE_API_TIMEOUT_SECONDS,
    authorize_google_oauth,
    build_authorized_http,
    build_google_api_service,
    build_google_drive_oauth_service,
    build_google_oauth_service,
    build_google_service,
    google_api_error_message,
    google_api_retries,
    google_api_timeout_seconds,
    google_execute,
    load_google_oauth_credentials,
    write_private_text_file,
)
from jobfinder.integrations.google.drive import (
    build_google_drive_service,
    get_drive_folder,
    upload_pdf_to_drive,
)
from jobfinder.integrations.google.sheets import build_google_sheets_service

__all__ = [
    "DEFAULT_GOOGLE_API_RETRIES",
    "DEFAULT_GOOGLE_API_TIMEOUT_SECONDS",
    "authorize_google_oauth",
    "build_arg_parser",
    "build_authorized_http",
    "build_google_api_service",
    "build_google_drive_oauth_service",
    "build_google_oauth_service",
    "build_google_service",
    "check_google_connection",
    "google_api_error_message",
    "google_api_retries",
    "google_api_timeout_seconds",
    "google_execute",
    "load_google_oauth_credentials",
    "write_private_text_file",
]


def check_google_connection() -> None:
    """Run a local Google Sheets and Drive OAuth smoke test."""
    settings = EnvSettings()
    spreadsheet_id = read_google_spreadsheet_id(
        settings.get("JOB_EVAL_GOOGLE_SPREADSHEET_ID")
    )
    drive_folder_id = settings.get("JOB_EVAL_CV_DRIVE_FOLDER_ID")

    if not spreadsheet_id:
        raise RuntimeError(
            "Missing GOOGLE_SPREADSHEET_ID or google_spreadsheet_id.txt."
        )
    if not drive_folder_id:
        raise RuntimeError("Missing JOB_EVAL_CV_DRIVE_FOLDER_ID.")

    sheets = build_google_sheets_service(error_cls=RuntimeError)
    drive = build_google_drive_service(error_cls=RuntimeError)
    print("CHECK token/service build: ok")

    sheet_meta = google_execute(
        sheets.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="spreadsheetId,properties(title),spreadsheetUrl",
        ),
        retries=0,
    )
    print(f"CHECK configured spreadsheet read: ok: {sheet_meta['properties']['title']}")

    folder = get_drive_folder(drive, drive_folder_id)
    print(f"CHECK configured drive folder read: ok: {folder.name}")

    created_sheet_id = ""
    uploaded_pdf_id = ""
    try:
        created = google_execute(
            sheets.spreadsheets().create(
                body={
                    "properties": {"title": "JobFinder OAuth Smoke Test"},
                    "sheets": [{"properties": {"title": "Smoke"}}],
                },
                fields="spreadsheetId,spreadsheetUrl",
            ),
            retries=0,
        )
        created_sheet_id = str(created["spreadsheetId"])
        print("CHECK create new spreadsheet: ok")

        google_execute(
            sheets.spreadsheets()
            .values()
            .update(
                spreadsheetId=created_sheet_id,
                range="'Smoke'!A1:B2",
                valueInputOption="RAW",
                body={"values": [["status", "ok"], ["source", "oauth"]]},
            ),
            retries=0,
        )
        print("CHECK write spreadsheet values: ok")

        values = google_execute(
            sheets.spreadsheets()
            .values()
            .get(
                spreadsheetId=created_sheet_id,
                range="'Smoke'!A1:B2",
            ),
            retries=0,
        ).get("values", [])
        if values != [["status", "ok"], ["source", "oauth"]]:
            raise RuntimeError(f"Unexpected spreadsheet values: {values!r}")
        print("CHECK read spreadsheet values: ok")

        with TemporaryDirectory(prefix="jobfinder_google_smoke_") as temp_dir:
            pdf_path = Path(temp_dir) / "jobfinder-oauth-smoke.pdf"
            pdf_path.write_bytes(
                b"%PDF-1.7\n"
                b"1 0 obj<</Type/Catalog>>endobj\n"
                b"trailer<</Root 1 0 R>>\n"
                b"%%EOF\n"
            )
            uploaded = upload_pdf_to_drive(
                drive,
                pdf_path,
                folder_id=folder.id,
                filename="jobfinder-oauth-smoke.pdf",
            )
            uploaded_pdf_id = uploaded.id
        print("CHECK upload PDF to configured Drive folder: ok")

    finally:
        if uploaded_pdf_id:
            google_execute(
                drive.files().delete(
                    fileId=uploaded_pdf_id,
                    supportsAllDrives=True,
                ),
                retries=0,
            )
            print("CLEANUP uploaded PDF: ok")
        if created_sheet_id:
            google_execute(
                drive.files().delete(
                    fileId=created_sheet_id,
                    supportsAllDrives=True,
                ),
                retries=0,
            )
            print("CLEANUP temporary spreadsheet: ok")

    print("RESULT local Google Sheets + Drive OAuth smoke test: passed")


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the Google auth helper argument parser."""
    parser = argparse.ArgumentParser(
        description="Authorize or validate JobFinder Google OAuth access."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Validate local Sheets and Drive access with temporary create, "
            "write, upload, and cleanup checks."
        ),
    )
    return parser


def main() -> int:
    """Authorize Google OAuth locally or validate the connection."""
    args = build_arg_parser().parse_args()
    try:
        if args.check:
            check_google_connection()
        else:
            token_path = authorize_google_oauth()
            print(f"Created {token_path.name}")
    except RuntimeError as exc:
        print(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
