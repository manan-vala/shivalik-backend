"""
Django settings for the Shivalik warehouse backend.

Everything environment-specific is read from the process environment, seeded
from a local ``.env`` file (see ``.env.example``). Nothing secret is committed.

Decisions encoded here — the reasoning behind each is in
``ARCHITECTURE.md``:

* **PostgreSQL.** ``DB_ENGINE`` defaults to ``postgresql``. SQLite remains
  reachable via ``DB_ENGINE=sqlite`` for laptops without a local server, but
  ``api.checks`` raises a loud warning when it is in use, because
  ``select_for_update()`` is a silent no-op there and every
  concurrency guarantee in the stock ledger becomes fiction.
* **The API is closed by default.** ``DEFAULT_PERMISSION_CLASSES`` is
  ``IsAuthenticated``; the four public routes (``login/``, ``token/refresh/``,
  ``health/``, ``register/``) opt out explicitly at the view. ``register/``
  is safe to open because its serializer cannot set anything that confers
  access — a signup lands ``Pending`` and inactive.
* **No committed secrets.** ``SECRET_KEY``, ``DEBUG``, hosts and DB
  credentials all come from the environment.
* **CORS middleware sits directly below `SecurityMiddleware`**, above
  anything that can generate a response.
* **Media is configured**, so ``Employee.contract`` uploads can work.
* **Pagination and filtering are project-wide**, not per view.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .env import env, env_bool, env_int, env_list

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env before anything below reads the environment. Real environment
# variables win over the file, so CI and containers need no .env at all.
load_dotenv(BASE_DIR / ".env", override=False)


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEBUG = env_bool("DJANGO_DEBUG", default=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured(
            "DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is off. "
            "Copy .env.example to .env and fill it in."
        )
    # Development convenience only — never reached with DEBUG off.
    SECRET_KEY = "django-insecure-local-development-key-do-not-deploy"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])

# HTTPS hardening — everything `manage.py check --deploy` asks for. On by
# default wherever DEBUG is off, because a deployment without TLS is the
# exception and should have to say so. Set DJANGO_SECURE_SSL=false for a
# plain-HTTP staging box.
SECURE_SSL_ENABLED = env_bool("DJANGO_SECURE_SSL", default=not DEBUG)

if SECURE_SSL_ENABLED:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = env_int("DJANGO_HSTS_SECONDS", default=60 * 60 * 24 * 365)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    # Behind a reverse proxy that terminates TLS, Django needs telling.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "staff_auth.Employee"


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "rest_framework_simplejwt",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # Local
    "api",
    "staff_auth",
    "auditlog",
    "inventory",
]

MIDDLEWARE = [
    # Outermost, so its timing and request id cover every other middleware.
    "api.observability.RequestLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    # Must sit above anything that can short-circuit a response
    # (CommonMiddleware redirects, error paths) or those responses lose their
    # CORS headers and fail in the browser for reasons that are painful to
    # diagnose.
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]


# ---------------------------------------------------------------------------
# Database — PostgreSQL
# ---------------------------------------------------------------------------

DB_ENGINE = env("DB_ENGINE", default="postgresql").lower()

if DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", default="shivalik"),
            "USER": env("DB_USER", default="shivalik"),
            "PASSWORD": env("DB_PASSWORD", default="shivalik"),
            "HOST": env("DB_HOST", default="127.0.0.1"),
            "PORT": env("DB_PORT", default="5432"),
            # Reuse connections across requests; a stock movement holds a row
            # lock, so connection setup cost is worth avoiding.
            "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", default=60),
        }
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            # Deliberately NOT DB_NAME: the two engines would share one
            # variable, so flipping DB_ENGINE in a .env written for the other
            # would look for a Postgres database called "db.sqlite3" — or
            # create a SQLite file called "shivalik". Separate names make the
            # switch a one-line edit that cannot half-apply.
            "NAME": BASE_DIR / env("SQLITE_NAME", default="db.sqlite3"),
        }
    }
else:
    raise ImproperlyConfigured(
        f"DB_ENGINE must be 'postgresql' or 'sqlite', got {DB_ENGINE!r}."
    )


# ---------------------------------------------------------------------------
# REST framework
# ---------------------------------------------------------------------------

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # Closed by default. Public routes opt out with an explicit
    # `permission_classes = [AllowAny]`, which is greppable in review.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    # DRF's handler, plus: a delete blocked by `on_delete=PROTECT` is a 409
    # naming what still depends on the row, not a 500.
    "EXCEPTION_HANDLER": "api.exceptions.exception_handler",
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": env_int("API_PAGE_SIZE", default=25),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_RATES": {
        "telemetry": env("TELEMETRY_THROTTLE_RATE", default="60/min"),
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Shivalik Warehouse API",
    "DESCRIPTION": (
        "Inventory, warehouse, vendor and staff APIs for the Shivalik "
        "book-distribution backend."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1",
    "COMPONENT_SPLIT_REQUEST": True,
    # `Employee.role` and `Employee.requested_role` share one choice set, so
    # spectacular sees the same enum under two names and warns. They are the
    # same enum on purpose — one is the role an admin assigned, the other the
    # role the applicant asked for — so collapse them to a single component
    # rather than letting the generator invent `RoleEnum` / `RequestedRoleEnum`
    # and hand the frontend two identical types.
    "ENUM_NAME_OVERRIDES": {
        "RoleEnum": "staff_auth.models.ROLE_CHOICES",
    },
}


# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)


# ---------------------------------------------------------------------------
# Passwords, i18n
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
# Stored and served as UTC (ISO-8601); the frontend localises for display.
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# Static & media
# ---------------------------------------------------------------------------

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / env("MEDIA_DIRNAME", default="media")


# ---------------------------------------------------------------------------
# Domain constants
# ---------------------------------------------------------------------------

# Money is INR everywhere. Stored as Decimal, never float.
DEFAULT_CURRENCY = "INR"

# Role-based permission classes are published as stubs and allow any
# authenticated caller until the permission matrix exists.
# Turning this on without filling in `allowed_roles` denies everyone.
ENFORCE_ROLE_PERMISSIONS = env_bool("ENFORCE_ROLE_PERMISSIONS", default=False)

# The login IP allow-list (Team D). `WhitelistedIP` starts empty and nothing
# seeds it, so enforcing it unconditionally means a fresh database cannot
# issue a single token — the whole API is unreachable, including `/admin/`'s
# API counterpart. That is correct for a deployment where the allow-list has
# been populated deliberately, and a lockout everywhere else, so it follows
# DEBUG: off while developing, on the moment DEBUG is.
ENFORCE_IP_ALLOWLIST = env_bool("ENFORCE_IP_ALLOWLIST", default=not DEBUG)

# Dead stock is computed on read, not persisted. Per-book overrides live
# on `Book.dead_stock_threshold_days`; this is the fallback.
DEAD_STOCK_DEFAULT_DAYS = env_int("DEAD_STOCK_DEFAULT_DAYS", default=90)


# ---------------------------------------------------------------------------
# Operational logging
# ---------------------------------------------------------------------------

# Requests, errors and frontend telemetry. Never the database: business
# history is `auditlog`, which is transactional and permanent; this is
# high-volume and disposable.
#
# stdout by default, which is what containers and log shippers expect. Set
# LOG_FILE to also append JSON lines to a file, and rotate it with logrotate:
# WatchedFileHandler reopens the file after logrotate moves it. Rotating
# in-process instead breaks as soon as two processes share the file — every
# gunicorn worker, or runserver and its autoreloader on Windows.
LOG_LEVEL = env("LOG_LEVEL", default="INFO").upper()
LOG_FORMAT = env("LOG_FORMAT", default="text" if DEBUG else "json").lower()
LOG_FILE = env("LOG_FILE", default="")

if LOG_FORMAT not in ("json", "text"):
    raise ImproperlyConfigured(f"LOG_FORMAT must be 'json' or 'text', got {LOG_FORMAT!r}.")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "request_id": {"()": "api.observability.RequestIdFilter"},
    },
    "formatters": {
        "json": {
            "()": "pythonjsonlogger.json.JsonFormatter",
            "fmt": "%(levelname)s %(name)s %(message)s %(request_id)s",
            "rename_fields": {"levelname": "level", "name": "logger"},
            "timestamp": True,
        },
        "text": {
            "format": "{asctime} {levelname} {name} [{request_id}] {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": LOG_FORMAT,
            "filters": ["request_id"],
        },
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Django's defaults attach their own console handler in DEBUG; hand
        # everything to root instead so each record is written exactly once.
        "django": {"handlers": [], "level": "INFO", "propagate": True},
    },
}

if LOG_FILE:
    LOGGING["handlers"]["file"] = {
        "class": "logging.handlers.WatchedFileHandler",
        "filename": LOG_FILE,
        "formatter": "json",
        "filters": ["request_id"],
    }
    LOGGING["root"]["handlers"].append("file")
