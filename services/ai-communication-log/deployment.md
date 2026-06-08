# Build and run
docker build -t sena-classifier .
docker run -p 8000:8000 --env-file .env sena-classifier

# API_KEY [middleware]
#python -c "import secrets; print(secrets.token_hex(32))"
# Caller_ID
#aws sts get-caller-identity --query Account --output text


# Lock down CORS (main.py:31)
Currently:
allow_origins=["*"]
Change it to the integrating team's backend domain:
allow_origins=["https://their-backend-domain.com"]


# AWS EC2: 
## 1. Push image to AWS ECR (Elastic Container Registry)
aws ecr create-repository --repository-name sena-classifier --region ap-southeast-2

## 2. Tag and push
docker tag sena-classifier 123456789.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 123456789.dkr.ecr.ap-southeast-2.amazonaws.com
docker push 123456789.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier

## 3. On your EC2 instance (Ubuntu, t3.micro is enough)
sudo apt update && sudo apt install -y docker.io
sudo docker pull 123456789.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier

## 4. Run it — no --env-file, set vars directly (safer)
sudo docker run -d -p 8000:8000 \
  -e API_KEY=your-key \
  -e BEDROCK_MODEL_ID=au.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  -e AWS_REGION=ap-southeast-2 \
  -e CONFIDENCE_THRESHOLD=0.5 \
  -e CONVERSATION_HISTORY_LIMIT=5 \
  123456789.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier

If you attach a Bedrock-enabled IAM role to the EC2 instance, you skip AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY entirely — boto3 picks up the role automatically.




# Deployment Guide:
Step 1 — Push your image to AWS ECR (from your local machine)

# 1. Create the ECR repository (only once)
aws ecr create-repository --repository-name sena-classifier --region ap-southeast-2

# 2. Authenticate Docker to ECR
aws ecr get-login-password --region ap-southeast-2 | docker login --username AWS --password-stdin 038848608811.dkr.ecr.ap-southeast-2.amazonaws.com

# 3. Tag your local image
docker tag sena-ai_log_communication 038848608811.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier

# 4. Push
docker push 038848608811.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier
Step 2 — Launch an EC2 instance (AWS Console)
Go to EC2 → Launch Instance
Choose Ubuntu 22.04, type t3.micro (free tier) or t3.small
Region: ap-southeast-2 (Sydney)
Create or select a key pair (.pem file — save it)
Security Group — open inbound ports:
22 (SSH, your IP only)
8000 (or 443 if you put nginx in front)
Step 3 — Attach a Bedrock IAM Role to EC2 (skip hardcoded keys)
Go to IAM → Roles → Create Role
Trusted entity: EC2
Attach policy: AmazonBedrockFullAccess (or a scoped-down custom policy)
Name it sena-bedrock-role
Go to your EC2 instance → Actions → Security → Modify IAM role → attach sena-bedrock-role
This means you don't need AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY on the server at all.

Step 4 — SSH into EC2 and run the container

# SSH in
ssh -i your-key.pem ubuntu@<EC2-PUBLIC-IP>

# Install Docker
sudo apt update && sudo apt install -y docker.io
sudo systemctl start docker

# Authenticate to ECR (from inside EC2 — works because of the IAM role)
aws ecr get-login-password --region ap-southeast-2 | sudo docker login --username AWS --password-stdin 038848608811.dkr.ecr.ap-southeast-2.amazonaws.com

# Pull the image
sudo docker pull 038848608811.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier

# Run it
sudo docker run -d -p 8000:8000 \
  -e API_KEY=8fd93889f6dc02e5566ad06c16a15e46e4d9d89f8a92958e29e4d353495d77ab \
  -e BEDROCK_MODEL_ID=au.anthropic.claude-sonnet-4-5-20250929-v1:0 \
  -e AWS_REGION=ap-southeast-2 \
  -e CONFIDENCE_THRESHOLD=0.5 \
  -e CONVERSATION_HISTORY_LIMIT=5 \
  --name sena-classifier \
  --restart always \
  038848608811.dkr.ecr.ap-southeast-2.amazonaws.com/sena-classifier
Step 5 — Verify it's live

curl http://<EC2-PUBLIC-IP>:8000/health
Expected: {"status":"ok","version":"1.0.0",...}





# Deployment verification:
## Health check
curl https://your-deployed-url.com/health

## Test classify
curl -X POST https://your-deployed-url.com/api/v1/classify \
  -H "X-API-Key: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "test_001",
    "provider_id": "org_001",
    "current_message": {
      "role": "support_worker",
      "text": "Good morning, ready to help.",
      "timestamp": "2025-06-01T10:00:00Z"
    },
    "history": []
  }'

## Functionality verification
### 1. Health Check (no key needed)

curl https://your-deployed-url.com/health

# Expected:
{ "status": "ok", "version": "1.0.0", "model": "au.anthropic.claude-sonnet-4-5-20250929-v1:0" }
If this fails — the container isn't running or the port isn't exposed.

### 2. Auth Check (confirm middleware is working)
# Without key — should get 401:
curl -X POST https://your-deployed-url.com/api/v1/classify `
  -H "Content-Type: application/json" `
  -d '{"conversation_id":"test","provider_id":"org"}'
Expected: 401 Invalid or missing API key

# With wrong key — should get 401:
curl -X POST https://your-deployed-url.com/api/v1/classify `
  -H "X-API-Key: wrongkey" `
  -H "Content-Type: application/json" `
  -d '{}'
Expected: 401

### 3. Real Classification Test
# Normal:
curl -X POST https://your-deployed-url.com/api/v1/classify `
  -H "X-API-Key: your-key" `
  -H "Content-Type: application/json" `
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
Expected: normal label, high confidence.

# Emergency:
curl -X POST https://your-deployed-url.com/api/v1/classify `
  -H "X-API-Key: your-key" `
  -H "Content-Type: application/json" `
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
Expected: emergency label, high confidence.

# Inappropriate:
curl -X POST https://your-deployed-url.com/api/v1/classify `
  -H "X-API-Key: your-key" `
  -H "Content-Type: application/json" `
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
Expected: inappropriate label, high confidence.

### 4. Run the Full Test Suite Against the Deployed URL
Your existing tests/test_classify.py hits localhost:8000. You can point it at the deployed URL instead:


$env:BASE_URL = "https://your-deployed-url.com"
pytest tests/test_classify.py -v
But first update the test file to read the URL from the environment — open tests/test_classify.py and change the top two lines:

import os
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000") + "/api/v1"
HEALTH_URL = os.getenv("BASE_URL", "http://localhost:8000") + "/health"
Then you can run the same 25+ tests against production without changing any test logic.