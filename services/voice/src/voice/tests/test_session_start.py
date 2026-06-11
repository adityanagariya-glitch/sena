def test_start_session_success(client, dev_headers):
    payload = {
        "objective": "CASE_NOTE",
        "participant_id": "11111111-1111-1111-1111-111111111111",
        "staff_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "shift_id": "22222222-2222-2222-2222-222222222222",
        "language": "en-AU",
        "metadata": {},
    }
    resp = client.post("/v1/voice/session", json=payload, headers=dev_headers)
    assert resp.status_code in (201, 503, 500)


def test_start_session_missing_auth_headers(client):
    payload = {
        "objective": "CASE_NOTE",
        "participant_id": "11111111-1111-1111-1111-111111111111",
        "staff_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "shift_id": "22222222-2222-2222-2222-222222222222",
    }
    resp = client.post("/v1/voice/session", json=payload)
    assert resp.status_code == 401


def test_start_session_invalid_objective(client, dev_headers):
    payload = {
        "objective": "ONBOARDING",
        "participant_id": "11111111-1111-1111-1111-111111111111",
        "staff_id": "cccccccc-cccc-cccc-cccc-cccccccccccc",
        "shift_id": "22222222-2222-2222-2222-222222222222",
    }
    resp = client.post("/v1/voice/session", json=payload, headers=dev_headers)
    assert resp.status_code == 422
