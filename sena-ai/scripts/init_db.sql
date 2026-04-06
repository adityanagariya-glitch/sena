-- Database initialization script
-- Creates the restricted application user (NOT a superuser)
-- Superuser 'sena' is for migrations only; runtime uses 'sena_app'

-- Create extensions
CREATE EXTENSION IF NOT EXISTS "pgvector";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Create restricted application role
-- CRITICAL: This user must NOT be a superuser. Superusers bypass RLS.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'sena_app') THEN
        CREATE ROLE sena_app LOGIN PASSWORD 'localdev';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE sena_ai TO sena_app;
GRANT USAGE ON SCHEMA public TO sena_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO sena_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO sena_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO sena_app;
