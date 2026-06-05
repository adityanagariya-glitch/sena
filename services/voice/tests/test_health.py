def test_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "alive"


def test_health_ready(client):
    resp = client.get("/health/ready")
    assert resp.status_code in (200, 503, 500)
