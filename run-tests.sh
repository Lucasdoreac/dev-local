#!/usr/bin/env bash
# Roda as suítes de teste do produto Reservas em containers descartáveis,
# construídos a partir do Dockerfile de cada serviço (mesma imagem que
# roda em dev via compose.yaml — não um ambiente pip-install ad-hoc à
# parte). Nada é escrito na árvore de trabalho: cada `docker build` usa
# uma tag `-tests` própria, e os containers de teste rodam com --rm.
#
#   ./run-tests.sh            # roda as duas suítes
#   ./run-tests.sh python     # só python-services
#   ./run-tests.sh internal   # só internal_apis
#   ./run-tests.sh auth       # só auth_service
#   ./run-tests.sh alocacao   # só o backend da Alocação (teachers-allocation)
#   ./run-tests.sh e2e        # E2E do supreme-test-framework (Behave + Selenium) contra a pilha no ar
set -uo pipefail
cd "$(dirname "$0")"
LAB=$(cd .. && pwd)

status=0

run_python_services() {
  echo "[python-services] build + pytest"
  if [ -f "$LAB/python-services/Dockerfile" ]; then
    docker build -q -t labtech-python-services-tests "$LAB/python-services" >/dev/null || return 1
    docker run --rm \
      -e MONGO_URI=mongodb://localhost:27017/ \
      -e MONGO_DATABASE=rooms-reservation-app \
      -e FLASK_ENV=development \
      -e SERVER_NAME=localhost:5000 \
      labtech-python-services-tests \
      sh -c "poetry run pytest -v"  # arquivos: [tool.pytest.ini_options] do pyproject
  else
    # O main atual não contém Dockerfile. Reutiliza a imagem do serviço Compose
    # em um container descartável; o bind mount aponta para o checkout atual.
    docker compose run --rm --no-deps api sh -lc \
      "cd /python-services && poetry install --no-interaction --no-root && PYTHONPATH=src poetry run pytest -v"
  fi
}

run_internal_apis() {
  echo "[internal_apis] build + pytest"
  if [ -f "$LAB/shared-resources/internal_apis/Dockerfile" ]; then
    docker build -q -t labtech-internal-apis-tests "$LAB/shared-resources/internal_apis" >/dev/null || return 1
    docker run --rm \
      labtech-internal-apis-tests \
      sh -c "PYTHONPATH=src poetry run pytest src/Tests -v"
  else
    # A imagem já existe no Compose, mas o main atual não contém Dockerfile.
    docker compose run --rm --no-deps internal sh -lc \
      "cd /internal_apis && poetry install --no-interaction --no-root && PYTHONPATH=src poetry run pytest src/Tests -v"
  fi
}

run_auth_service() {
  echo "[auth_service] build + pytest"
  docker build -q -t labtech-auth-service-tests "$LAB/shared-resources/auth_service" >/dev/null || return 1
  docker run --rm \
    labtech-auth-service-tests \
    sh -c "poetry run pytest tests -v"
}

run_alocacao() {
  echo "[alocacao] build + pytest"
  docker build -q -t labtech-alocacao-tests "$LAB/teachers-allocation/backend" >/dev/null || return 1
  docker run --rm labtech-alocacao-tests \
    sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && pytest -v"
}

# E2E no navegador (Chromium no container) contra a pilha que já está no ar
# (`docker compose up -d`): usa a rede do host da VM para abrir 127.0.0.1:3000
# como o navegador do Mac abriria. Não entra no "all": precisa da pilha.
run_e2e() {
  echo "[e2e] build + behave"
  curl -sf -o /dev/null http://127.0.0.1:3000/ \
    || { echo "frontend fora do ar em 127.0.0.1:3000: rode docker compose up -d"; return 1; }
  docker build -q -t labtech-e2e-tests "$LAB/supreme-test-framework" >/dev/null || return 1
  docker run --rm --network host \
    -e WINDOW_WIDTH=1280 -e WINDOW_HEIGHT=900 \
    labtech-e2e-tests \
    behave --no-color --logging-level=WARNING --no-junit \
      -D BASE_URL=http://127.0.0.1:3000 -D API_URL=http://127.0.0.1:5050
}

case "${1:-all}" in
  python)   run_python_services || status=1 ;;
  internal) run_internal_apis   || status=1 ;;
  auth)     run_auth_service    || status=1 ;;
  alocacao) run_alocacao        || status=1 ;;
  e2e)      run_e2e             || status=1 ;;
  all)
    run_python_services || status=1
    echo
    run_internal_apis   || status=1
    echo
    run_auth_service    || status=1
    echo
    run_alocacao        || status=1
    ;;
  *)
    echo "uso: $0 [python|internal|auth|alocacao|e2e|all]" >&2
    exit 2
    ;;
esac

if [ "$status" -eq 0 ]; then
  echo "=== RUN-TESTS: PASS ==="
else
  echo "=== RUN-TESTS: FAIL ==="
fi
exit "$status"
