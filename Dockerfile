FROM python:3.11-slim-bookworm

ENV TZ=America/Los_Angeles PYTHONUNBUFFERED=1

# pyodbc + Microsoft ODBC Driver 18, the same driver the other pk-apps use.
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl gnupg build-essential && \
    curl -fsSL https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml .
COPY pkmrp ./pkmrp
RUN pip install --no-cache-dir -e ".[dev]" && \
    apt-get purge -y --auto-remove build-essential && rm -rf /var/lib/apt/lists/*
COPY tests ./tests

# Shared access-control module (build context 'shared' -> pk-server-manager/shared).
# The dev image builds without it; the app then runs without sign-in checks.
COPY --from=shared /pk_access.py ./pk_access.py
COPY docker-entrypoint.sh .
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
CMD ["./docker-entrypoint.sh"]
