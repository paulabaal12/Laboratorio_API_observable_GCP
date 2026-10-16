import time

VALID = {"customer_id": "c-001", "customer_tier": "pro", "category": "electronics", "amount": 129.99}
REQUIRED_LOG_FIELDS = {
    "severity", "message", "request_id", "endpoint", "status_code", "outcome",
    "error_type", "latency_ms", "customer_tier", "category", "amount",
}


def create(client, **overrides):
    return client.post("/orders", json={**VALID, **overrides}, headers={"X-Request-ID": "rid-create"})


def test_create_201_and_log_format(client, last_log):
    resp = create(client)
    assert resp.status_code == 201
    assert resp.headers["X-Request-ID"] == "rid-create"
    order = resp.get_json()
    assert order["order_id"].startswith("ord-pro-electronics-12999-")
    assert order["status"] == "created"

    log = last_log()
    assert REQUIRED_LOG_FIELDS <= log.keys()
    assert log["severity"] == "INFO"
    assert log["message"] == "request_completed"
    assert log["request_id"] == "rid-create"
    assert log["endpoint"] == "POST /orders"
    assert log["status_code"] == 201
    assert log["outcome"] == "success"
    assert log["error_type"] is None
    assert isinstance(log["latency_ms"], float)
    assert (log["customer_tier"], log["category"], log["amount"]) == ("pro", "electronics", 129.99)


def test_get_200_resolves_id_without_shared_memory(client, last_log):
    order_id = create(client).get_json()["order_id"]
    resp = client.get(f"/orders/{order_id}", headers={"X-Request-ID": "rid-get"})
    assert resp.status_code == 200
    assert resp.get_json()["amount"] == 129.99
    log = last_log()
    assert log["endpoint"] == "GET /orders/{id}" and log["category"] == "electronics"


def test_cancel_200_then_409(client, last_log):
    order_id = create(client).get_json()["order_id"]
    assert client.post(f"/cancel/{order_id}").status_code == 200
    assert client.get(f"/orders/{order_id}").get_json()["status"] == "cancelled"

    resp = client.post(f"/cancel/{order_id}", headers={"X-Request-ID": "rid-409"})
    assert resp.status_code == 409
    log = last_log()
    assert (log["severity"], log["outcome"], log["error_type"]) == ("WARNING", "client_error", "already_cancelled")


def test_cancel_digital_409(client, last_log):
    order_id = create(client, category="digital").get_json()["order_id"]
    assert client.post(f"/cancel/{order_id}").status_code == 409
    assert last_log()["error_type"] == "order_fulfilled"


def test_400_invalid_payloads(client, last_log):
    cases = [
        (client.post("/orders", data="not json", content_type="application/json"), "invalid_json"),
        (create(client, customer_id=""), "missing_field"),
        (create(client, customer_tier="gold"), "invalid_field"),
        (create(client, category="cars"), "invalid_field"),
        (create(client, amount=-5), "invalid_amount"),
        (create(client, amount="10"), "invalid_amount"),
    ]
    for resp, error_type in cases:
        assert resp.status_code == 400, error_type
        assert resp.get_json()["error"] == error_type
    log = last_log()
    assert (log["severity"], log["outcome"], log["category"]) == ("WARNING", "client_error", "electronics")


def test_404_unknown_or_tampered_ids(client, last_log):
    order_id = create(client).get_json()["order_id"]
    tampered = order_id.replace("-12999-", "-99999-")
    for path in ("/orders/ord-does-not-exist", f"/orders/{tampered}", "/cancel/xyz", "/nope"):
        method = client.post if path.startswith("/cancel") else client.get
        assert method(path).status_code == 404, path
    assert last_log()["error_type"] == "route_not_found"


def test_405_wrong_method(client, last_log):
    assert client.get("/orders").status_code == 405
    assert last_log()["outcome"] == "client_error"


def test_500_simulated_failure(client, last_log, monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "1")
    resp = create(client)
    assert resp.status_code == 500
    log = last_log()
    assert (log["severity"], log["outcome"], log["error_type"]) == ("ERROR", "server_error", "simulated_failure")


def test_failure_rate_does_not_mask_client_errors(client, monkeypatch):
    monkeypatch.setenv("FAILURE_RATE", "1")
    assert create(client, amount=0).status_code == 400


def test_extra_latency(client, last_log, monkeypatch):
    monkeypatch.setenv("EXTRA_LATENCY_MS", "120")
    started = time.perf_counter()
    create(client)
    assert time.perf_counter() - started >= 0.12
    assert last_log()["latency_ms"] >= 120


def test_missing_request_id_is_generated(client, last_log):
    client.post("/orders", json=VALID)
    assert last_log()["request_id"].startswith("missing-")
