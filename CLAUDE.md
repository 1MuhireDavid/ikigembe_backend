# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run dev server
python manage.py runserver 0.0.0.0:8000

# Migrations
python manage.py makemigrations
python manage.py migrate

# Run all tests
python manage.py test

# Run tests for a specific app
python manage.py test apps.users
python manage.py test apps.movies

# Run a single test class or method
python manage.py test apps.users.tests.TestClassName
python manage.py test apps.users.tests.TestClassName.test_method_name

# Seed data
python manage.py seed_movies       # 27 Rwandan-themed movies
python manage.py add_test_data     # Test users + payments (password: "password123")

# Production server
gunicorn ikigembe_bn.wsgi:application --bind 0.0.0.0:8000
```

## Architecture

Django project (`ikigembe_bn/`) with three apps under `apps/`:

**`apps/users/`** — Auth + admin dashboard. Custom `User` model (AbstractBaseUser) supports login by email *or* phone number — at least one is required. JWT tokens embed `role` and `email` as custom claims. Role-based permissions live in `permissions.py` (`IsAdminRole`, `IsProducerRole`, `IsAdminOrProducerRole`). All admin analytics and management endpoints are in `admin_views.py` / `admin_urls.py`, mounted at `/api/admin/dashboard/`.

**`apps/movies/`** — Core app. `views.py` (~800 lines) handles discovery/listing, streaming URL generation, S3 multipart upload, and payment-gated access. The `Movie` model stores files via Django storages → S3, served through CloudFront. Four serializers cover different use cases: list, detail, create/update, and video access. Streaming endpoints generate signed CloudFront URLs and check `Payment` records before granting access.

**`apps/payments/`** — Models only (no dedicated views or serializers). `Payment` records user→movie purchases. `WithdrawalRequest` tracks producer earnings requests. Both are surfaced through admin_views endpoints. Revenue split: 70% producer / 30% platform.

## Request Flow

JWT/OAuth auth → DRF views → serializers → models → PostgreSQL (Supabase in prod, SQLite locally) + AWS S3 → CloudFront CDN

## URL Structure

| Prefix | App |
|---|---|
| `/api/auth/` | users/urls.py |
| `/api/movies/` | movies/urls.py |
| `/api/admin/dashboard/` | users/admin_urls.py |
| `/api/docs/` | Swagger UI |
| `/api/redoc/` | ReDoc |

## Key Patterns

**Database switching:** `settings.py` uses `dj_database_url` — SQLite locally when `DATABASE_URL` is unset, PostgreSQL (with SSL) in production. Tests always run against SQLite in-memory.

**Google OAuth:** `/api/auth/google/` verifies the Google ID token server-side and either creates a new account or links `google_id` to an existing email account.

**Token rotation:** Refresh tokens are rotated and blacklisted on each use (`rest_framework_simplejwt.token_blacklist`). Access tokens are 30 min; refresh tokens are 7 days.

**S3 multipart uploads:** Large video files use a 4-step flow: `initiate/` → `sign-part/` (per chunk) → `complete/` → `abort/`. All endpoints are in `movies/views.py`.

**Producer role:** New users always register as Viewer. Producers must be set via admin. Admin endpoints can approve/suspend producers.

## Environment Variables Required

```
DATABASE_URL
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
AWS_STORAGE_BUCKET_NAME
CLOUDFRONT_DOMAIN
GOOGLE_CLIENT_ID
SECRET_KEY
```
