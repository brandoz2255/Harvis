-- Runs FIRST in /docker-entrypoint-initdb.d (000_ sorts before every other
-- mounted file). init-db.sh also creates these but sorts LAST ("i" > "0"/"a"),
-- so anything earlier that needs an extension would fail without this.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
