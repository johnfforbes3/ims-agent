# IMS Agent — production Dockerfile
# Build: docker build -t ims-agent .
# Run:   docker run -p 8080:8080 --env-file .env ims-agent

FROM python:3.11-slim AS base

# System deps for numpy/pandas + ffmpeg for future Whisper STT
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user
RUN groupadd --gid 1001 imsagent \
 && useradd --uid 1001 --gid 1001 --no-create-home --shell /bin/false imsagent

WORKDIR /app

# Upgrade pip first (pip <26.0 has known CVEs)
RUN pip install --no-cache-dir --upgrade pip

# Install dependencies as root before dropping privileges
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY agent/ ./agent/
COPY main.py .

# Persistent data directories owned by non-root user
RUN mkdir -p data reports logs \
 && chown -R imsagent:imsagent /app

USER imsagent

# Dashboard port
EXPOSE 8080

# Docker / orchestrator health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default: serve dashboard + accept API calls
CMD ["python", "main.py", "--serve"]
