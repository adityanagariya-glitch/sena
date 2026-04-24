curl -s -X POST http://localhost:8084/v1/case-review/context `
  -H "Content-Type: application/json" `
  -H "X-Tenant-Id: aaaaaaaa-0000-0000-0000-000000000001" `
  -H "X-User-Id: bbbbbbbb-0000-0000-0000-000000000002" `
  -d '{"staff_id":"cccccccc-0000-0000-0000-000000000003","client_id":"dddddddd-0000-0000-0000-000000000004","limit":10}'
