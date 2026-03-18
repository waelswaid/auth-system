def _login(client, email, password):
    resp = client.post("/api/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200
    return resp.json()["access_token"]


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


# Correct current password changes the password successfully
def test_change_password_success(client, verified_user):
    user, password = verified_user
    token = _login(client, user.email, password)

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": password, "new_password": "newsecurepassword123"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200

    # Can login with new password
    new_token = _login(client, user.email, "newsecurepassword123")
    assert new_token


# Old tokens are rejected after password change
def test_change_password_invalidates_old_tokens(client, verified_user):
    user, password = verified_user
    token = _login(client, user.email, password)

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": password, "new_password": "newsecurepassword123"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 200

    # Old token should be rejected
    resp = client.get("/api/users/me", headers=_auth_header(token))
    assert resp.status_code == 401


# Wrong current password returns 400
def test_change_password_wrong_current(client, verified_user):
    user, password = verified_user
    token = _login(client, user.email, password)

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "wrongpassword123", "new_password": "newsecurepassword123"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 400


# New password too short returns 422
def test_change_password_new_too_short(client, verified_user):
    user, password = verified_user
    token = _login(client, user.email, password)

    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": password, "new_password": "short"},
        headers=_auth_header(token),
    )
    assert resp.status_code == 422


# Unauthenticated request returns 401
def test_change_password_unauthenticated(client):
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "anything", "new_password": "newsecurepassword123"},
    )
    assert resp.status_code == 401


# Can login with old password fails after change
def test_change_password_old_password_rejected(client, verified_user):
    user, password = verified_user
    token = _login(client, user.email, password)

    client.post(
        "/api/auth/change-password",
        json={"current_password": password, "new_password": "newsecurepassword123"},
        headers=_auth_header(token),
    )

    resp = client.post(
        "/api/auth/login",
        json={"email": user.email, "password": password},
    )
    assert resp.status_code == 401
