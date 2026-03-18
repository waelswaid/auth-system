# Update name returns 200 with updated data
def test_update_name_success(auth_client):
    client, access_token, user = auth_client
    resp = client.patch(
        "/api/users/me",
        json={"name": "Updated Name"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


# GET /users/me reflects the updated name
def test_update_name_persists(auth_client):
    client, access_token, user = auth_client
    client.patch(
        "/api/users/me",
        json={"name": "Persisted Name"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    resp = client.get(
        "/api/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Persisted Name"


# Null name field leaves name unchanged
def test_update_null_name_no_change(auth_client):
    client, access_token, user = auth_client
    original_name = user.name
    resp = client.patch(
        "/api/users/me",
        json={"name": None},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == original_name


# Empty body leaves profile unchanged
def test_update_empty_body(auth_client):
    client, access_token, user = auth_client
    original_name = user.name
    resp = client.patch(
        "/api/users/me",
        json={},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == original_name


# Empty string name is rejected (min_length=1)
def test_update_empty_string_name_rejected(auth_client):
    client, access_token, user = auth_client
    resp = client.patch(
        "/api/users/me",
        json={"name": ""},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert resp.status_code == 422


# Unauthenticated request returns 401
def test_update_profile_unauthenticated(client):
    resp = client.patch("/api/users/me", json={"name": "Hacker"})
    assert resp.status_code == 401
