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

import main as app_module
from auth import hash_password


TEST_PASSWORD = "CorrectHorseBatteryStaple!"


def make_valid_pdf_bytes() -> bytes:
    buffer = BytesIO()

    writer = PdfWriter()
    writer.add_blank_page(
        width=612,
        height=792,
    )

    writer.write(buffer)

    return buffer.getvalue()


def create_user(
    email: str,
    name: str,
):
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


def login_as(
    client,
    email: str,
):
    response = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": email,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200

    return {
        "Authorization": (
            f"Bearer {response.json()['access_token']}"
        ),
    }


def upload_pdf(
    client,
    headers,
    filename="resume.pdf",
):
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
    create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

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
    create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

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
    alice_id = create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

    response = upload_pdf(
        client,
        headers=headers,
        filename="../../alice-secret.pdf",
    )

    assert response.status_code == 200

    data = response.json()

    assert data["file_id"]

    assert data["file_url"] == (
        f"/api/files/{data['file_id']}"
    )

    assert data["filename"] == "alice-secret.pdf"

    assert data["content_type"] == "application/pdf"

    assert data["size_bytes"] > 0

    conn = app_module.get_db()

    try:
        row = conn.execute(
            """
            SELECT
                id,
                user_id,
                storage_name,
                original_filename
            FROM uploaded_files
            WHERE id = ?
            """,
            (data["file_id"],),
        ).fetchone()

    finally:
        conn.close()

    assert row["user_id"] == alice_id
    assert row["original_filename"] == "alice-secret.pdf"

    assert os.path.basename(
        row["storage_name"]
    ) != "../../alice-secret.pdf"


def test_upload_never_uses_client_filename_as_storage_path(
    client,
    temp_db_path,
):
    alice_id = create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

    malicious_filename = (
        "..\\..\\shared-overwrite.pdf"
    )

    response = upload_pdf(
        client,
        headers=headers,
        filename=malicious_filename,
    )

    assert response.status_code == 200

    data = response.json()

    assert (
        data["stored_filename"]
        != malicious_filename
    )

    assert data["stored_filename"].endswith(".pdf")

    absolute_storage = os.path.abspath(
        os.path.join(
            app_module.UPLOAD_DIR,
            alice_id,
            data["stored_filename"],
        )
    )

    assert os.path.exists(
        absolute_storage
    )


def test_upload_rejects_files_over_size_limit(
    client,
    temp_db_path,
):
    create_user(
        "alice@example.com",
        "Alice",
    )

    headers = login_as(
        client,
        "alice@example.com",
    )

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
    create_user(
        "alice@example.com",
        "Alice",
    )

    create_user(
        "bob@example.com",
        "Bob",
    )

    alice_headers = login_as(
        client,
        "alice@example.com",
    )

    bob_headers = login_as(
        client,
        "bob@example.com",
    )

    upload_response = upload_pdf(
        client,
        headers=alice_headers,
        filename="alice.pdf",
    )

    assert upload_response.status_code == 200

    alice_file_id = upload_response.json()["file_id"]

    monkeypatch.setattr(
        app_module,
        "call_llm_with_retry",
        lambda **kwargs: {
            "ok": True
        },
    )

    response = client.post(
        "/api/apps/local/integration-endpoints/Core/InvokeLLM",
        headers=bob_headers,
        json={
            "prompt": "Read this file.",
            "file_urls": [
                f"/api/files/{alice_file_id}",
            ],
        },
    )

    assert response.status_code == 404