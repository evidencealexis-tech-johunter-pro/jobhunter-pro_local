from __future__ import annotations

import hashlib
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException, status
from pypdf import PdfReader


DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_BYTES = int(
    os.getenv(
        "MAX_UPLOAD_BYTES",
        str(DEFAULT_MAX_UPLOAD_BYTES),
    )
)

PDF_EXTENSION = ".pdf"
PDF_CONTENT_TYPE = "application/pdf"

FILE_REFERENCE_PATTERN = re.compile(
    r"^/api/files/(?P<file_id>[0-9a-fA-F-]{36})$"
)


@dataclass(frozen=True)
class StoredFile:
    file_id: str
    user_id: str
    storage_path: Path
    original_filename: str
    content_type: str
    size_bytes: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _storage_root() -> Path:
    """
    Resolve the application's single upload root.

    The existing application configures UPLOAD_DIR relative to the
    project working directory. We preserve that behavior here so all
    upload-related code resolves files from exactly one location.
    """
    configured_root = os.getenv(
        "UPLOAD_DIR",
        "uploaded_resumes",
    )

    root = Path(configured_root).expanduser().resolve()

    root.mkdir(
        mode=0o750,
        parents=True,
        exist_ok=True,
    )

    return root


def initialize_schema(conn) -> None:
    """
    Ensure upload metadata exists.

    This is intentionally idempotent so both application startup and
    isolated tests can safely initialize the storage subsystem.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS uploaded_files (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            storage_name TEXT NOT NULL UNIQUE,
            original_filename TEXT NOT NULL,
            content_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL,
            sha256 TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_uploaded_files_user_id
        ON uploaded_files(user_id)
        """
    )

    conn.commit()


def _sanitize_original_filename(
    filename: str | None,
) -> str:
    raw = os.path.basename(
        (filename or "").strip()
    )

    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A filename is required.",
        )

    if "\x00" in raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid filename.",
        )

    if not raw.lower().endswith(PDF_EXTENSION):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted.",
        )

    if len(raw) > 255:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is too long.",
        )

    return raw


def _validate_pdf_bytes(
    content: bytes,
    *,
    content_type: str | None,
) -> None:
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )

    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=(
                "File is too large. "
                "Maximum size is 10 MB."
            ),
        )

    if content_type and content_type != PDF_CONTENT_TYPE:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="The uploaded file must be a PDF.",
        )

    if not content.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is not a valid PDF.",
        )

    try:
        reader = PdfReader(
            BytesIO(content),
            strict=False,
        )

        if not reader.pages:
            raise ValueError(
                "PDF contains no pages"
            )

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "The uploaded file is not "
                "a readable PDF."
            ),
        ) from exc


def _storage_name(
    user_id: str,
    file_id: str,
) -> str:
    return f"{user_id}/{file_id}.pdf"


def _safe_path(
    storage_name: str,
) -> Path:
    root = _storage_root().resolve()
    candidate = (
        root / storage_name
    ).resolve()

    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            "Resolved file path escapes storage root."
        ) from exc

    return candidate


def store_pdf(
    conn,
    *,
    user_id: str,
    filename: str | None,
    content_type: str | None,
    content: bytes,
) -> StoredFile:
    original_filename = (
        _sanitize_original_filename(
            filename
        )
    )

    _validate_pdf_bytes(
        content,
        content_type=content_type,
    )

    initialize_schema(conn)

    file_id = str(uuid.uuid4())

    storage_name = _storage_name(
        user_id,
        file_id,
    )

    storage_path = _safe_path(
        storage_name
    )

    storage_path.parent.mkdir(
        mode=0o750,
        parents=True,
        exist_ok=True,
    )

    digest = hashlib.sha256(
        content
    ).hexdigest()

    try:
        with open(
            storage_path,
            "xb",
        ) as handle:
            handle.write(content)

        conn.execute(
            """
            INSERT INTO uploaded_files (
                id,
                user_id,
                storage_name,
                original_filename,
                content_type,
                size_bytes,
                sha256,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                user_id,
                storage_name,
                original_filename,
                PDF_CONTENT_TYPE,
                len(content),
                digest,
                _utc_now(),
            ),
        )

        conn.commit()

    except Exception:
        try:
            storage_path.unlink(
                missing_ok=True
            )
        finally:
            conn.rollback()

        raise

    return StoredFile(
        file_id=file_id,
        user_id=user_id,
        storage_path=storage_path,
        original_filename=original_filename,
        content_type=PDF_CONTENT_TYPE,
        size_bytes=len(content),
    )


def _extract_file_id(
    file_reference: str,
) -> str:
    reference = (
        file_reference or ""
    ).strip()

    match = FILE_REFERENCE_PATTERN.fullmatch(
        reference
    )

    if match:
        return match.group("file_id")

    try:
        return str(
            uuid.UUID(reference)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file reference.",
        ) from exc


def get_owned_file(
    conn,
    *,
    user_id: str,
    file_reference: str,
) -> StoredFile:
    initialize_schema(conn)

    file_id = _extract_file_id(
        file_reference
    )

    row = conn.execute(
        """
        SELECT
            id,
            user_id,
            storage_name,
            original_filename,
            content_type,
            size_bytes
        FROM uploaded_files
        WHERE id = ?
          AND user_id = ?
        LIMIT 1
        """,
        (
            file_id,
            user_id,
        ),
    ).fetchone()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )

    storage_path = _safe_path(
        row["storage_name"]
    )

    if not storage_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found.",
        )

    return StoredFile(
        file_id=row["id"],
        user_id=row["user_id"],
        storage_path=storage_path,
        original_filename=row[
            "original_filename"
        ],
        content_type=row[
            "content_type"
        ],
        size_bytes=row[
            "size_bytes"
        ],
    )


def file_reference(
    file_id: str,
) -> str:
    return f"/api/files/{file_id}"