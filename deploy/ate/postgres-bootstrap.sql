-- Idempotent Substrate/OpenFGA database bootstrap for ate-system.
--
-- `ate-setup deploy` normally creates these roles and grants once, before the
-- API server starts. A recreated Longhorn volume loses them while the
-- StatefulSet keeps running a fresh, empty PostgreSQL, so every atepi replica
-- crash-loops on `role "substrate_readwrite_user" does not exist` and later on
-- `relation "store" does not exist` (OpenFGA queries the unqualified table).
--
-- Run this after PostgreSQL is ready and before/while ate-api-server starts:
--   kubectl -n ate-system apply -f deploy/ate/postgres-bootstrap-job.yaml
-- or by hand:
--   kubectl -n ate-system exec -i postgres-0 -c postgres -- \
--     psql -U postgres -d atepg -v ON_ERROR_STOP=1 < deploy/ate/postgres-bootstrap.sql
--
-- The API server runs migrations as substrate_owner after this; the schema and
-- default privileges below let it create tables that substrate_readwrite can
-- use, and set the search_path OpenFGA needs for its unqualified queries.

DO $$ BEGIN
  CREATE ROLE substrate_owner NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE ROLE substrate_readwrite NOLOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE ROLE substrate_owner_user LOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
  CREATE ROLE substrate_readwrite_user LOGIN;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

GRANT substrate_owner TO substrate_owner_user;
GRANT substrate_readwrite TO substrate_readwrite_user;

GRANT CONNECT, CREATE ON DATABASE atepg TO substrate_owner;
GRANT CONNECT ON DATABASE atepg TO substrate_readwrite;

CREATE SCHEMA IF NOT EXISTS substrate AUTHORIZATION substrate_owner;

GRANT USAGE ON SCHEMA substrate TO substrate_owner_user, substrate_readwrite, substrate_readwrite_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA substrate TO substrate_readwrite;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA substrate TO substrate_readwrite;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA substrate TO substrate_readwrite;

ALTER DEFAULT PRIVILEGES FOR ROLE substrate_owner IN SCHEMA substrate
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO substrate_readwrite;
ALTER DEFAULT PRIVILEGES FOR ROLE substrate_owner IN SCHEMA substrate
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO substrate_readwrite;
ALTER DEFAULT PRIVILEGES FOR ROLE substrate_owner IN SCHEMA substrate
  GRANT EXECUTE ON FUNCTIONS TO substrate_readwrite;

-- OpenFGA's postgres adapter issues unqualified statements (SELECT ... FROM
-- store), and the API server sets search_path per connection; the database and
-- role defaults cover the replicas and any psql session that forgets it.
ALTER DATABASE atepg SET search_path TO substrate, public;
ALTER ROLE substrate_owner SET search_path TO substrate, public;
ALTER ROLE substrate_readwrite SET search_path TO substrate, public;
ALTER ROLE substrate_owner_user SET search_path TO substrate, public;
ALTER ROLE substrate_readwrite_user SET search_path TO substrate, public;
