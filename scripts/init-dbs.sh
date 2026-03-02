#!/bin/bash
set -e
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<-EOSQL
    CREATE DATABASE ${EVOLUTION_DB_NAME:-evolution};
    CREATE DATABASE ${MIDDLEWARE_DB_NAME:-middleware};
EOSQL
