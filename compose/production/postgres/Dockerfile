FROM postgis/postgis:18-3.6

# Install pgRouting extension for PostgreSQL 18
RUN apt-get update && apt-get install --no-install-recommends -y \
    postgresql-18-pgrouting \
    && rm -rf /var/lib/apt/lists/*

# Copy initialization scripts
COPY ./compose/local/postgres/init-pgrouting.sql /docker-entrypoint-initdb.d/init-pgrouting.sql
