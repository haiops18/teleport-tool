FROM python:3.12-slim
RUN useradd --system --uid 10001 scanner && mkdir -p /data/sessions /data/exports && chown -R scanner:scanner /data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
USER scanner
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
