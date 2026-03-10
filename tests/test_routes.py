import io


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json["status"] == "ok"


def test_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"Find Your Next Job" in resp.data


def test_search_no_input(client):
    resp = client.post("/search", data={}, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Please provide" in resp.data or b"Find Your Next Job" in resp.data


def test_search_with_text(client):
    resp = client.post("/search", data={
        "resume_text": "Python developer with 5 years experience in Django and AWS",
        "location": "Remote",
    }, follow_redirects=True)
    assert resp.status_code == 200


def test_bad_file_upload(client):
    data = {
        "resume_file": (io.BytesIO(b"fake content"), "resume.txt"),
    }
    resp = client.post("/search", data=data, content_type="multipart/form-data",
                       follow_redirects=True)
    assert resp.status_code == 200
    assert b"Invalid file type" in resp.data or b"Find Your Next Job" in resp.data


# --- Auth ---

def test_register(client):
    resp = client.post("/register", data={
        "email": "new@example.com",
        "password": "password123",
        "name": "New User",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Account created" in resp.data


def test_register_duplicate(client):
    client.post("/register", data={
        "email": "dup@example.com",
        "password": "password123",
    })
    client.get("/logout")  # Log out so we can try registering again
    resp = client.post("/register", data={
        "email": "dup@example.com",
        "password": "password456",
    }, follow_redirects=True)
    assert b"already exists" in resp.data


def test_register_short_password(client):
    resp = client.post("/register", data={
        "email": "short@example.com",
        "password": "abc",
    }, follow_redirects=True)
    assert b"at least 8" in resp.data


def test_login_logout(client):
    # Register
    client.post("/register", data={
        "email": "login@example.com",
        "password": "password123",
    })
    # Logout
    client.get("/logout", follow_redirects=True)
    # Login
    resp = client.post("/login", data={
        "email": "login@example.com",
        "password": "password123",
    }, follow_redirects=True)
    assert resp.status_code == 200


def test_login_bad_password(client):
    client.post("/register", data={
        "email": "bad@example.com",
        "password": "password123",
    })
    client.get("/logout")
    resp = client.post("/login", data={
        "email": "bad@example.com",
        "password": "wrongpassword",
    }, follow_redirects=True)
    assert b"Invalid" in resp.data


# --- Auth-protected routes ---

def test_alerts_requires_login(client):
    resp = client.get("/alerts", follow_redirects=True)
    assert b"Log In" in resp.data


def test_alerts_page(auth_client):
    resp = auth_client.get("/alerts")
    assert resp.status_code == 200
    assert b"Job Alerts" in resp.data


def test_create_alert(auth_client):
    resp = auth_client.post("/alerts", data={
        "query": "Python Developer",
        "location": "Remote",
        "frequency": "daily",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Alert created" in resp.data


def test_settings_requires_login(client):
    resp = client.get("/settings", follow_redirects=True)
    assert b"Log In" in resp.data


def test_settings_page(auth_client):
    resp = auth_client.get("/settings")
    assert resp.status_code == 200
    assert b"Settings" in resp.data


def test_save_settings(auth_client):
    resp = auth_client.post("/settings", data={
        "name": "Updated Name",
        "timezone": "US/Eastern",
        "max_commute_minutes": "45",
        "seniority_tier": "IC3",
        "blocked_companies": "BadCo",
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert b"Settings saved" in resp.data
