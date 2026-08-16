import os
import sys
import uuid
from datetime import datetime, timezone
from io import BytesIO

from pypdf import PdfWriter


sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    ),
)

from fastapi.testclient import TestClient
import main as app_module
from auth import hash_password


TEST_PASSWORD = "CorrectHorseBatteryStaple!"


def make_valid_pdf_bytes() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    return buffer.getvalue()


def create_user(email: str, name: str):
    conn = app_module.get_db()

    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        """
        INSERT INTO users (
            id,
            email,
            name,
            password_hash,
            is_active,
            created_at,
            updated_at,
            last_login_at
        )
        VALUES (?, ?, ?, ?, 1, ?, ?, NULL)
        """,
        (
            user_id,
            email,
            name,
            hash_password(TEST_PASSWORD),
            now,
            now,
        ),
    )

    conn.commit()
    conn.close()

    return user_id


def login_as(client, email: str):
    """Authenticate in an isolated browser session and return a Bearer token."""
    with TestClient(app_module.app) as auth_client:
        response = auth_client.post(
            "/api/apps/local/auth/login",
            json={
                "email": email,
                "password": TEST_PASSWORD,
            },
        )

        assert response.status_code == 200, response.text
        access_token = response.json()["access_token"]

    return {"Authorization": f"Bearer {access_token}"}
def upload_pdf(client, headers, filename="resume.pdf"):
    return client.post(
        "/api/apps/local/integration-endpoints/Core/UploadFile",
        headers=headers,
        files={
            "file": (
                filename,
                make_valid_pdf_bytes(),
                "application/pdf",
            )
        },
    )


def test_upload_requires_authentication(
    client,
    temp_db_path,
):
    response = upload_pdf(
        client,
        headers={},
    )

    assert response.status_code == 401


def test_upload_rejects_non_pdf(
    client,
    temp_db_path,
):
    create_user("primary@example.com", "Primary")
    headers = login_as(client, "primary@example.com")

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/UploadFile",
        headers=headers,
        files={
            "file": (
                "resume.txt",
                b"not a pdf",
                "text/plain",
            )
        },
    )

    assert response.status_code == 400


def test_upload_rejects_fake_pdf(
    client,
    temp_db_path,
):
    create_user("primary@example.com", "Primary")
    headers = login_as(client, "primary@example.com")

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/UploadFile",
        headers=headers,
        files={
            "file": (
                "resume.pdf",
                b"%PDF-1.7\nnot actually a valid pdf",
                "application/pdf",
            )
        },
    )

    assert response.status_code == 400


def test_upload_stores_opaque_file_reference(
    client,
    temp_db_path,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    headers = login_as(client, "primary@example.com")

    response = upload_pdf(
        client,
        headers=headers,
        filename="../../primary-secret.pdf",
    )

    assert response.status_code == 200

    data = response.json()

    assert data["file_id"]
    assert data["file_url"] == f"/api/files/{data['file_id']}"
    assert data["filename"] == "primary-secret.pdf"
    assert data["content_type"] == "application/pdf"
    assert data["size_bytes"] > 0

    conn = app_module.get_db()
    try:
        row = conn.execute(
            """
            SELECT id, user_id, storage_name, original_filename
            FROM uploaded_files
            WHERE id = ?
            """,
            (data["file_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert row["user_id"] == primary_user_id
    assert row["original_filename"] == "primary-secret.pdf"
    assert os.path.basename(row["storage_name"]) != "../../primary-secret.pdf"


def test_upload_never_uses_client_filename_as_storage_path(
    client,
    temp_db_path,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    headers = login_as(client, "primary@example.com")

    response = upload_pdf(
        client,
        headers=headers,
        filename="..\\..\\shared-overwrite.pdf",
    )

    assert response.status_code == 200

    data = response.json()

    assert data["stored_filename"].endswith(".pdf")
    assert data["stored_filename"] != "..\\..\\shared-overwrite.pdf"

    conn = app_module.get_db()
    try:
        row = conn.execute(
            """
            SELECT user_id, storage_name, original_filename
            FROM uploaded_files
            WHERE id = ?
            LIMIT 1
            """,
            (data["file_id"],),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["user_id"] == primary_user_id
    assert row["original_filename"] == "shared-overwrite.pdf"
    assert row["storage_name"].endswith(f"{data['file_id']}.pdf")


def test_upload_rejects_files_over_size_limit(
    client,
    temp_db_path,
):
    create_user("primary@example.com", "Primary")
    headers = login_as(client, "primary@example.com")

    oversized = (
        b"%PDF-1.7\n"
        + (
            b"x"
            * (
                app_module.MAX_UPLOAD_BYTES
                + 1
            )
        )
    )

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/UploadFile",
        headers=headers,
        files={
            "file": (
                "large.pdf",
                oversized,
                "application/pdf",
            )
        },
    )

    assert response.status_code == 413


def test_invoke_llm_cannot_read_another_users_upload(
    client,
    temp_db_path,
    monkeypatch,
):
    primary_user_id = create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")

    primary_headers = login_as(client, "primary@example.com")
    secondary_headers = login_as(client, "secondary@example.com")

    upload_response = upload_pdf(
        client,
        headers=primary_headers,
        filename="primary.pdf",
    )

    assert upload_response.status_code == 200

    primary_file_id = upload_response.json()["file_id"]

    monkeypatch.setattr(
        app_module,
        "call_llm_with_retry",
        lambda **kwargs: {"ok": True},
    )

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/InvokeLLM",
        headers=secondary_headers,
        json={
            "prompt": "Read this file.",
            "file_urls": [
                f"/api/files/{primary_file_id}",
            ],
        },
    )

    assert response.status_code == 404

    assert primary_user_id