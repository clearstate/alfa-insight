-- Рекомендуемое разграничение прав в PostgreSQL (применяет участник 6, пароли — из секретов, не из репозитория).
-- etl     — единственная роль с правом записи в схему company_profile;
-- api     — сервис company_profile: только чтение;
-- reader  — сервисы участников 3 и 4 (агент, ранжирование): только чтение аналитических таблиц,
--           без users/user_companies и без построчных платежей. Права пользователей проверяет API, а не БД.
CREATE ROLE company_profile_etl LOGIN;
CREATE ROLE company_profile_api LOGIN;
CREATE ROLE company_profile_reader LOGIN;

GRANT USAGE, CREATE ON SCHEMA company_profile TO company_profile_etl;
GRANT ALL ON ALL TABLES IN SCHEMA company_profile TO company_profile_etl;

GRANT USAGE ON SCHEMA company_profile TO company_profile_api, company_profile_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA company_profile TO company_profile_api;
-- companies (сырые поля, включая NEGATIVEMARK), payments, person_links, users — читателям не выдаются.
GRANT SELECT ON company_profile.company_profiles, company_profile.demo_companies, company_profile.etl_runs
    TO company_profile_reader;
