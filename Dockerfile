# Alfa Insight: сервис новостной аналитики + собранный интерфейс (frontend/dist). Один образ, одна команда запуска.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.lock.txt ./
RUN pip install -r requirements.lock.txt
COPY contracts ./contracts
COPY services ./services
COPY scripts ./scripts
COPY data ./data
COPY frontend/dist ./frontend/dist
RUN useradd --system --uid 10001 app && mkdir -p /app/data/runtime && chown -R app /app/data/runtime
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health').status==200 else 1)"
CMD ["python", "-m", "services.insight.server"]
