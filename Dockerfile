FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY crm_spike.py .

EXPOSE 8000

# --forwarded-allow-ips é necessário porque a aplicação roda atrás do Traefik.
# Sem isso, o Uvicorn ignora X-Forwarded-Proto e monta redirects em http://.
CMD ["uvicorn", "crm_spike:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--forwarded-allow-ips", "*"]
