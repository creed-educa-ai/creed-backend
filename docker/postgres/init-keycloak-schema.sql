-- Schema dedicado do Keycloak no Postgres local, espelhando o desenho de producao
-- (README do creed-infrastructure: RDS unico, schema por componente, como o N8N).
--
-- O N8N cria o schema dele sozinho; o Keycloak NAO cria -- ele espera o schema
-- ja existir e falha no boot se nao existir. Por isso este arquivo.
--
-- O Postgres so roda /docker-entrypoint-initdb.d/ quando o volume nasce vazio:
-- quem ja tem o volume `pgdata` precisa de um `docker compose down -v` uma vez.
CREATE SCHEMA IF NOT EXISTS keycloak;
