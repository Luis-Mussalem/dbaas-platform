# syntax=docker/dockerfile:1

# =============================================================================
# Stage 1 — builder: instala as dependências Python num virtualenv isolado.
# Separar o build do runtime mantém a imagem final pequena: ferramentas de
# compilação e caches de pip ficam nesta stage e nunca chegam à imagem final.
# =============================================================================
# Base pinada em bookworm (Debian 12) de propósito: a tag flutuante
# python:3.12-slim já migrou para trixie (Debian 13), cujo libldap quebra a
# instalação do client PostgreSQL do PGDG. Pinar mantém o build reprodutível.
FROM python:3.12-slim-bookworm AS builder

# - PYTHONDONTWRITEBYTECODE: não gera .pyc durante o build (imagem mais limpa)
# - PIP_NO_CACHE_DIR / PIP_DISABLE_PIP_VERSION_CHECK: build mais rápido e leve
ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Cria um venv dedicado em /opt/venv. Copiar o venv inteiro para a stage de
# runtime é mais simples e previsível que recompilar lá.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copiar só o requirements primeiro aproveita o cache de camadas do Docker:
# enquanto requirements.txt não muda, esta camada (a mais cara) é reaproveitada.
COPY requirements.txt .
RUN pip install -r requirements.txt


# =============================================================================
# Stage 2 — runtime: imagem final mínima que apenas executa a aplicação.
# =============================================================================
FROM python:3.12-slim-bookworm AS runtime

# - PYTHONUNBUFFERED: logs aparecem na hora (sem buffer) — essencial em container
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# postgresql-client-16 fornece pg_dump, pg_restore e pg_basebackup, usados pelo
# serviço de backup (PHASE 5). A versão precisa ser >= à do servidor gerenciado
# (postgres:16) — por isso usamos o repositório oficial PGDG, já que o Debian
# bookworm traz apenas o client 15 por padrão.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl ca-certificates gnupg; \
    install -d /usr/share/postgresql-common/pgdg; \
    curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc; \
    echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends postgresql-client-16; \
    apt-get purge -y --auto-remove curl gnupg; \
    rm -rf /var/lib/apt/lists/*

# Copia o venv pronto da stage builder — sem pip install nem toolchain aqui.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Usuário não-root (defesa em profundidade): se a aplicação for comprometida,
# o atacante não tem privilégios de root dentro do container.
RUN useradd --create-home --uid 10001 appuser

# Código da aplicação + migrations. Copiado por último porque muda com mais
# frequência que as dependências — preserva o cache das camadas acima.
COPY --chown=appuser:appuser src ./src
COPY --chown=appuser:appuser alembic ./alembic
COPY --chown=appuser:appuser alembic.ini ./

USER appuser

EXPOSE 8000

# Healthcheck bate no mesmo GET /health usado pela infra/load balancer.
# Usa urllib (stdlib) para não depender de curl na imagem final.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health').status==200 else 1)"

# Sobe a API. As migrations (alembic upgrade head) são executadas como passo
# separado no deploy — não no CMD — para não acoplar startup da app a migration.
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
