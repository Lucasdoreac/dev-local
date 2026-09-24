#!/usr/bin/env bash
# Sobe o que falta para o fluxo de APROVAÇÃO rodar local (dev):
#   - MinIO (labtech_minio) para o PDF do evento;
#   - recria python_services_api com MINIO_* (mesma config de antes + 3 variáveis).
# Credencial do MinIO: dev-local/minio.env (gerada, fora de qualquer repo).
# Email: em FLASK_ENV=development o python-services NÃO envia — devolve o HTML
# (rota /administration_approval), então nenhum email sai daqui.
# Rascunho do compose de dev/staging (proposta: crispy-octo-cluster).
# Imagem do MinIO vem do Quay: o Docker Hub recusou `minio/minio` (23/09/2026).
set -euo pipefail
cd "$(dirname "$0")"
source ./minio.env
NET=java-services_default
LAB=$(cd .. && pwd)

if ! docker ps -a --format '{{.Names}}' | grep -qx labtech_minio; then
  # Alias com HÍFEN: o MinIO recusa hostname com "_" (InvalidRequest: invalid
  # hostname) — o upload do PDF falhava calado com o nome do container.
  docker run -d --name labtech_minio --network "$NET" --network-alias labtech-minio \
    -p 127.0.0.1:9000:9000 -p 127.0.0.1:9001:9001 \
    -e MINIO_ROOT_USER="$MINIO_ROOT_USER" -e MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
    -v labtech_minio_data:/data \
    quay.io/minio/minio server /data --console-address :9001 >/dev/null
fi

# Container já existente sem o alias: reconecta com ele.
if ! docker inspect labtech_minio --format '{{json .NetworkSettings.Networks}}' | grep -q labtech-minio; then
  docker network disconnect "$NET" labtech_minio && docker network connect --alias labtech-minio "$NET" labtech_minio
fi

docker rm -f python_services_api >/dev/null 2>&1 || true
docker run -d --name python_services_api --network "$NET" -p 5000:5000 \
  -v "$LAB/python-services:/app" -w /app \
  -e PYTHONPATH=/app/src \
  -e MONGO_URI=mongodb://labtech_mongo:27017/ -e MONGO_DATABASE=rooms-reservation-app \
  -e FLASK_ENV=development \
  -e MINIO_URL=http://labtech-minio:9000 \
  -e MINIO_ACCESS_KEY="$MINIO_ROOT_USER" -e MINIO_SECRET_KEY="$MINIO_ROOT_PASSWORD" \
  python:3.12-slim sh -c "pip install --no-cache-dir flask flask-cors requests pymongo flasgger typst minio gunicorn python-dotenv sib-api-v3-sdk && python main.py" >/dev/null

for i in $(seq 1 90); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' -m 2 http://127.0.0.1:5000/apidocs/)" = 200 ] && break; sleep 2
done
echo "minio: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:9000/minio/health/live)  api: $(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:5000/apidocs/)"
