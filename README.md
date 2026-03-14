# FastAPI App — Full Documentation

---

## Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Architecture & Layer Responsibilities](#architecture--layer-responsibilities)
4. [Request Flow](#request-flow)
5. [Database](#database)
6. [Module Reference](#module-reference)
   - [core/config.py](#coreconfigpy)
   - [database/session.py](#databasesessionpy)
   - [models/base.py](#modelsbasepy)
   - [models/task.py](#modelstaskpy)
   - [models/user.py](#modelsuserpy)
   - [schemas/task_model.py](#schemastask_modelpy)
   - [schemas/users_schema.py](#schemasusers_schemapy)
   - [repositories/task_repository.py](#repositoriestask_repositorypy)
   - [repositories/user_repository.py](#repositoriesuser_repositorypy)
   - [services/task_services.py](#servicestask_servicespy)
   - [services/user_services.py](#servicesuser_servicespy)
   - [api/routes/task_routes.py](#apiroutestask_routespy)
   - [api/routes/user_routes.py](#apiroutesuser_routespy)
   - [utils/security/password_hash.py](#utilssecuritypassword_hashpy)
7. [API Endpoints](#api-endpoints)
8. [Dependency Injection](#dependency-injection)

---

## Overview

A RESTful API built with **FastAPI** and **PostgreSQL**. It provides two resources:

- **Tasks** — create tasks, list them, and mark them as complete. Each task belongs to a user.
- **Users** — register new users with a hashed password.

The codebase follows a strict **layered architecture**: every concern lives in exactly one layer, and layers only communicate with their immediate neighbors.

---

## Directory Structure

```
app/
├── main.py                               # App entry point — assembles routers
├── core/
│   └── config.py                         # Typed settings loaded from .env
├── database/
│   └── session.py                        # Engine, session factory, get_db() dependency
├── models/
│   ├── base.py                           # Shared DeclarativeBase for all ORM models
│   ├── task.py                           # Task ORM model → tasks table
│   └── user.py                           # User ORM model → users table
├── schemas/
│   ├── task_model.py                     # Pydantic schemas for task endpoints
│   └── users_schema.py                   # Pydantic schemas for user endpoints
├── repositories/
│   ├── task_repository.py                # Raw DB queries for tasks
│   └── user_repository.py               # Raw DB queries for users
├── services/
│   ├── task_services.py                  # Business logic for tasks
│   └── user_services.py                  # Business logic for users
├── api/
│   └── routes/
│       ├── task_routes.py                # HTTP endpoints for /api/tasks/...
│       └── user_routes.py               # HTTP endpoints for /api/users/...
└── utils/
    └── security/
        ├── __init__.py                   # Exposes hash_password
        └── password_hash.py              # hash_password, verify_password via pwdlib
```

---

## Architecture & Layer Responsibilities

The app is split into five layers. Data flows strictly downward on a request and back up on a response. No layer skips another.

```
┌─────────────────────────────────────┐
│           api/routes/               │  HTTP only — methods, paths, status codes
├─────────────────────────────────────┤
│           services/                 │  Business logic — rules, data transformation
├─────────────────────────────────────┤
│           repositories/             │  Database only — all SQL/ORM lives here
├─────────────────────────────────────┤
│           models/                   │  ORM classes — map Python objects to DB tables
├─────────────────────────────────────┤
│           database/session.py       │  Connection management — creates & closes sessions
└─────────────────────────────────────┘
```

| Layer | What it knows about | What it does NOT do |
|---|---|---|
| Routes | HTTP verbs, paths, request/response schemas | No SQL, no business rules |
| Services | Pydantic schemas, repository functions | No SQL, no HTTP concerns |
| Repositories | ORM models, SQLAlchemy session | No HTTP, no business rules |
| Models | Table structure, column types | No queries, no validation |
| Session | Database URL, connection lifecycle | No queries, no logic |

**Schemas** (Pydantic) sit alongside this stack — they define the shape of data entering and leaving the API but are not a layer themselves. They are used by routes to validate input and by FastAPI to serialize output.

---

## Request Flow

### Example: `POST /api/tasks/create`

```
Client
  │
  │  POST /api/tasks/create
  │  Body: { "task": "Buy milk", "user_id": "uuid..." }
  ▼
api/routes/task_routes.py
  │  FastAPI validates the body against TaskCreate (Pydantic)
  │  FastAPI calls get_db() and injects a Session via Depends
  │  Calls create_task(db, task)
  ▼
services/task_services.py
  │  Extracts task.task and task.user_id from the schema
  │  Calls task_repository.create_task(db, task_name, user_id)
  ▼
repositories/task_repository.py
  │  Builds a Task ORM object
  │  db.add(task) — stages the insert
  │  db.commit()  — writes to the database
  │  db.refresh() — reloads the saved row (picks up DB-generated id)
  │  Returns the ORM Task object
  ▼
Routes → FastAPI serializes the ORM object through TaskRead → Client
  │
  └─ Response: { "id": 1, "task": "Buy milk", "completed": false, "user_id": "uuid..." }
```

---

## Database

**Engine:** PostgreSQL
**ORM:** SQLAlchemy (sync)
**Connection string:** read from `DATABASE_URL` in `.env`

### Tables

#### `users`

| Column | Type | Constraints |
|---|---|---|
| `id` | UUID | Primary key, `gen_random_uuid()` server default |
| `name` | varchar | Not null, indexed |
| `email` | varchar | Not null, unique, indexed |
| `password_hash` | varchar | Not null |
| `created_at` | timestamptz | Not null, `now()` server default |

#### `tasks`

| Column | Type | Constraints |
|---|---|---|
| `id` | bigint | Primary key, auto-increment (BIGSERIAL / sequence) |
| `task` | varchar(200) | Not null |
| `completed` | boolean | Not null, defaults to `false` |
| `user_id` | UUID | Not null, foreign key → `users.id` |

> `tasks.user_id` references `users.id` — every task must belong to an existing user.

---

## Module Reference

### `core/config.py`

Defines a `Settings` class using `pydantic-settings`. Reads `.env` on startup and exposes typed attributes.

```python
settings.DATABASE_URL  # used by database/session.py
```

All other modules import `settings` from here — nothing reads `os.environ` directly.

---

### `database/session.py`

Three things:

- **`engine`** — SQLAlchemy connection to the DB, created once at startup.
- **`SessionLocal`** — session factory (`autocommit=False`, `autoflush=False`). Calling it produces a new session.
- **`get_db()`** — FastAPI dependency. Creates a session, yields it to the route, rolls back on exception, and always closes in `finally`.

```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

---

### `models/base.py`

Defines the shared `Base` class all ORM models inherit from.

```python
class Base(DeclarativeBase):
    pass
```

Centralizing `Base` ensures all models are registered under the same metadata, which is required for operations like `Base.metadata.create_all()`.

---

### `models/task.py`

Maps the `tasks` table to the `Task` Python class.

```python
class Task(Base):
    __tablename__ = "tasks"

    id        = Column(BigInteger, primary_key=True)
    task      = Column(String(200), nullable=False)
    completed = Column(Boolean, nullable=False, default=False)
    user_id   = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
```

Uses the legacy SQLAlchemy `Column` style.

---

### `models/user.py`

Maps the `users` table to the `User` Python class.

```python
class User(Base):
    __tablename__ = "users"

    id            # UUID, server-generated
    name          # String, not null, indexed
    email         # String, unique, not null, indexed
    password_hash # String, not null — never stores plaintext
    created_at    # DateTime (tz-aware), server-generated
```

Uses the modern SQLAlchemy 2.0 `Mapped` / `mapped_column` style.

---

### `schemas/task_model.py`

Three Pydantic schemas covering the full task lifecycle:

| Schema | Used as | Fields |
|---|---|---|
| `TaskCreate` | Request body for creating a task | `task: str`, `user_id: UUID` |
| `TaskComplete` | Request body for completing a task | `id: int` |
| `TaskRead` | Response model for task endpoints | `id`, `task`, `completed`, `user_id` |

`TaskRead` has `from_attributes=True` so FastAPI can build it directly from a SQLAlchemy ORM object.

---

### `schemas/users_schema.py`

Three Pydantic schemas with an inheritance chain:

```
UserBase        →  name: str, email: EmailStr
├── UserCreate  →  adds password: str (8–128 chars)
└── UserRead    →  adds id: UUID, created_at: datetime
```

`UserCreate` is used as the request body. `UserRead` is the response model — it never includes the password or password hash.

---

### `repositories/task_repository.py`

All SQL for the `tasks` table lives here.

| Function | What it does |
|---|---|
| `get_all_tasks(db)` | Returns all rows from `tasks` |
| `create_task(db, task_name, user_id)` | Inserts a new task row and returns it |
| `set_complete(task_id, db)` | Sets `completed = True` for the given id; raises 404 if not found |

---

### `repositories/user_repository.py`

All SQL for the `users` table lives here.

| Function | What it does |
|---|---|
| `create_user(db, user_in)` | Hashes the password, inserts the user, raises 409 on duplicate email |

---

### `services/task_services.py`

Thin wrappers that sit between the routes and repositories. Currently no heavy business logic, but this is where rules like "a user can only have N tasks" would live.

| Function | What it does |
|---|---|
| `return_task(db)` | Delegates to `get_all_tasks` |
| `create_task(db, task)` | Extracts fields from `TaskCreate`, delegates to repository |
| `set_complete(task, db)` | Extracts `task.id`, delegates to repository |

---

### `services/user_services.py`

| Function | What it does |
|---|---|
| `user_create(db, user)` | Delegates to `user_repository.create_user` |

---

### `api/routes/task_routes.py`

Defines `tasks_router = APIRouter(tags=["tasks"])` and three endpoints. Registered in `main.py` under the `/api` prefix.

| Method | Path | Request body | Response |
|---|---|---|---|
| GET | `/api/tasks/get` | — | `list[TaskRead]` |
| POST | `/api/tasks/create` | `TaskCreate` | `TaskRead` |
| POST | `/api/tasks/complete` | `TaskComplete` | — |

---

### `api/routes/user_routes.py`

Defines `user_router = APIRouter(tags=["users"])` and one endpoint. Registered in `main.py` under the `/api` prefix.

| Method | Path | Request body | Response |
|---|---|---|---|
| POST | `/api/users/create` | `UserCreate` | `UserRead` |

---

### `utils/security/password_hash.py`

```python
hash_password(password: str) -> str
verify_password(password: str, hashed_password: str) -> bool
```

Backed by `pwdlib` using its recommended algorithm. `hash_password` is called in the user repository before saving to the DB. `verify_password` is available for a future login endpoint.

---

## API Endpoints

| Method | Path | Description | Request body | Response |
|---|---|---|---|---|
| GET | `/api/tasks/get` | List all tasks | — | `list[TaskRead]` |
| POST | `/api/tasks/create` | Create a task | `TaskCreate` | `TaskRead` |
| POST | `/api/tasks/complete` | Mark a task complete | `TaskComplete` | — |
| POST | `/api/users/create` | Register a new user | `UserCreate` | `UserRead` |

---

## Dependency Injection

FastAPI's `Depends()` system wires the database session into routes without any route manually creating or closing a session.

```
get_db()  ←  database/session.py
    │
    └── Depends(get_db) in task_routes.py / user_routes.py
            │
            └── db passed to services/
                        │
                        └── db passed to repositories/
```

Each layer simply receives `db: Session` as a parameter. No layer knows how the session was created or when it will be closed — that is entirely `get_db()`'s responsibility. This makes every layer independently testable by passing in a mock session.
