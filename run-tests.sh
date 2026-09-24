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
set -uo pipefail
cd "$(dirname "$0")"
LAB=$(cd .. && pwd)

status=0

run_python_services() {
  echo "[python-services] build + pytest"
  docker build -q -t labtech-python-services-tests "$LAB/python-services" >/dev/null || return 1
  docker run --rm \
    -e MONGO_URI=mongodb://localhost:27017/ \
    -e MONGO_DATABASE=rooms-reservation-app \
    -e FLASK_ENV=development \
    -e SERVER_NAME=localhost:5000 \
    labtech-python-services-tests \
    sh -c "poetry run pytest -v"  # arquivos: [tool.pytest.ini_options] do pyproject
}

run_internal_apis() {
  echo "[internal_apis] build + pytest"
  docker build -q -t labtech-internal-apis-tests "$LAB/shared-resources/internal_apis" >/dev/null || return 1
  docker run --rm \
    labtech-internal-apis-tests \
    sh -c "PYTHONPATH=src poetry run pytest src/Tests -v"
}

run_auth_service() {
  echo "[auth_service] build + pytest"
  docker build -q -t labtech-auth-service-tests "$LAB/shared-resources/auth_service" >/dev/null || return 1
  docker run --rm \
    labtech-auth-service-tests \
    sh -c "poetry run pytest tests -v"
}

case "${1:-all}" in
  python)   run_python_services || status=1 ;;
  internal) run_internal_apis   || status=1 ;;
  auth)     run_auth_service    || status=1 ;;
  all)
    run_python_services || status=1
    echo
    run_internal_apis   || status=1
    echo
    run_auth_service    || status=1
    ;;
  *)
    echo "uso: $0 [python|internal|auth|all]" >&2
    exit 2
    ;;
esac

if [ "$status" -eq 0 ]; then
  echo "=== RUN-TESTS: PASS ==="
else
  echo "=== RUN-TESTS: FAIL ==="
fi
exit "$status"
