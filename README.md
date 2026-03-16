# FastAPI Authentication API

A backend authentication API built with FastAPI, featuring user registration, email verification, JWT-based authentication, and password reset functionality.

## Tech Stack

- **Framework:** FastAPI 0.135 + Uvicorn
- **Database:** PostgreSQL + SQLAlchemy 2.0 ORM
- **Migrations:** Alembic
- **Authentication:** PyJWT (HS256)
- **Password Hashing:** Argon2id (pwdlib)
- **Email:** Mailgun API
- **Rate Limiting:** Redis (sliding window counter via Lua script)
- **Testing:** pytest (77 tests, 94% coverage)


## API Endpoints

### Users (`/api`)

| Method | Path | Auth | Rate Limited | Description |
|--------|------|------|--------------|-------------|
| POST | `/users/create` | No | 5/hr per IP | Register a new user |
| GET | `/users/me` | Bearer | No | Get authenticated user profile |

### Auth (`/api/auth`)

| Method | Path | Auth | Rate Limited | Description |
|--------|------|------|--------------|-------------|
| POST | `/login` | No | 10/hr per IP+email, 30/hr per IP | Login, returns access + refresh tokens |
| POST | `/refresh` | Cookie | 30/hr per IP | Refresh access token |
| POST | `/logout` | Bearer | No | Revoke tokens and clear cookie |
| POST | `/forgot-password` | No | 5/hr per IP+email | Send password reset email |
| GET | `/reset-password` | No | 10/hr per IP | Validate reset code from email |
| POST | `/reset-password` | No | 10/hr per IP | Reset password with code or token |
| POST | `/resend-verification` | No | 5/hr per IP+email | Resend verification email |
| GET | `/verify-email` | No | 10/hr per IP | Verify email via code from email link |
| POST | `/verify-email` | No | No | Verify email via JWT token |

## Setup

### Prerequisites

- Python 3.14+
- PostgreSQL 18+
- Redis 7+ (via Docker or WSL)

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd FastAPIapp

# Create and activate a virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt
```

### Environment Variables

Checkout .env.example

### Database Setup

```bash
# Run migrations
alembic upgrade head
```

### Redis Setup

```bash
# Start Redis via Docker
docker run -d --name redis -p 6379:6379 redis:7

# Verify it's running
docker exec -it redis redis-cli ping   # should return PONG
```

The app connects to `redis://localhost:6379/0` by default. Override with the `REDIS_URL` environment variable. If Redis is unavailable, the app still runs but rate limiting is disabled (fail-open).

### Run the Server

```bash
uvicorn app.main:app --reload
```

### Run The Test Client

```bash
streamlit run test-client\streamlit_client.py
```

The API will be available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

## Authentication Flow

1. **Register** — `POST /api/users/create` creates account and sends verification email
2. **Verify Email** — User clicks link in email (`GET /api/auth/verify-email?code=...`)
3. **Login** — `POST /api/auth/login` returns an access token (30 min) and sets a refresh token as an httponly cookie (1 day)
4. **Access Protected Routes** — Include `Authorization: Bearer <access_token>` header
5. **Refresh** — `POST /api/auth/refresh` exchanges refresh cookie for a new access token
6. **Logout** — `POST /api/auth/logout` blacklists both tokens and clears the cookie

### Token Revocation

Tokens are revoked through two mechanisms:
- **Blacklist table** — Individual token JTIs are stored and checked on every request
- **Password change invalidation** — Changing a password invalidates all tokens issued before the change

### Security Features

- Argon2id password hashing
- Row-level database locks on email verification and password reset to prevent race conditions
- Redis-backed sliding window rate limiting on all auth endpoints (distributed, persistent across restarts)
- Refresh tokens stored as httponly, samesite=strict cookies
- Secure cookie flag enabled in production

## Testing

Tests use a real PostgreSQL database (`fastapiapp_test`) with per-test transaction rollback for isolation. Redis is mocked via `fakeredis` — no running Redis server needed for tests.

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Generate HTML report
pytest tests/ --html=reports/test_report.html --self-contained-html
```

Test reports are available in the `reports/` directory.

## Architecture

The application follows a layered architecture:

```
Routes → Dependencies → Services → Repositories → Models → PostgreSQL
                ↕
         Redis (rate limiting)
```

- **Routes** — HTTP concerns (request/response, status codes, cookies)
- **Dependencies** — Rate limiting (Redis sliding window counter), authentication
- **Services** — Business logic (validation, token generation, email dispatch)
- **Repositories** — Pure data access (queries, inserts, row-level locks)
- **Models** — Database schema (SQLAlchemy ORM)

See [system-architecture.md](system-architecture.md) for detailed architecture docs.
See [docs/redis-rate-limiting.md](docs/redis-rate-limiting.md) for the rate limiting implementation walkthrough.
