"""Tests for generated CV PDF output."""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from jobfinder.evaluator.latex import LatexCompilationResult, compile_latex_to_pdf
from jobfinder.evaluator.models import JobEvaluation, JobRecord
from jobfinder.evaluator.pdf_output import (
    assign_cv_ids,
    cv_pdf_filename,
    drive_run_folder_name,
    generate_cv_pdf_outputs,
    sanitize_filename,
)

LATEX_CV = r"\documentclass{article}\begin{document}\section*{Profile}\end{document}"


class FakeRequest:
    """Minimal executable fake Google API request."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    def execute(self) -> dict[str, Any]:
        return self.result


class FakeDriveFiles:
    """Fake Drive files resource for folder creation tests."""

    def __init__(self, service: FakeDriveService) -> None:
        self.service = service

    def list(self, **kwargs: Any) -> FakeRequest:
        self.service.lists.append(kwargs)
        return FakeRequest({"files": []})

    def create(self, **kwargs: Any) -> FakeRequest:
        body = kwargs["body"]
        self.service.creates.append(kwargs)
        file_id = f"folder-{len(self.service.creates)}"
        return FakeRequest(
            {
                "id": file_id,
                "name": body["name"],
                "webViewLink": f"https://drive.example/{file_id}",
            }
        )


class FakeDriveService:
    """Small fake for the Google Drive service surface used by PDF output."""

    def __init__(self) -> None:
        self.lists: list[dict[str, Any]] = []
        self.creates: list[dict[str, Any]] = []

    def files(self) -> FakeDriveFiles:
        return FakeDriveFiles(self)


def test_sanitize_filename_removes_path_and_unsafe_characters():
    """Generated PDF filenames should not preserve path separators or wildcards."""
    value = sanitize_filename("../Senior: GIS/Remote*? <Berlin>|")

    assert value == "Senior GIS Remote Berlin"


def test_cv_pdf_filename_uses_requested_parts_in_order():
    """Generated PDF filenames should use ID, applicant, role, then company."""
    assert cv_pdf_filename(
        12,
        "Senior GIS Analyst (m/f/d), Remote / Geo+Maps GmbH & Co. KG",
        "Amir Donyadide",
    ) == ("12_CV_Amir_Donyadide_Senior_GIS_Analyst_m_f_Geo_Maps.pdf")
    assert cv_pdf_filename(13, "Développeur C++ / Météo AG") == (
        "13_CV_Applicant_Developpeur_C_Meteo.pdf"
    )


def test_assign_cv_ids_are_row_numbers_for_generated_cvs():
    """Only rows with generated LaTeX CVs receive stable row-number IDs."""
    records = [
        JobRecord(2, "GIS Analyst / Acme", "Job Title: GIS Analyst"),
        JobRecord(3, "Senior Manager / Acme", "Job Title: Senior Manager"),
        JobRecord(4, "Remote Sensing / Example", "Job Title: Remote Sensing"),
    ]
    evaluations = {
        2: JobEvaluation(2, "Suitable", 90, "Match", tailored_cv=LATEX_CV),
        3: JobEvaluation(3, "Not Suitable", 30, "Too senior", tailored_cv=LATEX_CV),
        4: JobEvaluation(4, "Suitable", 88, "Match", tailored_cv=LATEX_CV),
    }

    candidates = assign_cv_ids(records, evaluations)

    assert [candidate.cv_id for candidate in candidates] == [2, 4]
    assert [candidate.row_number for candidate in candidates] == [2, 4]
    assert candidates[0].filename == "2_CV_Applicant_GIS_Analyst_Acme.pdf"
    assert candidates[1].filename == "4_CV_Applicant_Remote_Sensing_Example.pdf"


def test_compile_latex_to_pdf_captures_subprocess_failure(tmp_path):
    """LaTeX compiler failures should return an error instead of raising."""
    output_pdf = tmp_path / "cv.pdf"

    def fake_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="! Undefined control sequence.",
            stderr="",
        )

    result = compile_latex_to_pdf(
        r"\documentclass{article}\begin{document}\bad\end{document}",
        output_pdf,
        runner=fake_runner,
    )

    assert result.success is False
    assert "! Undefined control sequence." in result.error
    assert not output_pdf.exists()


def test_compile_latex_to_pdf_rejects_unsafe_input_commands(tmp_path):
    """Model-generated CVs should not be able to read arbitrary local files."""
    output_pdf = tmp_path / "cv.pdf"

    def fake_runner(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise AssertionError("unsafe LaTeX should be rejected before latexmk runs")

    result = compile_latex_to_pdf(
        r"\documentclass{article}\begin{document}\input{/etc/passwd}\end{document}",
        output_pdf,
        runner=fake_runner,
    )

    assert result.success is False
    assert "unsupported command" in result.error
    assert not output_pdf.exists()


def test_drive_run_folder_name_uses_required_format():
    """Drive run folder names should use sortable timestamps."""
    assert drive_run_folder_name(datetime(2026, 5, 20, 9, 8, 7)) == (
        "2026-05-20_09-08-07"
    )


def test_generate_cv_pdf_outputs_creates_drive_folder_and_links(tmp_path):
    """PDF generation should compile, upload, and return row-level Drive links."""
    service = FakeDriveService()
    uploads: list[tuple[Path, str, str]] = []
    records = [JobRecord(2, "GIS Analyst / Acme", "Job Title: GIS Analyst")]
    evaluations = {2: JobEvaluation(2, "Suitable", 90, "Match", tailored_cv=LATEX_CV)}

    def fake_compile(
        latex_code: str,
        output_pdf: Path,
        **kwargs: Any,
    ) -> LatexCompilationResult:
        output_pdf.write_bytes(b"%PDF-1.7\n")
        return LatexCompilationResult(success=True, pdf_path=output_pdf)

    def fake_upload(
        drive_service: Any,
        pdf_path: Path,
        *,
        folder_id: str,
        filename: str,
    ) -> SimpleNamespace:
        uploads.append((pdf_path, folder_id, filename))
        return SimpleNamespace(web_view_link=f"https://drive.example/{filename}")

    result = generate_cv_pdf_outputs(
        records,
        evaluations,
        drive_service=service,
        now=datetime(2026, 5, 20, 9, 8, 7),
        compile_latex=fake_compile,
        upload_pdf=fake_upload,
    )

    assert result.outputs == {
        2: "https://drive.example/2_CV_Applicant_GIS_Analyst_Acme.pdf"
    }
    assert result.success_count == 1
    assert result.error_count == 0
    assert [call["body"]["name"] for call in service.creates] == [
        "JobFinder",
        "2026-05-20_09-08-07",
    ]
    assert uploads[0][1] == "folder-2"
    assert uploads[0][2] == "2_CV_Applicant_GIS_Analyst_Acme.pdf"
