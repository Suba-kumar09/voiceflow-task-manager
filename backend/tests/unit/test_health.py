import uuid


def test_health_is_ok_without_database(make_client):
    client = make_client("")
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ready_reports_database_not_configured(make_client):
    client = make_client("")
    resp = client.get("/api/v1/ready")
    assert resp.status_code == 503
    assert resp.json() == {
        "status": "not_ready",
        "database": "not_configured",
        "migrations": "unknown",
    }


def test_ready_reports_unreachable_database(make_client):
    # Port 1 on localhost: nothing listens there, so the connection must fail fast.
    client = make_client("postgresql+psycopg://nobody:nopass@127.0.0.1:1/none?connect_timeout=2")
    resp = client.get("/api/v1/ready")
    assert resp.status_code == 503
    assert resp.json()["database"] == "unavailable"


def test_unknown_route_uses_standard_error_shape(make_client):
    client = make_client("")
    resp = client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "not_found"
    assert body["error"]["request_id"] == resp.headers["X-Request-ID"]


def test_request_id_is_echoed_when_valid_and_replaced_when_not(make_client):
    client = make_client("")
    rid = str(uuid.uuid4())
    assert (
        client.get("/api/v1/health", headers={"X-Request-ID": rid}).headers["X-Request-ID"] == rid
    )

    bad = client.get("/api/v1/health", headers={"X-Request-ID": "not-a-uuid\nInjected: x"})
    returned = bad.headers["X-Request-ID"]
    assert returned != "not-a-uuid\nInjected: x"
    uuid.UUID(returned)  # raises if not a UUID
