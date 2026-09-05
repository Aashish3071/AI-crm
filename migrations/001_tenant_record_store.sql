BEGIN;

CREATE TABLE IF NOT EXISTS crm_companies (
    id text PRIMARY KEY,
    revision bigint NOT NULL DEFAULT 0,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS crm_records (
    company_id text NOT NULL REFERENCES crm_companies(id) ON DELETE CASCADE,
    collection text NOT NULL,
    record_id text NOT NULL,
    data jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (company_id, collection, record_id),
    CONSTRAINT crm_collection_name CHECK (collection ~ '^[A-Za-z][A-Za-z0-9]*$')
);

CREATE INDEX IF NOT EXISTS crm_records_collection_idx ON crm_records(company_id, collection);
CREATE INDEX IF NOT EXISTS crm_records_data_gin_idx ON crm_records USING gin(data);

CREATE TABLE IF NOT EXISTS crm_links (
    company_id text NOT NULL,
    from_collection text NOT NULL,
    from_id text NOT NULL,
    relationship text NOT NULL,
    to_collection text NOT NULL,
    to_id text NOT NULL,
    PRIMARY KEY (company_id, from_collection, from_id, relationship, to_collection, to_id),
    FOREIGN KEY (company_id, from_collection, from_id)
        REFERENCES crm_records(company_id, collection, record_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED,
    FOREIGN KEY (company_id, to_collection, to_id)
        REFERENCES crm_records(company_id, collection, record_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS crm_links_target_idx ON crm_links(company_id, to_collection, to_id);

CREATE TABLE IF NOT EXISTS crm_auth_companies (
    id text PRIMARY KEY,
    name text NOT NULL,
    status text NOT NULL CHECK (status IN ('Active', 'Inactive')),
    created_at bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS crm_auth_users (
    id text PRIMARY KEY,
    company_id text NOT NULL REFERENCES crm_auth_companies(id) ON DELETE CASCADE,
    name text NOT NULL,
    email text NOT NULL,
    role text NOT NULL,
    status text NOT NULL CHECK (status IN ('Active', 'Inactive')),
    password_hash text NOT NULL,
    created_at bigint NOT NULL,
    password_changed_at bigint NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS crm_auth_users_email_idx ON crm_auth_users(lower(email));
CREATE INDEX IF NOT EXISTS crm_auth_users_company_idx ON crm_auth_users(company_id, status);

COMMIT;
