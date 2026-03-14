import requests

# end-to-end login test script
BASE_URL = "http://127.0.0.1:8000/api"

TEST_USER = {
    "name": "Test User",
    "email": "testuser@example.com",
    "password": "securepassword123",
}


def test_register():
    print("\n--- Test: Register user ---")
    r = requests.post(f"{BASE_URL}/users/create", json=TEST_USER)
    if r.status_code == 200:
        print(f"PASS — user created: {r.json()['email']}")
    elif r.status_code == 409:
        print("INFO — user already exists, continuing with login tests")
    else:
        print(f"FAIL — unexpected status {r.status_code}: {r.json()}")


def test_login_valid():
    print("\n--- Test: Login with correct credentials ---")
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "email": TEST_USER["email"],
        "password": TEST_USER["password"],
    })
    if r.status_code == 200:
        data = r.json()
        token = data.get("access_token")
        token_type = data.get("token_type")
        print(f"PASS — token received")
        print(f"  token_type : {token_type}")
        print(f"  access_token (first 40 chars): {token[:40]}...")
        return token
    else:
        print(f"FAIL — status {r.status_code}: {r.json()}")
        return None


def test_login_wrong_password():
    print("\n--- Test: Login with wrong password ---")
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "email": TEST_USER["email"],
        "password": "wrongpassword999",
    })
    if r.status_code == 401:
        print(f"PASS — correctly rejected: {r.json()['detail']}")
    else:
        print(f"FAIL — expected 401, got {r.status_code}: {r.json()}")


def test_login_nonexistent_email():
    print("\n--- Test: Login with non-existent email ---")
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "email": "nobody@example.com",
        "password": "somepassword123",
    })
    if r.status_code == 401:
        print(f"PASS — correctly rejected: {r.json()['detail']}")
    else:
        print(f"FAIL — expected 401, got {r.status_code}: {r.json()}")


if __name__ == "__main__":
    test_register()
    test_login_valid()
    test_login_wrong_password()
    test_login_nonexistent_email()
    print("\nDone.")
