"""Django settings for Brew GIS.

All environment-specific behavior flows from environment variables.
Set DJANGO_DEBUG=True for development, DJANGO_TESTING=True for test suite,
or neither for production.
"""

import socket
import ssl
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve(strict=True).parent.parent
# brewgis/
APPS_DIR = BASE_DIR / "brewgis"
env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
if READ_DOT_ENV_FILE:
    # OS environment variables take precedence over variables from .env
    dotenv_path = BASE_DIR / ".env"
    if dotenv_path.exists():
        env.read_env(str(dotenv_path))

# ==============================================================================
# MODE FLAGS
# ==============================================================================
# DJANGO_TESTING gates test-suite behavior (fast hashers, locmem email, etc.)
# DJANGO_DEBUG gates dev behavior (debug toolbar, console email, etc.)
# When neither is set, production settings apply.

TESTING = env.bool("DJANGO_TESTING", default=False)
# In test mode, DEBUG defaults to True so template debugging works.
DEBUG = env.bool("DJANGO_DEBUG", default=TESTING)

# ==============================================================================
# GENERAL
# ==============================================================================
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
SITE_ID = 1
USE_I18N = True
USE_TZ = True
LOCALE_PATHS = [str(BASE_DIR / "locale")]

# ==============================================================================
# DATABASES
# ==============================================================================
DATABASES = {"default": env.db("DATABASE_URL")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["ENGINE"] = "django.contrib.gis.db.backends.postgis"

# ==============================================================================
# URLS
# ==============================================================================
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# ==============================================================================
# APPS
# ==============================================================================
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.admin",
    "django.forms",
    "django.contrib.gis",
]
THIRD_PARTY_APPS = [
    "crispy_forms",
    "crispy_bootstrap5",
    "allauth",
    "allauth.account",
    "django_celery_beat",
    "django_htmx",
]
LOCAL_APPS = [
    "brewgis.workspace",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# ==============================================================================
# AUTHENTICATION
# ==============================================================================
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]
AUTH_USER_MODEL = "auth.User"
LOGIN_REDIRECT_URL = "/"
LOGIN_URL = "account_login"

# ==============================================================================
# PASSWORDS
# ==============================================================================
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ==============================================================================
# MIDDLEWARE
# ==============================================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
]

# ==============================================================================
# STATIC
# ==============================================================================
STATIC_ROOT = str(BASE_DIR / "staticfiles")
STATIC_URL = "/static/"
STATICFILES_DIRS = [str(APPS_DIR / "static")]
STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# ==============================================================================
# MEDIA
# ==============================================================================
MEDIA_ROOT = str(APPS_DIR / "media")
MEDIA_URL = "/media/"

# ==============================================================================
# TEMPLATES
# ==============================================================================
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [str(APPS_DIR / "templates")],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
            ],
            # Template debugging follows DEBUG (True in dev + tests).
            "debug": DEBUG,
        },
    },
]

# ==============================================================================
# FORMS
# ==============================================================================
FORM_RENDERER = "django.forms.renderers.TemplatesSetting"
CRISPY_TEMPLATE_PACK = "bootstrap5"
CRISPY_ALLOWED_TEMPLATE_PACKS = "bootstrap5"

# ==============================================================================
# FIXTURES
# ==============================================================================
FIXTURE_DIRS = (str(APPS_DIR / "fixtures"),)

# ==============================================================================
# SECURITY — Baseline
# ==============================================================================
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
X_FRAME_OPTIONS = "DENY"

# ==============================================================================
# EMAIL — Baseline (overridden per mode below)
# ==============================================================================
EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_TIMEOUT = 5

# ==============================================================================
# ADMIN
# ==============================================================================
ADMIN_URL = "admin/"
ADMINS = ["jason@krausdevhouse.com"]
MANAGERS = ADMINS
DJANGO_ADMIN_FORCE_ALLAUTH = env.bool("DJANGO_ADMIN_FORCE_ALLAUTH", default=False)

# ==============================================================================
# LOGGING — Baseline (overridden for production below)
# ==============================================================================
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"level": "INFO", "handlers": ["console"]},
}

# ==============================================================================
# REDIS
# ==============================================================================
REDIS_URL = env("REDIS_URL", default="redis://redis:6379/0")
REDIS_SSL = REDIS_URL.startswith("rediss://")

