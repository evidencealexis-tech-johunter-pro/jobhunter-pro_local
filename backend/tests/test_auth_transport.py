import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(
            os.path.abspath(__file__)
        )
    ),
)

import main as app_module
from auth import AUTH_COOKIE_NAME, CSRF_HEADER_NAME, hash_password


TEST_PASSWORD = "CorrectHorseBatteryStaple!"


def create_user(email: str, name: str) -> str:
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


def login(client, email: str):
    response = client.post(
        "/api/apps/local/auth/login",
        json={
            "email": email,
            "password": TEST_PASSWORD,
        },
    )

    assert response.status_code == 200
    assert response.cookies.get(AUTH_COOKIE_NAME)
    return response


def test_login_sets_httponly_lax_session_cookie(client, temp_db_path):
    create_user("primary@example.com", "Primary")

    response = login(client, "primary@example.com")

    set_cookie = response.headers["set-cookie"].lower()

    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie


def test_cookie_authenticates_without_authorization_header(client, temp_db_path):
    create_user("primary@example.com", "Primary")

    login(client, "primary@example.com")

    response = client.get("/api/apps/local/entities/User/me")

    assert response.status_code == 200
    assert response.json()["email"] == "primary@example.com"


def test_csrf_endpoint_returns_token_for_cookie_session(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")

    response = client.get("/api/apps/local/auth/csrf")

    assert response.status_code == 200
    assert response.json()["header_name"] == CSRF_HEADER_NAME
    assert len(response.json()["csrf_token"]) == 64


def test_cookie_mutation_requires_csrf_token(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")

    response = client.post(
        "/api/apps/local/entities/Resume",
        json={
            "file_name": "resume.pdf",
            "skills": ["Python"],
            "active": True,
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"


def test_cookie_mutation_accepts_valid_csrf_token(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")

    csrf_response = client.get("/api/apps/local/auth/csrf")
    csrf_token = csrf_response.json()["csrf_token"]

    response = client.post(
        "/api/apps/local/entities/Resume",
        headers={CSRF_HEADER_NAME: csrf_token},
        json={
            "file_name": "resume.pdf",
            "skills": ["Python"],
            "active": True,
        },
    )

    assert response.status_code == 200
    assert response.json()["user_id"]


def test_bearer_auth_remains_supported(client, temp_db_path):
    create_user("primary@example.com", "Primary")

    response = login(client, "primary@example.com")
    token = response.json()["access_token"]

    # A separate client avoids automatically carrying the session cookie.
    from fastapi.testclient import TestClient

    api_client = TestClient(app_module.app)
    me = api_client.get(
        "/api/apps/local/entities/User/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert me.status_code == 200
    assert me.json()["email"] == "primary@example.com"


def test_logout_revokes_cookie_session_and_clears_cookie(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")

    csrf_token = client.get(
        "/api/apps/local/auth/csrf"
    ).json()["csrf_token"]

    logout_response = client.post(
        "/api/apps/auth/logout",
        headers={CSRF_HEADER_NAME: csrf_token},
    )

    assert logout_response.status_code == 200

    me = client.get("/api/apps/local/entities/User/me")
    assert me.status_code == 401


def test_cookie_mutation_rejects_untrusted_origin(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")
    csrf_token = client.get("/api/apps/local/auth/csrf").json()["csrf_token"]

    response = client.post(
        "/api/apps/local/entities/Resume",
        headers={
            CSRF_HEADER_NAME: csrf_token,
            "Origin": "https://evil.example",
        },
        json={"file_name": "resume.pdf", "skills": ["Python"], "active": True},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Untrusted request origin"


def test_cookie_mutation_rejects_cross_site_fetch_metadata(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")
    csrf_token = client.get("/api/apps/local/auth/csrf").json()["csrf_token"]

    response = client.post(
        "/api/apps/local/entities/Resume",
        headers={
            CSRF_HEADER_NAME: csrf_token,
            "Sec-Fetch-Site": "cross-site",
        },
        json={"file_name": "resume.pdf", "skills": ["Python"], "active": True},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Cross-site request blocked"


def test_cookie_mutation_cannot_claim_another_user(client, temp_db_path):
    primary_user_id = create_user("primary@example.com", "Primary")
    create_user("secondary@example.com", "Secondary")
    login(client, "primary@example.com")
    csrf_token = client.get("/api/apps/local/auth/csrf").json()["csrf_token"]

    response = client.post(
        "/api/apps/local/entities/Resume",
        headers={CSRF_HEADER_NAME: csrf_token},
        json={
            "file_name": "resume.pdf",
            "skills": ["Python"],
            "active": True,
            "user_id": "attacker-selected-user",
        },
    )

    assert response.status_code == 200
    assert response.json()["user_id"] == primary_user_id


def test_cookie_logout_requires_csrf(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")

    response = client.post("/api/apps/auth/logout")

    assert response.status_code == 403
    assert response.json()["detail"] == "CSRF validation failed"


def test_security_headers_are_present(client, temp_db_path):
    create_user("primary@example.com", "Primary")
    login(client, "primary@example.com")

    response = client.get("/api/apps/local/entities/User/me")

    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"