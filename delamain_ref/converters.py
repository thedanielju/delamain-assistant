from __future__ import annotations

import importlib.metadata
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .templates import warning_block
from .util import utc_now_iso


@dataclass
class ConversionResult:
    ok: bool
    status: str
    converter: str
    markdown: str
    warnings: list[str] = field(default_factory=list)
    extraction_report: dict = field(default_factory=dict)
    metadata_notes: list[str] = field(default_factory=list)
    error: str | None = None


def detect_dependencies() -> dict:
    return {
        "docling": _has_docling(),
        "pandoc": _pandoc_command() is not None,
        "ocrmypdf": _tool_command("ocrmypdf") is not None,
        "tesseract": _tool_command("tesseract") is not None,
        "pypdf": _has_module("pypdf"),
        "python_docx": _has_module("docx"),
    }


def convert_rich_document(source: Path, figures_dir: Path) -> ConversionResult:
    extension = source.suffix.lower()
    figures_dir.mkdir(parents=True, exist_ok=True)

    if extension in {".docx", ".rtf", ".odt"}:
        docling_result = _try_docling(source, figures_dir)
        if docling_result and docling_result.ok:
            return docling_result
        pandoc_result = _convert_with_pandoc(source, figures_dir)
        if docling_result and not docling_result.ok:
            pandoc_result.warnings.extend(docling_result.warnings)
        return pandoc_result

    if extension == ".pdf":
        docling_result = _try_docling(source, figures_dir)
        if docling_result and docling_result.ok:
            return docling_result
        pdf_result = _convert_pdf_with_pypdf(source)
        if docling_result and not docling_result.ok:
            pdf_result.warnings.extend(docling_result.warnings)
        return pdf_result

    return ConversionResult(
        ok=False,
        status="failed",
        converter="none",
        markdown="",
        warnings=[f"Unsupported extension: {extension}"],
        error=f"Unsupported extension: {extension}",
    )


def _has_docling() -> bool:
    return _has_module("docling")


def _has_module(name: str) -> bool:
    try:
        __import__(name)
    except Exception:
        return False
    return True


def _try_docling(source: Path, figures_dir: Path) -> ConversionResult | None:
    if not _has_docling():
        return None
    try:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(str(source))
        markdown = result.document.export_to_markdown()
        warnings: list[str] = []
        extraction = {"kind": "docling", "generated_at": utc_now_iso()}
        try:
            extraction["document"] = result.document.export_to_dict()
        except Exception:
            extraction["document"] = {"note": "Docling structured export unavailable"}
        version = importlib.metadata.version("docling")
        return ConversionResult(
            ok=True,
            status="fresh",
            converter=f"docling@{version}",
            markdown=warning_block(warnings) + markdown,
            warnings=warnings,
            extraction_report=extraction,
        )
    except Exception as exc:  # pragma: no cover - only when docling exists and fails.
        return ConversionResult(
            ok=False,
            status="failed",
            converter="docling",
            markdown="",
            warnings=[f"Docling failed: {exc}"],
            extraction_report={"kind": "docling", "error": str(exc)},
            error=str(exc),
        )