# ==============================================================================
# CACHES — Baseline (overridden per mode below)
# ==============================================================================
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "",
    },
}

# ==============================================================================
# CELERY — Baseline
# ==============================================================================
if USE_TZ:
    CELERY_TIMEZONE = TIME_ZONE
CELERY_BROKER_URL = REDIS_URL
CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE} if REDIS_SSL else None
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_REDIS_BACKEND_USE_SSL = CELERY_BROKER_USE_SSL
CELERY_RESULT_EXTENDED = True
CELERY_RESULT_BACKEND_ALWAYS_RETRY = True
CELERY_RESULT_BACKEND_MAX_RETRIES = 10
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_TIME_LIMIT = 5 * 60
CELERY_TASK_SOFT_TIME_LIMIT = 60
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
CELERY_WORKER_SEND_TASK_EVENTS = True
CELERY_TASK_SEND_SENT_EVENT = True
# Eager by default in dev/test; override via env for async Celery in host mode.
CELERY_TASK_ALWAYS_EAGER = env.bool(
    "CELERY_TASK_ALWAYS_EAGER", default=(DEBUG or TESTING)
)
CELERY_TASK_EAGER_PROPAGATES = env.bool(
    "CELERY_TASK_EAGER_PROPAGATES", default=(DEBUG or TESTING)
)

# ==============================================================================
# DJANGO-ALLAUTH
# ==============================================================================
ACCOUNT_ALLOW_REGISTRATION = env.bool("DJANGO_ACCOUNT_ALLOW_REGISTRATION", True)
ACCOUNT_LOGIN_METHODS = {"username"}
ACCOUNT_SIGNUP_FIELDS = ["email*", "username*", "password1*", "password2*"]
ACCOUNT_EMAIL_VERIFICATION = "optional"

# ==============================================================================
# APPLICATION — Tile server, GIS, Soda, etc.
# ==============================================================================
TILE_SERVER_BACKEND = env("TILE_SERVER_BACKEND", default="tipg")
TILE_SERVER_TIPG_URL = env("TILE_SERVER_TIPG_URL", default="http://tipg:8081")
TILE_SERVER_MARTIN_URL = env("TILE_SERVER_MARTIN_URL", default="http://martin:3000")
TOKEN_AUTH_KEY = env("TOKEN_AUTH_KEY", default=None)
CENSUS_API_KEY = env("CENSUS_API_KEY", default=None)

# GIS File Upload — validation limits for the GIS file ingest endpoint.
GIS_FILE_EXTENSIONS = env.list(
    "GIS_FILE_EXTENSIONS",
    default=[
        ".geojson",
        ".json",
        ".gpkg",
        ".gpkg.zip",
        ".shp",
        ".shp.zip",
        ".zip",
        ".csv",
        ".tsv",
        ".kml",
        ".kmz",
        ".gpx",
        ".fgb",
        ".parquet",
        ".topojson",
    ],
)

# Maximum upload file size in bytes (default: 100 MB).
MAX_UPLOAD_SIZE = env.int("MAX_UPLOAD_SIZE", default=100 * 1024 * 1024)

DATA_DOWNLOAD_CACHE_DIR = BASE_DIR / "planning"


# ==============================================================================
# MODE-SPECIFIC OVERRIDES
# ==============================================================================
# Test mode → fast hashers, locmem email, test auth key, no Dagster daemon.
# Dev mode  → debug toolbar, console email, locmem cache, eager Celery.
# Prod mode → SSL/HSTS, Redis cache, SMTP/Anymail, real Celery, admin logging.

if TESTING:  # ── TEST MODE ────────────────────────────────────────────────
    SECRET_KEY = env(
        "DJANGO_SECRET_KEY",
        default="c054aW6SOYg4EKrnAH6LviTjZfOUXXOGFQWoDI9yAoH5jP1bfiTtsYxT9MVRTlKg",
    )
    TEST_RUNNER = "django.test.runner.DiscoverRunner"
    PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    MEDIA_URL = "http://media.testserver"
    TOKEN_AUTH_KEY = env("TOKEN_AUTH_KEY", default="test-token-key-dev-only")

