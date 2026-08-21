# ---- Build React frontend ----
FROM node:20-slim AS frontend-build
WORKDIR /app/dax_ui/frontend
COPY dax_ui/frontend/package*.json ./
RUN npm ci --prefer-offline
COPY dax_ui/frontend/ ./
RUN npm run build

# ---- Python runtime ----
FROM python:3.13-slim AS runtime

# System deps for DuckDB and other native libs
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt requirements-ui.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-ui.txt

# Copy application code
COPY dax_engine/ ./dax_engine/
COPY dax_parser/ ./dax_parser/
COPY dax_project/ ./dax_project/
COPY dax_ui/ ./dax_ui/
COPY dax_compiler.py semantic_model_loader.py semantic_model.yaml dax_sql_mapping.json ./

# Copy built React frontend from build stage
COPY --from=frontend-build /app/dax_ui/frontend/dist ./dax_ui/frontend/dist

# Create non-root user
RUN useradd -m -s /bin/bash daxuser
USER daxuser

# Default env vars
ENV DAX_SERVER_MODE=server \
    DAX_PROJECT_PATH=/data/project \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import requests; r=requests.get('http://localhost:8080/runtime/meta', timeout=5); assert r.status_code==200"

# Start in server mode by default
CMD ["python", "-m", "dax_ui", \
     "--mode", "server", \
     "--host", "0.0.0.0", \
     "--port", "8080", \
     "--log-level", "info"]
