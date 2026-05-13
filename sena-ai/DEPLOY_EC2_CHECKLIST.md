# EC2 Demo Deployment — Onboarding Service

Target: existing EC2 instance, Docker Compose, port **8083**. Demo grade.

---

## 0. Prereqs (one-time, on the EC2 box)

- [ ] **SSH in** (or `aws ssm start-session --target i-xxx` if SSM enabled).
- [ ] **Security Group**: inbound TCP **8083** open to demo client IP (or `0.0.0.0/0` for public demo — restrict after). Outbound `443` open for Gemini API + webhook.
- [ ] **Disk free**: `df -h /` — need ~2 GB free for Docker image + Redis volume.
- [ ] **Docker + Compose plugin installed**:
  ```bash
  # Amazon Linux 2023
  sudo dnf install -y docker
  sudo systemctl enable --now docker
  sudo usermod -aG docker $USER && newgrp docker
  DOCKER_CONFIG=${DOCKER_CONFIG:-$HOME/.docker}
  mkdir -p $DOCKER_CONFIG/cli-plugins
  curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
    -o $DOCKER_CONFIG/cli-plugins/docker-compose
  chmod +x $DOCKER_CONFIG/cli-plugins/docker-compose
  docker compose version   # verify
  ```
  (Ubuntu: `sudo apt-get install -y docker.io docker-compose-plugin`.)

---

## 1. Get code onto the box

Pick **one**:

- **Git pull (preferred):**
  ```bash
  git clone <your-repo-url> sena
  cd sena/SENA_AI/sena-ai
  ```
- **scp tarball (no git):**
  ```bash
  # on your laptop
  tar -czf sena-ai.tgz --exclude='.venv' --exclude='__pycache__' --exclude='.git' SENA_AI/sena-ai
  scp sena-ai.tgz ec2-user@<EC2_DNS>:~
  # on EC2
  tar -xzf sena-ai.tgz && cd SENA_AI/sena-ai
  ```

---

## 2. Configure env

- [ ] `cp .env.deploy.example .env`
- [ ] Edit `.env`:
  - `SENA_AI_GEMINI_API_KEY` — paste real key
  - `SENA_AI_APP_WEBHOOK_URL` + `SENA_AI_APP_WEBHOOK_SECRET` — real values (or a webhook.site URL for demo)
- [ ] `chmod 600 .env`

---

## 3. Build + run

```bash
docker compose -f docker-compose.deploy.yml up -d --build
docker compose -f docker-compose.deploy.yml ps
docker compose -f docker-compose.deploy.yml logs -f sena-onboarding
```

Expected: `Application startup complete` and `Uvicorn running on http://0.0.0.0:8083`.

---

## 4. Smoke test

```bash
# from EC2
curl -s http://localhost:8083/health/live   # → {"status":"ok"} or 200
curl -s http://localhost:8083/health/ready

# from your laptop (replace public DNS)
curl -s http://<EC2_PUBLIC_DNS>:8083/health/live
curl -s http://<EC2_PUBLIC_DNS>:8083/docs    # Swagger UI loads
```

If `/health/live` returns 200 → demo is live.

---

## 5. Hand off to client team

Give them:
- **Base URL**: `http://<EC2_PUBLIC_DNS>:8083`
- **WS URL**: `ws://<EC2_PUBLIC_DNS>:8083/ws/onboarding/{session_id}`
- **OpenAPI**: `http://<EC2_PUBLIC_DNS>:8083/openapi.json`

---

## 6. If something breaks (1-min triage)

| Symptom | Check |
|---|---|
| Container exits immediately | `docker compose logs sena-onboarding` — usually missing env var |
| `502`/connection refused from outside | Security Group inbound 8083 missing |
| `/health/ready` fails | `docker compose logs redis` — Redis not up yet, wait 10s |
| Gemini calls fail | `SENA_AI_GEMINI_API_KEY` wrong, or no outbound 443 in SG |
| Webhook never fires | `SENA_AI_APP_WEBHOOK_URL` unreachable from EC2 |

Restart cleanly:
```bash
docker compose -f docker-compose.deploy.yml down
docker compose -f docker-compose.deploy.yml up -d --build
```

---

## 7. Demo-only shortcuts taken (fix before any real env)

- HTTP only (no TLS). For prod: put ALB or Caddy/Nginx in front with ACM cert; WS becomes `wss://`.
- Single container, no autoscaling, no health-based restart at ALB level.
- Redis volume on the box — if EC2 dies, sessions die. Demo data is ephemeral, so OK.
- `.env` on disk — for prod move to AWS Secrets Manager / SSM Parameter Store.
- Security group may be wide-open — narrow to client IPs after handoff.
