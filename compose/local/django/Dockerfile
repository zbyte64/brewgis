# Build the map bundle — a gitignored Vite artifact, so nothing else in the
# image or the repo provides it. It cannot live under APP_HOME: the repo is
# bind-mounted over /app at runtime, which hides anything baked into that path.
# settings.py adds this directory to STATICFILES_DIRS *after* the repo's own
# static dir, so a bundle a developer built into the repo still wins.
FROM docker.io/node:22-bookworm-slim AS frontend-build-stage

WORKDIR /src
COPY ./package.json ./package-lock.json ./
RUN npm ci
COPY ./tsconfig.json ./vite.config.ts ./
COPY ./js ./js
RUN npm run build


# define an alias for the specific python version used in this file.
FROM docker.io/python:3.12.7-slim-bookworm AS python

# Python build stage
FROM python AS python-build-stage

ARG BUILD_ENVIRONMENT=local

# Install apt packages
RUN apt-get update && apt-get install --no-install-recommends -y \
  # dependencies for building Python packages
  build-essential \
  # psycopg dependencies
  libpq-dev

# Requirements are installed here to ensure they will be cached.
COPY ./requirements .

# Create Python Dependency and Sub-Dependency Wheels.
RUN pip wheel --wheel-dir /usr/src/app/wheels  \
  -r ${BUILD_ENVIRONMENT}.txt


# Python 'run' stage
FROM python AS python-run-stage

ARG BUILD_ENVIRONMENT=local
ARG APP_HOME=/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV BUILD_ENV=${BUILD_ENVIRONMENT}
ENV PYTHONPATH="/app"
ENV DJANGO_SETTINGS_MODULE=brewgis.config.settings
ENV DJANGO_READ_DOT_ENV_FILE=true

WORKDIR ${APP_HOME}


# devcontainer dependencies and utils
RUN apt-get update && apt-get install --no-install-recommends -y \
  sudo git bash-completion nano ssh

# Create devcontainer user and add it to sudoers
RUN groupadd --gid 1000 dev-user \
  && useradd --uid 1000 --gid dev-user --shell /bin/bash --create-home dev-user \
  && echo dev-user ALL=\(root\) NOPASSWD:ALL > /etc/sudoers.d/dev-user \
  && chmod 0440 /etc/sudoers.d/dev-user


# Install required system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
  # psycopg dependencies
  libpq-dev  \
  wait-for-it \
  postgresql-client \
  postgis \
  # Translations dependencies
  gettext \
  # dbt and GIS analysis dependencies
  libgdal-dev gdal-bin \
  # osmnx / network analysis dependencies
  libspatialindex-dev \
  # cleaning up unused files
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*

# Playwright E2E test dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
    libnss3 libnspr4 libatk-bridge2.0-0 libdrm2 libxkbcommon0 \
    libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 \
    libpango-1.0-0 libcairo2 libatspi2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# WeasyPrint (PDF report generation) dependencies —
# https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#debian-ubuntu
RUN apt-get update && apt-get install --no-install-recommends -y \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright browsers (chromium only to keep image lean)
# Use a shared path so the dev-user can access them at runtime
ENV PLAYWRIGHT_BROWSERS_PATH=/usr/local/share/ms-playwright
RUN pip install playwright==1.52.0 && \
    mkdir -p /usr/local/share/ms-playwright && \
    playwright install chromium --with-deps

RUN --mount=type=bind,from=python-build-stage,source=/usr/src/app/wheels,target=/wheels \
  pip install --no-cache-dir --no-index --find-links=/wheels/ /wheels/*

# Patch: web.server.settings uses Generator[Context, None] (2 type args) which
# typing_extensions >=4.12 rejects because Generator expects 3 (Yield, Send, Return).
# Can remove when upstream fixes it.
RUN sed -i 's/Generator\[Context, None\]/Generator[Context, None, None]/g' \
  /usr/local/lib/python3.12/site-packages/web/server/settings.py

COPY ./compose/production/django/entrypoint /entrypoint
RUN sed -i 's/\r$//g' /entrypoint
RUN chmod +x /entrypoint

COPY ./compose/local/django/start /start
RUN sed -i 's/\r$//g' /start
RUN chmod +x /start


COPY ./compose/local/django/celery/worker/start /start-celeryworker
RUN sed -i 's/\r$//g' /start-celeryworker
RUN chmod +x /start-celeryworker

COPY ./compose/local/django/celery/beat/start /start-celerybeat
RUN sed -i 's/\r$//g' /start-celerybeat
RUN chmod +x /start-celerybeat

COPY ./compose/local/django/celery/flower/start /start-flower
RUN sed -i 's/\r$//g' /start-flower
RUN chmod +x /start-flower

COPY ./compose/local/django/start-mcp /start-mcp
RUN sed -i 's/\r$//g' /start-mcp
RUN chmod +x /start-mcp

COPY ./compose/local/django/start-sqlmesh-ui /start-sqlmesh-ui
RUN sed -i 's/\r$//g' /start-sqlmesh-ui
RUN chmod +x /start-sqlmesh-ui


# copy application code to WORKDIR
COPY . ${APP_HOME}

# The map bundle from the frontend stage, plus its sourcemap (the dev image is
# where the map gets debugged). Kept outside APP_HOME — see the stage above.
COPY --from=frontend-build-stage \
  /src/brewgis/static/js/brew-gis-map.js \
  /src/brewgis/static/js/brew-gis-map.js.map \
  /opt/brewgis-frontend/js/

# Pre-download DuckDB extensions so INSTALL is a no-op at runtime
COPY ./compose/local/django/preload_duckdb.py /tmp/preload_duckdb.py
RUN su - dev-user -c "python3 /tmp/preload_duckdb.py" && rm /tmp/preload_duckdb.py

ENTRYPOINT ["/entrypoint"]