def _convert_with_pandoc(source: Path, figures_dir: Path) -> ConversionResult:
    pandoc = _pandoc_command()
    if pandoc is None:
        return ConversionResult(
            ok=False,
            status="failed",
            converter="none",
            markdown="",
            warnings=["pandoc is not installed; cannot convert Office-style document."],
            error="Missing dependency: pandoc",
        )

    output_path = source.parent / "_document.pandoc.md"
    cmd = [
        pandoc,
        str(source),
        "-t",
        "gfm",
        "--wrap=none",
        "--extract-media",
        str(figures_dir),
        "-o",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        markdown = output_path.read_text(encoding="utf-8")
    except subprocess.CalledProcessError as exc:
        return ConversionResult(
            ok=False,
            status="failed",
            converter="pandoc",
            markdown="",
            warnings=[f"Pandoc conversion failed: {exc.stderr.strip() or exc.stdout.strip()}"],
            extraction_report={"kind": "pandoc", "cmd": cmd},
            error=exc.stderr.strip() or exc.stdout.strip() or str(exc),
        )
    finally:
        if output_path.exists():
            output_path.unlink(missing_ok=True)

    if not markdown.strip():
        return ConversionResult(
            ok=False,
            status="failed",
            converter="pandoc",
            markdown="",
            warnings=["Pandoc returned empty markdown output."],
            extraction_report={"kind": "pandoc", "cmd": cmd},
            error="Empty markdown output",
        )

    pandoc_version = _pandoc_version()
    return ConversionResult(
        ok=True,
        status="fresh",
        converter=f"pandoc@{pandoc_version}",
        markdown=markdown,
        extraction_report={"kind": "pandoc", "cmd": cmd},
    )


def _convert_pdf_with_pypdf(source: Path) -> ConversionResult:
    loaded = _load_pypdf()
    if loaded is None:
        return ConversionResult(
            ok=False,
            status="failed",
            converter="none",
            markdown="",
            warnings=["pypdf is not installed; cannot extract PDF text."],
            error="Missing dependency: pypdf",
        )
    PdfReader, pypdf_version = loaded
    try:
        reader = PdfReader(str(source))
    except Exception as exc:
        return ConversionResult(
            ok=False,
            status="failed",
            converter=f"pypdf@{pypdf_version}",
            markdown="",
            warnings=[f"Unable to open PDF: {exc}"],
            error=str(exc),
        )

    pages: list[dict] = []
    total_chars = 0
    lines = [f"# {source.stem}", ""]
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        total_chars += len(text)
        pages.append({"page": idx, "chars": len(text)})
        lines.extend([f"## Page {idx}", ""])
        if text:
            lines.append(text)
        else:
            lines.append("_[No text extracted]_")
        lines.append("")

    warnings: list[str] = []
    status = "fresh"
    page_count = max(len(pages), 1)
    avg_chars = total_chars / page_count

    if total_chars < 200 or avg_chars < 45:
        source_size_mb = source.stat().st_size / (1024 * 1024)
        if source_size_mb >= 30:
            status = "needs_ocr"
            warnings.append(
                f"PDF text extraction is poor and source is {source_size_mb:.1f} MB; manual OCR approval recommended."
            )
        elif _tool_command("ocrmypdf") and _tool_command("tesseract"):
            ocr_result = _try_ocr(source)
            if ocr_result:
                return ocr_result
            status = "needs_ocr"
            warnings.append("OCR attempt failed; manual review needed.")
        else:
            status = "needs_ocr"
            warnings.append(
                "PDF text extraction is poor and OCR dependencies are missing (ocrmypdf/tesseract)."
            )

    markdown = warning_block(warnings) + "\n".join(lines).rstrip() + "\n"
    return ConversionResult(
        ok=True,
        status=status,
        converter=f"pypdf@{pypdf_version}",
        markdown=markdown,
        warnings=warnings,
        extraction_report={"kind": "pypdf", "pages": pages, "total_chars": total_chars},
    )


def _try_ocr(source: Path) -> ConversionResult | None:
    loaded = _load_pypdf()
    if loaded is None:
        return None
    PdfReader, _ = loaded
    ocr_pdf = source.parent / f"{source.stem}.ocr.pdf"
    sidecar = source.parent / f"{source.stem}.ocr.txt"
    cmd = [
        _tool_command("ocrmypdf") or "ocrmypdf",
        "--skip-text",
        "--force-ocr",
        "--sidecar",
        str(sidecar),
        str(source),
        str(ocr_pdf),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        reader = PdfReader(str(ocr_pdf))
        lines = [f"# {source.stem}", ""]
        pages: list[dict] = []
        total_chars = 0
        for idx, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            total_chars += len(text)
            pages.append({"page": idx, "chars": len(text)})
            lines.extend([f"## Page {idx}", "", text or "_[No text extracted]_", ""])

        markdown = "\n".join(lines).rstrip() + "\n"
        return ConversionResult(
            ok=True,
            status="fresh",
            converter="pypdf+ocrmypdf",
            markdown=markdown,
            extraction_report={
                "kind": "ocrmypdf",
                "cmd": cmd,
                "pages": pages,
                "total_chars": total_chars,
                "ocr_pdf": ocr_pdf.name,
                "sidecar": sidecar.name,
            },
        )
    except subprocess.CalledProcessError:
        return None


def _pandoc_version() -> str:
    pandoc = _pandoc_command()
    if pandoc is None:
        return "missing"
    proc = subprocess.run([pandoc, "--version"], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return "unknown"
    first = (proc.stdout.splitlines() or ["unknown"])[0]
    return first.replace("pandoc", "").strip() or "unknown"


def _load_pypdf():
    try:
        from pypdf import PdfReader, __version__ as pypdf_version
    except Exception:
        return None
    return PdfReader, pypdf_version


def _pandoc_command() -> str | None:
    system_pandoc = _tool_command("pandoc")
    if system_pandoc:
        return system_pandoc
    try:
        import pypandoc

        path = pypandoc.get_pandoc_path()
    except Exception:
        return None
    return path or None


def _tool_command(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    candidate = Path(sys.executable).parent / name
    if candidate.exists():
        return str(candidate)
    return None


def build_metadata_payload(
    *,
    source_name: str,
    source_size: int,
    source_sha256: str,
    source_mtime: str,
    converter: str,
    status: str,
    warnings: list[str],
    extraction_report: dict,
) -> dict:
    return {
        "generated_at": utc_now_iso(),
        "source": {
            "name": source_name,
            "size_bytes": source_size,
            "sha256": source_sha256,
            "mtime": source_mtime,
        },
        "conversion": {
            "converter": converter,
            "status": status,
            "warnings": warnings,
            "confidence": "deterministic conversion without LLM summarization",
        },
        "extraction": {"report_digest": _json_digest(extraction_report)},
    }


def _json_digest(payload: dict) -> str:
    if not payload:
        return "empty"
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True)
    # avoid additional imports for digest formatting.
    return f"len:{len(serialized)}"
