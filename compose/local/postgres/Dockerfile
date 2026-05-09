FROM postgis/postgis:17-3.5

# Install pgRouting extension for PostgreSQL 17
RUN apt-get update && apt-get install --no-install-recommends -y \
    postgresql-17-pgrouting \
    && rm -rf /var/lib/apt/lists/*

# Copy initialization scripts
COPY ./compose/local/postgres/init-pgrouting.sql /docker-entrypoint-initdb.d/init-pgrouting.sql
