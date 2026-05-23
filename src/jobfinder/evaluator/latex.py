"""LaTeX-to-PDF compilation utilities for generated CVs."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# XeTeX writes "Output written on cv.pdf (N pages, ...)." to stdout.
_PAGE_COUNT_RE = re.compile(
    r"Output written on [^\(]*\(\s*(\d+)\s+pages?\b",
    re.IGNORECASE,
)
PDFLATEX_ENCODING_PACKAGE_RE = re.compile(
    r"(?m)^[ \t]*\\usepackage(?:\[[^\]]*\])?\{(?:inputenc|fontenc)\}"
    r"[ \t]*(?:%.*)?\n?"
)
FONT_SPEC_PACKAGE_RE = re.compile(
    r"(?m)^[ \t]*(?:\\usepackage(?:\[[^\]]*\])?\{fontspec\}|\\setmainfont\b)"
)
DOCUMENTCLASS_RE = re.compile(
    r"(?m)^[ \t]*\\documentclass(?:\[[^\]]*\])?\{[^}]+\}[ \t]*(?:%.*)?\n?"
)
XELATEX_UNICODE_FONT_BLOCK = r"""\usepackage{fontspec}
\defaultfontfeatures{Ligatures=TeX}
\setmainfont{lmroman10-regular.otf}[
  BoldFont=lmroman10-bold.otf,
  ItalicFont=lmroman10-italic.otf,
  BoldItalicFont=lmroman10-bolditalic.otf
]"""


@dataclass(frozen=True)
class LatexCompilationResult:
    """Result of compiling one generated LaTeX CV."""

    success: bool
    pdf_path: Path | None = None
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    page_count: int | None = None


def parse_page_count_from_output(text: str) -> int | None:
    """Extract the compiled PDF page count from XeTeX/latexmk stdout."""
    match = _PAGE_COUNT_RE.search(text)
    if match:
        return int(match.group(1))
    return None


def prepare_latex_for_xelatex(latex_code: str) -> str:
    """Return LaTeX source with Unicode fonts suitable for XeLaTeX."""
    stripped = latex_code.strip()
    if FONT_SPEC_PACKAGE_RE.search(stripped):
        return stripped

    updated = PDFLATEX_ENCODING_PACKAGE_RE.sub("", stripped)
    documentclass_match = DOCUMENTCLASS_RE.search(updated)
    if not documentclass_match:
        return "\n".join((XELATEX_UNICODE_FONT_BLOCK, updated)).strip()

    insert_at = documentclass_match.end()
    prefix = updated[:insert_at]
    suffix = updated[insert_at:].lstrip("\n")
    return "\n".join((prefix.rstrip(), XELATEX_UNICODE_FONT_BLOCK, suffix)).strip()


SubprocessRunner = Callable[..., subprocess.CompletedProcess[str]]
DANGEROUS_LATEX_COMMAND_RE = re.compile(
    r"\\(?:"
    r"input|include|includeonly|import|subimport|"
    r"openin|openout|read|write|write18|"
    r"catcode|csname|newread|newwrite"
    r")\b"
)


def tail_text(text: str, limit: int = 4000) -> str:
    """Return the final part of a long compiler log for spreadsheet storage."""
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return "[truncated]\n" + stripped[-limit:]


def copy_photo_to_compilation_dir(photo_path: Path | None, temp_dir: Path) -> None:
    """Copy an optional CV photo into paths LaTeX commonly references."""
    if photo_path is None or not photo_path.exists():
        return

    target = temp_dir / photo_path.name
    shutil.copy2(photo_path, target)

    parent_named_target = temp_dir / photo_path.parent.name / photo_path.name
    if parent_named_target != target:
        parent_named_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(photo_path, parent_named_target)


def latex_safety_error(latex_code: str) -> str:
    """Return an error when generated LaTeX uses unsafe filesystem primitives."""
    match = DANGEROUS_LATEX_COMMAND_RE.search(latex_code)
    if not match:
        return ""
    return (
        "Generated LaTeX contains unsupported command "
        f"{match.group(0)!r}. CV PDF compilation only allows self-contained "
        "documents plus optional included images."
    )


def compile_latex_to_pdf(
    latex_code: str,
    output_pdf: Path,
    *,
    photo_path: Path | None = None,
    timeout_seconds: int = 120,
    runner: SubprocessRunner = subprocess.run,
) -> LatexCompilationResult:
    """Compile generated LaTeX CV code into a PDF using an isolated temp dir."""
    output_pdf = output_pdf.resolve()
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    safety_error = latex_safety_error(latex_code)
    if safety_error:
        return LatexCompilationResult(success=False, error=safety_error)

    with tempfile.TemporaryDirectory(prefix="jobfinder_cv_") as temp_name:
        temp_dir = Path(temp_name)
        tex_path = temp_dir / "cv.tex"
        tex_path.write_text(
            prepare_latex_for_xelatex(latex_code) + "\n",
            encoding="utf-8",
        )
        copy_photo_to_compilation_dir(photo_path, temp_dir)

        command = [
            "latexmk",
            "-xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            "cv.tex",
        ]
        try:
            completed = runner(
                command,
                cwd=temp_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError:
            return LatexCompilationResult(
                success=False,
                error=(
                    "latexmk was not found. Install latexmk and xelatex "
                    "(for example, texlive-xetex on Ubuntu)."
                ),
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return LatexCompilationResult(
                success=False,
                error=tail_text(
                    "\n".join(
                        part
                        for part in (
                            f"LaTeX compilation timed out after {timeout_seconds}s.",
                            stdout,
                            stderr,
                        )
                        if part
                    )
                ),
                stdout=stdout,
                stderr=stderr,
            )

        stdout = completed.stdout or ""
        stderr = completed.stderr or ""
        compiled_pdf = temp_dir / "cv.pdf"
        if completed.returncode != 0:
            return LatexCompilationResult(
                success=False,
                error=tail_text("\n".join(part for part in (stdout, stderr) if part)),
                stdout=stdout,
                stderr=stderr,
            )
        if not compiled_pdf.exists():
            return LatexCompilationResult(
                success=False,
                error=tail_text(
                    "\n".join(
                        part
                        for part in (
                            "LaTeX finished without producing cv.pdf.",
                            stdout,
                            stderr,
                        )
                        if part
                    )
                ),
                stdout=stdout,
                stderr=stderr,
            )

        shutil.copy2(compiled_pdf, output_pdf)
        page_count = parse_page_count_from_output(
            stdout
        ) or parse_page_count_from_output(stderr)
        return LatexCompilationResult(
            success=True,
            pdf_path=output_pdf,
            stdout=stdout,
            stderr=stderr,
            page_count=page_count,
        )
