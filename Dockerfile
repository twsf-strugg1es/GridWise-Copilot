# GridWise Copilot -- fallback execution path for the judges.
#
# Contains NO credentials. The model key is supplied at run time:
#   docker run -p 8000:8000 -e LLM_API_KEY=sk-... <image>

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# PuLP ships its own CBC binary, so no system solver package is needed. Install
# dependencies first so a code change does not invalidate the wheel layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY optimizer/ ./optimizer/
COPY scripts/ ./scripts/
COPY tests/ ./tests/

EXPOSE 8000

# Bind 0.0.0.0 so the container is reachable from outside, per the guide.
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
