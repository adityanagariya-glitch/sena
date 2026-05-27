# Staging Checklist

## Must Fix Before Staging

- [Done] Fix undefined variable in `scripts/memory.py`.
  - In `create_session()`, change the log line from `user_id` to `actor_id`.
  - Current risk: new session creation can fail with `NameError`.

- [Done (2)] Fix blocked-message handling in `scripts/generator.py`.
  - `generate_stream()` uses `MESSAGES["BLOCKED"]`, but `scripts/config.py` does not define `"BLOCKED"`.
  - Either add a `"BLOCKED"` message or use an existing message such as `MESSAGES["HARMFUL"]` / `MESSAGES["ERROR"]`.

- [Done -- not using; cleaned up ] Confirm Bedrock guardrails are actually applied during generation.
  - `GUARDRAIL_ID` and `GUARDRAIL_VERSION` are imported in `scripts/generator.py`.
  - They are not currently passed into `bedrock_runtime.converse_stream()`.
  - Decide whether staging requires generation-time guardrails. If yes, wire the guardrail config into the Bedrock call.

- [Done] Make DynamoDB table names configurable by explicit environment variables.
  - `deployment_lambda/deploy_query_lambda.py` sets `SESSIONS_TABLE` and `TURNS_TABLE`.
  - `scripts/config.py` currently derives table names from `ENV` only.
  - Update config so explicit `SESSIONS_TABLE` / `TURNS_TABLE` env vars are respected.

- [Done] Lock down session history access.
  - `app/main.py` currently returns turns by `session_id`.
  - Add ownership validation so a logged-in user cannot request another user's session by guessing a session id.

- [ ] Set a real staging `JWT_SECRET`.
  - Do not rely on the default local secret in `app/main.py`.
  - Confirm the staging environment injects `JWT_SECRET`.
  For staging — set the env var before running FastAPI:
  powershell# Windows — set for current terminal session
  $env:JWT_SECRET = "your-strong-random-secret-here"
  uvicorn app.main:app --reload --port 8000
  Or create a .env file in your project root:
  JWT_SECRET=your-strong-random-secret-here
  And load it with python-dotenv — add to top of main.py:
  pythonfrom dotenv import load_dotenv
  load_dotenv()
  Generate a strong secret:
  pythonimport secrets
  print(secrets.token_hex(32))
  Run that once, copy the output, use it as your JWT_SECRET.

- [ ] Restrict CORS for staging.
  - `app/main.py` currently uses `allow_origins=["*"]`.
  - Replace with the actual staging frontend origin.

- [Done] Add a dependency manifest.
  - Create `requirements.txt` or `pyproject.toml`.
  - Include required runtime packages such as `boto3`, `fastapi`, `uvicorn`, `PyJWT`, `streamlit`, and `requests`.

## Should Fix Before Staging

- [Done] Remove duplicate login call in `app/streamlit_app.py`.
  - The sign-in flow calls `do_login()` twice.
  - This can create duplicate logs and unnecessary API calls.

- [Done] Return the actual generation `block_reason` from `scripts/pipeline.py`.
  - `block_reason` is set during Step 6 but the final return still uses `None`.

- [Done] Clean up stale commented code in `scripts/pipeline.py`.
  - Old `generate_stream()` try/except code is commented out.
  - Remove it once the current streaming-to-dict flow is confirmed.

- [ ] Align FastAPI and Lambda identity format.
  - FastAPI uses `actor_id = f"{org_id}#{user_id}"`.
  - `scripts/lambda_function.py` passes plain `user_id` to session functions.
  - Pick one identity format for sessions and memory.

- [ ] Confirm staging model ids.
  - Local config uses `au.anthropic.claude-haiku-4-5-20251001-v1:0`.
  - Lambda deploy config uses `au.anthropic.claude-sonnet-4-6`.
  - Verify both are valid and intended in the AWS region.

- [ ] Confirm AgentCore memory id.
  - Local config uses `senaPolicyProceduresMemory-FGIxWL6gih`.
  - Lambda deploy config uses `senaMistyMemory`.
  - Verify the staging memory resource exists and matches the chosen environment.

## Validation Before Staging Sign-off

- [ ] Run syntax checks for all Python files outside `venv`.

- [ ] Start FastAPI locally with the project virtual environment.

- [ ] Verify `/health` returns `200`.

- [ ] Verify `/auth/login` works for an active user and rejects inactive/wrong credentials.

- [ ] Verify `/query/stream` returns:
  - `meta`
  - one or more `token` events
  - final `done` event

- [ ] Verify blocked/off-topic questions return a blocked response.

- [ ] Verify empty-context questions return the configured not-in-KB response.

- [ ] Verify new chats create sessions in DynamoDB.

- [ ] Verify saved turns appear in the correct user's session history.

- [ ] Verify one user cannot read another user's turns.

- [ ] Verify organisation isolation:
  - Sunrise users should retrieve Sunrise + NDIS documents only.
  - Horizons users should retrieve Horizons + NDIS documents only.
  - Superadmin behaviour should match the intended access policy.

- [ ] Verify Streamlit can:
  - log in
  - start a new chat
  - stream an answer
  - list sessions
  - load previous turns
  - rename sessions

- [ ] Verify AWS permissions for staging:
  - Bedrock model invocation
  - Bedrock streaming invocation
  - Bedrock Knowledge Base retrieval
  - DynamoDB sessions and turns tables
  - AgentCore memory read/write
  - CloudWatch logs

- [ ] Verify staging environment variables:
  - `ENV`
  - `AWS_REGION`
  - `JWT_SECRET`
  - `KB_ID`
  - `DS_ID`
  - `GUARDRAIL_ID`
  - `GUARDRAIL_VERSION`
  - `MEMORY_ID`
  - `SESSIONS_TABLE`
  - `TURNS_TABLE`
  - `GENERATION_MODEL`
  - `CLASSIFIER_MODEL`
  - `RERANKER_MODEL`
  - `NUM_RESULTS`
  - `RERANK_TOP`

## Production-Hardening Items

- [ ] Replace `fake_users.json` authentication with the intended staging/prod identity provider.

- [ ] Store passwords securely if local users remain in any staging-like environment.

- [ ] Move secrets and ids out of source defaults where possible.

- [ ] Add structured application logging for request ids, user ids, session ids, and AWS failures.

- [ ] Add automated smoke tests for auth, streaming query, memory save, and org isolation.

- [ ] Add deployment rollback notes for FastAPI, Streamlit, Lambda, and document ingestion Lambdas.