elif DEBUG:  # ── DEV MODE ──────────────────────────────────────────────────
    SECRET_KEY = env(
        "DJANGO_SECRET_KEY",
        default="m42vNRcLUVAlAr68BB1CzaFwf60kiPM131JamMDe2lvWtS7nmfoJQuV6QcmlTH1t",
    )
    ALLOWED_HOSTS = ["localhost", "0.0.0.0", "127.0.0.1"]  # noqa: S104

    # WhiteNoise — serve static files without collectstatic in dev.
    INSTALLED_APPS = ["whitenoise.runserver_nostatic", *INSTALLED_APPS]

    # Email — print to console in dev.
    EMAIL_BACKEND = env(
        "DJANGO_EMAIL_BACKEND",
        default="django.core.mail.backends.console.EmailBackend",
    )

    # Django Debug Toolbar
    INSTALLED_APPS += ["debug_toolbar"]
    MIDDLEWARE += ["debug_toolbar.middleware.DebugToolbarMiddleware"]
    DEBUG_TOOLBAR_CONFIG = {
        "DISABLE_PANELS": [
            "debug_toolbar.panels.redirects.RedirectsPanel",
            # Disable profiling panel due to an issue with Python 3.12:
            # https://github.com/jazzband/django-debug-toolbar/issues/1875
            "debug_toolbar.panels.profiling.ProfilingPanel",
        ],
        "SHOW_TEMPLATE_CONTEXT": True,
    }
    INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
    if env("USE_DOCKER") == "yes":
        hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
        INTERNAL_IPS += [".".join([*ip.split(".")[:-1], "1"]) for ip in ips]

else:  # ── PRODUCTION MODE ─────────────────────────────────────────────────
    SECRET_KEY = env("DJANGO_SECRET_KEY")  # required — no default
    ALLOWED_HOSTS = env.list(
        "DJANGO_ALLOWED_HOSTS", default=["github.com/zbyte64/brewgis"]
    )

    # Database connection pooling
    DATABASES["default"]["CONN_MAX_AGE"] = env.int("CONN_MAX_AGE", default=60)

    # Redis-backed cache
    CACHES: dict[str, dict[str, object]] = {  # type: ignore[no-redef]
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "IGNORE_EXCEPTIONS": True,
            },
        },
    }

    # Security — SSL, HSTS, secure cookies
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
    SESSION_COOKIE_SECURE = True
    SESSION_COOKIE_NAME = "__Secure-sessionid"
    CSRF_COOKIE_SECURE = True
    CSRF_COOKIE_NAME = "__Secure-csrftoken"
    SECURE_HSTS_SECONDS = 60
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
    )
    SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
    SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
        "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True
    )

    # Static & Media storage
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
        },
    }

    # Email — SMTP with Anymail
    DEFAULT_FROM_EMAIL = env(
        "DJANGO_DEFAULT_FROM_EMAIL",
        default="Brew GIS <noreply@github.com/zbyte64/brewgis>",
    )
    SERVER_EMAIL = env("DJANGO_SERVER_EMAIL", default=DEFAULT_FROM_EMAIL)
    EMAIL_SUBJECT_PREFIX = env("DJANGO_EMAIL_SUBJECT_PREFIX", default="[Brew GIS] ")
    ACCOUNT_EMAIL_SUBJECT_PREFIX = EMAIL_SUBJECT_PREFIX
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    INSTALLED_APPS += ["anymail"]
    ANYMAIL: dict[str, object] = {}

    # Admin URL from env (obscured in production)
    ADMIN_URL = env("DJANGO_ADMIN_URL")

    # Production logging — mail admins on 500s when DEBUG=False
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
        },
        "formatters": {
            "verbose": {
                "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
            },
        },
        "handlers": {
            "mail_admins": {
                "level": "ERROR",
                "filters": ["require_debug_false"],
                "class": "django.utils.log.AdminEmailHandler",
            },
            "console": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
                "formatter": "verbose",
            },
        },
        "root": {"level": "INFO", "handlers": ["console"]},
        "loggers": {
            "django.request": {
                "handlers": ["mail_admins"],
                "level": "ERROR",
                "propagate": True,
            },
            "django.security.DisallowedHost": {
                "level": "ERROR",
                "handlers": ["console", "mail_admins"],
                "propagate": True,
            },
        },
    }
