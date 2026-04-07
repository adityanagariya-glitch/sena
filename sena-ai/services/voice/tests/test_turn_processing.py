def test_turn_validation_error_empty_transcript(client, dev_headers):
    payload = {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "transcript": "",
        "transcript_confidence": 0.91,
        "audio_duration_ms": 5000,
        "sequence_number": 1,
        "timestamp": "2026-04-07T10:00:00Z",
    }
    resp = client.post("/v1/voice/session/turn", json=payload, headers=dev_headers)
    assert resp.status_code == 422


def test_turn_unknown_session(client, dev_headers):
    payload = {
        "session_id": "33333333-3333-3333-3333-333333333333",
        "transcript": "Participant was calm and engaged.",
        "transcript_confidence": 0.91,
        "audio_duration_ms": 5000,
        "sequence_number": 1,
        "timestamp": "2026-04-07T10:00:00Z",
    }
    resp = client.post("/v1/voice/session/turn", json=payload, headers=dev_headers)
    assert resp.status_code in (404, 503, 500)
