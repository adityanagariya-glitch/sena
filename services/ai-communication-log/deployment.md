# Deployment Guide — Sena AI Communication Classifier

---

## Quick commands

```bash
# Build and run locally with Docker
docker build -t sena-classifier .
docker run -p 8000:8000 --env-file .env sena-classifier
```

```python
# Generate a new API key
python -c "import secrets; print(secrets.token_hex(32))"
```

```bash
# Confirm your AWS account ID
aws sts get-caller-identity --query Account --output text
```

---

## Before deploying — lock down CORS

In `ai-classifier/app/main.py` line 34, change:
```python
allow_origins=["*"]
```
to the integration team's backend domain:
```python
allow_origins=["https://their-backend-domain.com"]
```
Do this before handing out the URL.

---

## Step 1 — Build and push image to AWS ECR

Run from your local machine.

```bash
# Create the ECR repository (only once)
aws ecr create-repository --repository-name sena-classifier --region ap-southeast-2

# Authenticate Docker to ECR
aws ecr get-login-password --region ap-southeast-2 | \
  docker login --username AWS --password-stdin YOUR_AWS_ACCOUNT_ID.dkr.ecr.ap-southeast-2.amazonaws.com

# Tag your local image
docker tag sena-classifier YOUR_AWS_ACCOUNT_ID.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier

# Push
docker push YOUR_AWS_ACCOUNT_ID.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier
```

Replace `YOUR_AWS_ACCOUNT_ID` with the output of:
```bash
aws sts get-caller-identity --query Account --output text
```

---

## Step 2 — Launch an EC2 instance (AWS Console)

- Go to **EC2 → Launch Instance**
- AMI: Ubuntu 22.04
- Type: `t3.micro` (sufficient) or `t3.small`
- Region: `ap-southeast-2` (Sydney)
- Create or select a key pair (`.pem` file — save it, it's excluded from git via `.gitignore`)
- Security Group — open inbound ports:
  - `22` (SSH — your IP only)
  - `8000` (or `443` if you put nginx in front)

---

## Step 3 — Attach a Bedrock IAM role to EC2

This eliminates the need for hardcoded AWS credentials on the server.

1. Go to **IAM → Roles → Create Role**
2. Trusted entity: `EC2`
3. Attach policy: `AmazonBedrockFullAccess` (or a scoped-down custom policy)
4. Name it `sena-bedrock-role`
5. Go to your EC2 instance → **Actions → Security → Modify IAM role** → attach `sena-bedrock-role`

With this role attached, `boto3` picks up credentials automatically — no `AWS_ACCESS_KEY_ID` or `AWS_SECRET_ACCESS_KEY` needed on the server.

---

## Step 4 — SSH in and run the container

```bash
# SSH into EC2
ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>

# Install Docker
sudo apt update && sudo apt install -y docker.io
sudo systemctl start docker

# Authenticate to ECR (works automatically via the IAM role)
aws ecr get-login-password --region ap-southeast-2 | \
  sudo docker login --username AWS --password-stdin YOUR_AWS_ACCOUNT_ID.dkr.ecr.ap-southeast-2.amazonaws.com

# Pull the image
sudo docker pull YOUR_AWS_ACCOUNT_ID.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier

# Run the container
sudo docker run -d -p 8000:8000 \
  -e API_KEY=YOUR_API_KEY \
  -e BEDROCK_MODEL_ID=au.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  -e AWS_REGION=ap-southeast-2 \
  -e CONFIDENCE_THRESHOLD=0.5 \
  -e CONVERSATION_HISTORY_LIMIT=5 \
  --name sena-classifier \
  --restart always \
  YOUR_AWS_ACCOUNT_ID.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier
```

`YOUR_API_KEY` — generate with `python -c "import secrets; print(secrets.token_hex(32))"`.  
Do not reuse the local dev key in production.

---

## Step 5 — Verify it's live

```bash
curl http://<EC2-PUBLIC-IP>:8000/health
```

Expected:
```json
{ "status": "ok", "version": "1.0.0", "model": "au.anthropic.claude-sonnet-4-5-20250929-v1:0" }
```

---

## Deployment verification

### 1. Health check (no key required)

```bash
curl https://your-deployed-url.com/health
```

Expected: `{ "status": "ok", "version": "1.0.0", "model": "au.anthropic.claude-sonnet-4-5-20250929-v1:0" }`

If this fails — the container isn't running or the port isn't exposed.

---

### 2. Auth check

```bash
# Without key — expect 401
curl -X POST https://your-deployed-url.com/api/v1/classify \
  -H "Content-Type: application/json" \
  -d '{"conversation_id":"test","provider_id":"org"}'

# With wrong key — expect 401
curl -X POST https://your-deployed-url.com/api/v1/classify \
  -H "X-API-Key: wrongkey" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

### 3. Classification smoke tests

**Normal:**
```bash
curl -X POST https://your-deployed-url.com/api/v1/classify \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "deploy_test_001",
    "provider_id": "org_001",
    "current_message": {
      "role": "support_worker",
      "text": "Good morning, ready to help today.",
      "timestamp": "2025-06-01T10:00:00Z"
    },
    "history": []
  }'
```
Expected: `classifications[0].label = "normal"`, `risk.level = "low"`, `breakdown.detected = false`

**Emergency / high risk:**
```bash
curl -X POST https://your-deployed-url.com/api/v1/classify \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "deploy_test_002",
    "provider_id": "org_001",
    "current_message": {
      "role": "client",
      "text": "I dont want to live anymore.",
      "timestamp": "2025-06-01T10:00:00Z"
    },
    "history": []
  }'
```
Expected: `classifications[0].label = "emergency"`, `risk.level = "critical"`, `recommended_action` non-null

**Inappropriate / communication breakdown:**
```bash
curl -X POST https://your-deployed-url.com/api/v1/classify \
  -H "X-API-Key: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "deploy_test_003",
    "provider_id": "org_001",
    "current_message": {
      "role": "support_worker",
      "text": "I dont want to deal with you. Just do what I say.",
      "timestamp": "2025-06-01T10:00:00Z"
    },
    "history": []
  }'
```
Expected: `classifications[0].label = "inappropriate"`, `risk.level = "high"` or `"critical"`

---

### 4. Run the full test suite against the deployed URL

The test suite in `ai-classifier/tests/test_classify.py` reads `BASE_URL` from the environment, defaulting to `localhost:8000`. Point it at the deployed instance:

```powershell
# PowerShell
$env:BASE_URL = "https://your-deployed-url.com"
$env:API_KEY  = "YOUR_API_KEY"
cd ai-classifier
pytest tests/test_classify.py -v
```

```bash
# bash / Linux
export BASE_URL="https://your-deployed-url.com"
export API_KEY="YOUR_API_KEY"
cd ai-classifier
pytest tests/test_classify.py -v
```

This runs all tests (normal, emergency, inappropriate, sentiment, risk, breakdown, outcome, multi-label, history trimming, validation) against the live server without changing any test code.
