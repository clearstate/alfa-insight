-- company_profile: схема PostgreSQL (миграция 0001_init).
-- СГЕНЕРИРОВАНО из services/company_profile/db.py (render_ddl). Не править вручную: менять TABLES и
-- перегенерировать: python scripts/company_profile_cli.py ddl > services/company_profile/db_sql/schema.postgres.sql
-- Применяется автоматически ETL (SqlStore.migrate).

CREATE SCHEMA IF NOT EXISTS company_profile;

CREATE TABLE IF NOT EXISTS company_profile.schema_migrations (
    version TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (version)
);

CREATE TABLE IF NOT EXISTS company_profile.etl_runs (
    run_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    source_files JSONB,
    stats JSONB,
    counters JSONB,
    samples JSONB,
    rules_hash TEXT,
    schema_version TEXT,
    error TEXT,
    PRIMARY KEY (run_id)
);

CREATE INDEX IF NOT EXISTS etl_runs_status_idx ON company_profile.etl_runs (status, finished_at);

CREATE TABLE IF NOT EXISTS company_profile.companies (
    synthetic_u TEXT NOT NULL,
    org_type TEXT,
    okfs_name TEXT,
    company_age_years_gradation TEXT,
    eco_mark_label TEXT,
    mainokved_code TEXT,
    mainokved_name TEXT,
    negativemark BOOLEAN,
    amount_workers_fns_gradation TEXT,
    amount_workers_spark_gradation TEXT,
    cl_type TEXT,
    cl_product_rko_mark BOOLEAN,
    cl_product_gar_mark BOOLEAN,
    cl_product_loa_mark BOOLEAN,
    cl_product_lea_mark BOOLEAN,
    cl_product_dep_mark BOOLEAN,
    cl_product_zpp_mark BOOLEAN,
    fts_flag BOOLEAN,
    fts_country_name TEXT,
    factoring_mark BOOLEAN,
    revenue_company DOUBLE PRECISION,
    group_id TEXT,
    city TEXT,
    region TEXT,
    source_line INTEGER NOT NULL,
    PRIMARY KEY (synthetic_u)
);

CREATE INDEX IF NOT EXISTS companies_group_idx ON company_profile.companies (group_id);

CREATE INDEX IF NOT EXISTS companies_okved_idx ON company_profile.companies (mainokved_code);

CREATE INDEX IF NOT EXISTS companies_region_idx ON company_profile.companies (region);

CREATE TABLE IF NOT EXISTS company_profile.quarantined_companies (
    company_id TEXT NOT NULL,
    source_lines JSONB NOT NULL,
    PRIMARY KEY (company_id)
);

CREATE TABLE IF NOT EXISTS company_profile.company_issues (
    company_id TEXT NOT NULL,
    issue_no INTEGER NOT NULL,
    code TEXT NOT NULL,
    field TEXT,
    message TEXT NOT NULL,
    source_file TEXT NOT NULL,
    lines JSONB NOT NULL,
    PRIMARY KEY (company_id, issue_no)
);

CREATE INDEX IF NOT EXISTS company_issues_code_idx ON company_profile.company_issues (code);

CREATE TABLE IF NOT EXISTS company_profile.person_links (
    synthetic_f TEXT NOT NULL,
    synthetic_u TEXT NOT NULL,
    source_line INTEGER NOT NULL,
    PRIMARY KEY (synthetic_f, synthetic_u)
);

CREATE INDEX IF NOT EXISTS person_links_company_idx ON company_profile.person_links (synthetic_u);

CREATE TABLE IF NOT EXISTS company_profile.payments (
    payer TEXT NOT NULL,
    beneficiary TEXT NOT NULL,
    pay_amt DOUBLE PRECISION NOT NULL,
    pay_cnt BIGINT NOT NULL,
    source_line INTEGER NOT NULL,
    n_rows INTEGER NOT NULL,
    PRIMARY KEY (payer, beneficiary)
);

CREATE INDEX IF NOT EXISTS payments_beneficiary_idx ON company_profile.payments (beneficiary);

CREATE TABLE IF NOT EXISTS company_profile.self_payments (
    company_id TEXT NOT NULL,
    pay_amt DOUBLE PRECISION NOT NULL,
    pay_cnt BIGINT NOT NULL,
    n_rows INTEGER NOT NULL,
    PRIMARY KEY (company_id)
);

CREATE TABLE IF NOT EXISTS company_profile.users (
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    display_name TEXT,
    synthetic BOOLEAN NOT NULL,
    priority_topics JSONB,
    PRIMARY KEY (user_id)
);

CREATE TABLE IF NOT EXISTS company_profile.user_companies (
    user_id TEXT NOT NULL,
    company_id TEXT NOT NULL,
    PRIMARY KEY (user_id, company_id)
);

CREATE INDEX IF NOT EXISTS user_companies_company_idx ON company_profile.user_companies (company_id);

CREATE TABLE IF NOT EXISTS company_profile.company_profiles (
    company_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    built_at TIMESTAMPTZ NOT NULL,
    is_large_business BOOLEAN,
    okved_code TEXT,
    okved_section TEXT,
    region TEXT,
    okved_levels JSONB NOT NULL,
    topic_names JSONB NOT NULL,
    profile JSONB NOT NULL,
    PRIMARY KEY (company_id)
);

CREATE INDEX IF NOT EXISTS company_profiles_okved_levels_gin ON company_profile.company_profiles USING GIN (okved_levels);

CREATE INDEX IF NOT EXISTS company_profiles_topics_gin ON company_profile.company_profiles USING GIN (topic_names);

CREATE INDEX IF NOT EXISTS company_profiles_large_idx ON company_profile.company_profiles (is_large_business);

CREATE TABLE IF NOT EXISTS company_profile.demo_companies (
    slot TEXT NOT NULL,
    company_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (slot)
);
