#!/bin/bash
# Creates the platform2 database and p2 user alongside the navnet database.
# Runs automatically on first postgres container start.
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE navnet;
    CREATE USER p2 WITH PASSWORD '${P2_DB_PASSWORD:-changeme}';
    CREATE DATABASE platform2;
    GRANT ALL PRIVILEGES ON DATABASE platform2 TO p2;
    \c platform2
    CREATE EXTENSION IF NOT EXISTS timescaledb;
    GRANT ALL ON SCHEMA public TO p2;
EOSQL
