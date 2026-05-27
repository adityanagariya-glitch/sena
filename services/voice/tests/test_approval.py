def test_approval_requires_manager_role(client, dev_headers):
    payload = {
        "approval_item_id": "55555555-5555-5555-5555-555555555555",
        "decision": "APPROVED",
        "reviewer_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "review_notes": "ok",
    }
    resp = client.post("/v1/approval/decision", json=payload, headers=dev_headers)
    assert resp.status_code == 403


def test_reject_requires_reason(client, manager_headers):
    payload = {
        "approval_item_id": "55555555-5555-5555-5555-555555555555",
        "decision": "REJECTED",
        "reviewer_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
        "review_notes": "",
    }
    resp = client.post("/v1/approval/decision", json=payload, headers=manager_headers)
    assert resp.status_code == 422
