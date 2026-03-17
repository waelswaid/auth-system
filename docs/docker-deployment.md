# Docker Deployment Guide

This document explains what Docker does to your system, how every piece of the Docker setup works, and step-by-step instructions for deploying on an AWS Linux host.

---

## Table of Contents

1. [What Docker Does to Your System](#what-docker-does-to-your-system)
2. [How the Docker Setup Works](#how-the-docker-setup-works)
3. [Environment Variables](#environment-variables)
4. [Deploy on AWS Linux](#deploy-on-aws-linux)
5. [Managing the Deployment](#managing-the-deployment)
6. [Troubleshooting](#troubleshooting)

---

## What Docker Does to Your System

### The core idea

Docker packages your application and all its dependencies into isolated units called **containers**. Each container runs in its own filesystem, network, and process space — completely separate from the host machine and from other containers. This means:

- **No system-wide installs.** You do not install Python, Postgres, or Redis on the host. Each runs inside its own container with the exact version specified in the config.
- **No dependency conflicts.** The Python packages, Postgres version, and Redis version used by this project cannot collide with anything else on the machine.
- **Reproducible environments.** The same image built on your laptop will behave identically on the AWS server.

### What gets installed on the host

The only things installed on the host machine are:

| Component | Purpose |
|-----------|---------|
| **Docker Engine** | The runtime that builds and runs containers |
| **Docker Compose plugin** | Reads `docker-compose.yml` and orchestrates multi-container setups |

Everything else — Python 3.14, your app code, Postgres 16, Redis 7, pip packages — lives inside containers and does not touch the host filesystem (except through explicitly defined volumes).

### What Docker creates on the host

Docker stores its data under `/var/lib/docker/`. Here's what accumulates over time:

| Artifact | What it is | How it grows |
|----------|-----------|--------------|
| **Images** | Read-only snapshots used to create containers. `python:3.14-slim`, `postgres:16-alpine`, `redis:7-alpine`, and your built app image. | ~300-500 MB total for this project. Old images accumulate if you rebuild frequently. |
| **Containers** | Running (or stopped) instances of images. | Minimal disk use beyond the image. |
| **Volumes** | Persistent storage that survives container restarts. This project uses one: `pgdata` for Postgres data files. | Grows with your database size. |
| **Build cache** | Cached layers from `docker build` to speed up rebuilds. | Can grow large over time. |
| **Networks** | Virtual networks that let containers talk to each other by service name. Docker Compose creates one automatically. | Negligible disk use. |

To reclaim disk space at any time:

```bash
# Remove unused images, stopped containers, and build cache
docker system prune -a

# See disk usage breakdown
docker system df
```

### Networking

Docker Compose creates a private virtual network for the three services. Within this network:

- Containers address each other by service name (`postgres`, `redis`, `app`) — Docker's internal DNS resolves these.
- Only the `app` service exposes a port to the host (`8000:8000`). Postgres and Redis are **not** accessible from outside the Docker network, which is a security benefit.
- From the host machine, you reach the API at `http://localhost:8000`. From the internet, you reach it at `http://<your-server-ip>:8000`.

### Process isolation

- Each container runs its own process tree. The app container runs `uvicorn`, the postgres container runs the Postgres server, and the redis container runs the Redis server.
- Containers cannot see each other's filesystems or processes.
- The app container runs as a non-root user (`appuser`) for security — even if someone exploits the application, they cannot gain root access inside the container.

---

## How the Docker Setup Works

### File overview

```
FastAPIapp/
  Dockerfile              # Instructions to build the app image
  docker-compose.yml      # Defines all services and how they connect
  entrypoint.sh           # Startup script: runs migrations, then starts the server
  .dockerignore           # Files excluded from the Docker build context
  .env.docker.example     # Template for environment variables
  requirements-prod.txt   # Python dependencies (production only)
```

### Dockerfile — multi-stage build

The Dockerfile uses a **two-stage build** to keep the final image small:

**Stage 1 (builder):** Uses `python:3.14-slim` to create a virtual environment and install all pip packages from `requirements-prod.txt`. This stage includes compilers and build tools needed by some packages (like `psycopg2-binary`), but these tools are discarded after this stage.

**Stage 2 (runtime):** Starts from a fresh `python:3.14-slim` image. It installs only `libpq5` (the Postgres client library needed at runtime), copies the pre-built virtual environment from stage 1, copies your application code, and sets file ownership to `appuser`. The result is a lean image without compilers, build headers, or pip cache.

Key details:
- `RUN chown -R appuser:appuser /app` — Ensures the non-root `appuser` owns all application files, so Alembic can run migrations and Python can write `__pycache__` files.
- `USER appuser` — All subsequent commands (and the running application) execute as this non-root user.
- `ENTRYPOINT ["/entrypoint.sh"]` — The container always starts by running `entrypoint.sh`.

### docker-compose.yml — service orchestration

Defines three services:

**postgres:**
- Uses `postgres:16-alpine` (lightweight Alpine Linux variant).
- Stores data in a named volume `pgdata` so your database survives container restarts.
- Health check: `pg_isready` — the app container will not start until Postgres reports healthy.
- Password comes from `${POSTGRES_PASSWORD:-postgres}` — reads from your `.env` file, falls back to `postgres` if unset.

**redis:**
- Uses `redis:7-alpine`.
- Used for rate limiting (see `docs/redis-rate-limiting.md`).
- Health check: `redis-cli ping` — must respond before the app starts.
- No persistent volume — rate limiting data is ephemeral by design.

**app:**
- Built from the Dockerfile in the project root.
- Loads your `.env` file via `env_file`, then the `environment` block sets/overrides Docker-specific variables (`DATABASE_URL`, `REDIS_URL`, `ENVIRONMENT`).
- `DATABASE_URL` uses the same `${POSTGRES_PASSWORD}` variable as the postgres service, so they always match.
- `depends_on` with `condition: service_healthy` ensures Postgres and Redis are ready before the app container starts.
- `ports: "8000:8000"` maps host port 8000 to container port 8000.
- `restart: unless-stopped` on all services means they automatically restart after crashes or host reboots (unless you explicitly `docker compose stop`).

### entrypoint.sh — startup sequence

```bash
#!/bin/sh
set -e
alembic upgrade head          # Apply any pending database migrations
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Every time the app container starts, it:
1. Runs all pending Alembic migrations (`alembic upgrade head`). This is safe to run repeatedly — if the database is already up to date, it does nothing.
2. Starts the Uvicorn ASGI server. The `exec` replaces the shell process with Uvicorn so that signals (like `docker compose stop`) are forwarded correctly.

### .dockerignore — build context exclusions

These files/directories are excluded from the Docker image:
- `.env` and `.env.*` — secrets must not be baked into the image
- `.git/`, `tests/`, `test-client/`, `docs/` — not needed at runtime
- `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.coverage`, `htmlcov/` — build artifacts
- `venv/`, `.venv/` — local virtual environments (the image builds its own)

---

## Environment Variables

Copy the template and fill in real values:

```bash
cp .env.docker.example .env
```

| Variable | Used by | Description |
|----------|---------|-------------|
| `POSTGRES_PASSWORD` | postgres service + app `DATABASE_URL` | Password for the Postgres `postgres` user. **Change this from the default.** |
| `JWT_SECRET_KEY` | app | Secret key for signing JWT tokens. Generate with: `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `MAILGUN_API_KEY` | app | Your Mailgun API key for sending emails. |
| `MAILGUN_DOMAIN` | app | Your Mailgun sending domain (e.g., `mg.yourdomain.com`). |
| `MAILGUN_FROM_EMAIL` | app | The "from" address on outgoing emails. |
| `APP_BASE_URL` | app | Public URL of your deployed instance (e.g., `https://yourdomain.com`). Used in email links. |
| `ENVIRONMENT` | app | Set to `production` in Docker. Already set in `docker-compose.yml`, but can be overridden in `.env`. |

Variables set in the `environment` block of `docker-compose.yml` (`DATABASE_URL`, `REDIS_URL`, `ENVIRONMENT`) override any same-named variables from `.env`. You do not need to set those three in `.env`.

---

## Deploy on AWS Linux

### Prerequisites

- An AWS EC2 instance running Amazon Linux 2023 (or Amazon Linux 2, or Ubuntu)
- SSH access to the instance
- Security group allowing inbound traffic on port 22 (SSH) and port 8000 (API)
- Your project code available via git

### Step 1: Install Docker

**Amazon Linux 2023 / Amazon Linux 2:**

```bash
# Install Docker
sudo yum install -y docker

# Start Docker and enable it on boot
sudo systemctl enable --now docker

# Add your user to the docker group (so you don't need sudo for every command)
sudo usermod -aG docker $USER

# IMPORTANT: Log out and back in for the group change to take effect
exit
```

After logging back in, verify:

```bash
docker --version
```

### Step 2: Install Docker Compose

```bash
# Download the Compose plugin
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-$(uname -m) \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose

# Verify
docker compose version
```

### Step 3: Clone the repository

```bash
cd ~
git clone https://github.com/waelswaid/auth-system.git FastAPIapp
cd FastAPIapp
```

### Step 4: Configure environment variables

```bash
cp .env.docker.example .env
nano .env   # or vim .env
```

At minimum, change:
- `POSTGRES_PASSWORD` — set a strong password
- `JWT_SECRET_KEY` — generate one: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`
- `MAILGUN_API_KEY` and `MAILGUN_DOMAIN` — if you need email functionality
- `APP_BASE_URL` — your server's public URL or IP

### Step 5: Build and start

```bash
# Build the app image and start all services in detached mode
docker compose up -d --build
```

This will:
1. Pull `postgres:16-alpine` and `redis:7-alpine` (first time only)
2. Build your app image using the Dockerfile
3. Start Postgres and Redis, wait for health checks to pass
4. Start the app container, run Alembic migrations, start Uvicorn

### Step 6: Verify

```bash
# Check all three containers are running
docker compose ps

# Check app logs
docker compose logs app

# Test the health endpoint
curl http://localhost:8000/health
```

You should see `{"status": "healthy"}`. From outside the server, use `http://<your-server-ip>:8000/health`.

---

## Managing the Deployment

### Common commands

```bash
# View logs (follow mode)
docker compose logs -f app

# View logs for all services
docker compose logs -f

# Stop all services (containers persist, can be restarted)
docker compose stop

# Start stopped services
docker compose start

# Stop and remove containers (volumes and images are preserved)
docker compose down

# Stop, remove containers, AND delete the database volume (DATA LOSS)
docker compose down -v

# Rebuild after code changes
docker compose up -d --build

# Restart a single service
docker compose restart app
```

### Deploying updates

```bash
cd ~/FastAPIapp
git pull origin main
docker compose up -d --build
```

This rebuilds the app image with the new code, recreates the app container, and runs any new Alembic migrations on startup. Postgres and Redis containers are unaffected unless their config changed.

### Viewing database contents

```bash
# Open a psql shell inside the Postgres container
docker compose exec postgres psql -U postgres -d app
```

### Running one-off commands in the app container

```bash
# Open a shell
docker compose exec app bash

# Run a specific command
docker compose exec app alembic history
```

### Monitoring disk usage

```bash
# See how much space Docker is using
docker system df

# Clean up unused images and build cache
docker system prune -a
```

---

## Troubleshooting

### App container keeps restarting

```bash
docker compose logs app
```

Common causes:
- **Missing `.env` file** — `env_file: .env` in compose will fail if the file doesn't exist. Run `cp .env.docker.example .env`.
- **Migration failure** — If Alembic fails, the container exits and restarts. Check the logs for the SQL error.
- **Postgres not ready** — Shouldn't happen with health checks, but verify with `docker compose ps` that postgres is healthy.

### "Permission denied" errors

If you see permission errors related to Alembic or file writes, rebuild the image:

```bash
docker compose build --no-cache
docker compose up -d
```

The `chown -R appuser:appuser /app` in the Dockerfile should prevent this, but a stale cached image might not have the fix.

### Cannot connect to Docker daemon

```bash
# Make sure Docker is running
sudo systemctl start docker

# Make sure your user is in the docker group
groups
# If "docker" is not listed:
sudo usermod -aG docker $USER
# Then log out and back in
```

### Port 8000 already in use

```bash
# Find what's using the port
sudo lsof -i :8000

# Or change the host port in docker-compose.yml:
# ports:
#   - "9000:8000"   # Access via port 9000 instead
```

### Resetting everything

If you need a completely clean start:

```bash
# Stop and remove containers, networks, and volumes
docker compose down -v

# Remove the built image
docker rmi $(docker compose images -q)

# Start fresh
docker compose up -d --build
```

This **deletes all database data**. Only do this if you want a fresh start.
