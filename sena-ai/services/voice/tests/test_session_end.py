def test_end_session_not_found(client, dev_headers):
    payload = {
        "session_id": "44444444-4444-4444-4444-444444444444",
        "ended_at": "2026-04-07T10:30:00Z",
        "client_timezone": "Australia/Sydney",
    }
    resp = client.post("/v1/voice/session/end", json=payload, headers=dev_headers)
    assert resp.status_code == 404
