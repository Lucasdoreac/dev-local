#!/usr/bin/env bash
# Executa os gates CI dos quatro repos da etapa em containers descartáveis.
# Os diretórios padrão apontam para os heads locais dos PRs; cada um pode ser
# substituído por uma variável de ambiente para verificar outro checkout.
# O código é montado read-only, copiado para o container e nunca escreve no host.
#
#   ./run-tests.sh                 # API, catálogo, Auth e checks do framework
#   ./run-tests.sh python|internal|auth|framework|e2e|alocacao
#
# O alvo framework reproduz o workflow isolado (compile/import/Behave dry-run).
# O alvo e2e usa Chrome efêmero em host networking para preservar localhost:3000.
set -uo pipefail
cd "$(dirname "$0")"
LAB=$(cd .. && pwd)

PYTHON_SOURCE="${PYTHON_SERVICES_DIR:-$LAB/python-services/.worktrees/python-logger-ci-focused}"
INTERNAL_SOURCE="${INTERNAL_APIS_DIR:-$LAB/shared-resources/.worktrees/internal-api-gate-focused/internal_apis}"
AUTH_SOURCE="${AUTH_SERVICE_DIR:-$LAB/shared-resources/.worktrees/auth-dependencies-focused/auth_service}"
FRAMEWORK_SOURCE="${E2E_FRAMEWORK_DIR:-$LAB/supreme-test-framework}"
PYTHON_IMAGE="python:3.12-slim"
CHROME_IMAGE="selenium/standalone-chrome:4.49.0-20260909"
POETRY_VERSION="2.4.1"
DEV_NETWORK="${DEV_TEST_NETWORK:-labtech-dev_default}"
PROXY_ARGS=(
  -e "HTTP_PROXY=${DEV_TEST_PROXY:-}"
  -e "HTTPS_PROXY=${DEV_TEST_PROXY:-}"
  -e "http_proxy=${DEV_TEST_PROXY:-}"
  -e "https_proxy=${DEV_TEST_PROXY:-}"
)

status=0

describe_source() {
  local name="$1" source="$2"
  if [[ ! -d "$source" ]]; then
    echo "[$name] checkout ausente: $source" >&2
    return 1
  fi
  printf '[%s] %s @ %s\n' \
    "$name" \
    "$(git -C "$source" branch --show-current 2>/dev/null || echo sem-git)" \
    "$(git -C "$source" rev-parse --short HEAD 2>/dev/null || echo sem-sha)"
}

run_poetry_suite() {
  local name="$1" source="$2" test_command="$3" network="${4:-bridge}"
  describe_source "$name" "$source" || return 1
  [[ -f "$source/pyproject.toml" && -f "$source/poetry.lock" ]] || {
    echo "[$name] pyproject.toml ou poetry.lock ausente" >&2
    return 1
  }

  docker run --rm --network "$network" "${PROXY_ARGS[@]}" \
    -v "$source:/source:ro" \
    -e POETRY_VERSION="$POETRY_VERSION" \
    -e TEST_COMMAND="$test_command" \
    -e REDIS_URL="${REDIS_URL:-}" \
    "$PYTHON_IMAGE" sh -ec '
      python -m pip install --disable-pip-version-check --no-cache-dir "poetry==$POETRY_VERSION"
      mkdir -p /workspace
      tar -C /source \
        --exclude=.git --exclude=.worktrees --exclude=__pycache__ \
        --exclude=.pytest_cache --exclude=.mypy_cache --exclude=.venv \
        --exclude=node_modules --exclude="*.env" \
        -cf /tmp/source.tar .
      tar -xf /tmp/source.tar -C /workspace
      cd /workspace
      poetry install --no-interaction --no-ansi --no-root
      sh -ec "$TEST_COMMAND"
    '
}

run_python_services() {
  echo "[python-services] install congelado + pytest"
  run_poetry_suite python-services "$PYTHON_SOURCE" \
    "PYTHONPATH=src poetry run pytest -q"
}

run_internal_apis() {
  echo "[shared-resources/internal_apis] install congelado + pytest"
  run_poetry_suite internal_apis "$INTERNAL_SOURCE" \
    "PYTHONPATH=src poetry run pytest src/Tests -q"
}

start_isolated_redis() {
  local redis_name="labtech-tests-redis-$$"
  (
    cleanup_redis() { docker stop "$redis_name" >/dev/null 2>&1 || true; }
    trap cleanup_redis EXIT
    docker run -d --rm --name "$redis_name" --network "$DEV_NETWORK" \
      redis:8.10.1 redis-server --save "" --appendonly no >/dev/null || exit 1

    local ready=0
    for _ in $(seq 1 20); do
      if docker exec "$redis_name" redis-cli ping 2>/dev/null | grep -q PONG; then
        ready=1
        break
      fi
      sleep 1
    done
    if [[ "$ready" -ne 1 ]]; then
      echo "[auth_service] Redis isolado não ficou pronto" >&2
      exit 1
    fi

    echo "[auth_service] install congelado + pytest + Redis efêmero"
    REDIS_URL="redis://$redis_name:6379/15" run_poetry_suite auth_service "$AUTH_SOURCE" \
      "PYTHONPATH=. poetry run pytest tests -q" "$DEV_NETWORK"
  )
}

run_auth_service() {
  if ! docker network inspect "$DEV_NETWORK" >/dev/null 2>&1; then
    echo "[auth_service] rede Docker ausente: $DEV_NETWORK (suba dev-local primeiro)" >&2
    return 1
  fi
  start_isolated_redis
}

run_framework_checks() {
  describe_source supreme-test-framework "$FRAMEWORK_SOURCE" || return 1
  [[ -f "$FRAMEWORK_SOURCE/requirements.txt" ]] || {
    echo "[supreme-test-framework] requirements.txt ausente" >&2
    return 1
  }

  echo "[supreme-test-framework] install de requirements + compile/import/Behave dry-run"
  docker run --rm --network bridge "${PROXY_ARGS[@]}" \
    -v "$FRAMEWORK_SOURCE:/source:ro" \
    "$PYTHON_IMAGE" sh -ec '
      mkdir -p /workspace
      tar -C /source \
        --exclude=.git --exclude=.worktrees --exclude=__pycache__ \
        --exclude=.pytest_cache --exclude=.venv --exclude=downloads \
        --exclude="*.env" -cf /tmp/source.tar .
      tar -xf /tmp/source.tar -C /workspace
      cd /workspace
      python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
      python -m compileall -q features page_objects utils
      python -c "from utils.browser_setup import setup_webdriver; assert callable(setup_webdriver)"
      behave --dry-run --no-color
    '
}

run_framework_e2e() (
  describe_source supreme-test-framework "$FRAMEWORK_SOURCE" || return 1
  [[ -f "$FRAMEWORK_SOURCE/requirements.txt" ]] || {
    echo "[supreme-test-framework] requirements.txt ausente" >&2
    return 1
  }
  if ! docker network inspect "$DEV_NETWORK" >/dev/null 2>&1; then
    echo "[supreme-test-framework] rede Docker ausente: $DEV_NETWORK (suba dev-local primeiro)" >&2
    return 1
  fi

  local chrome_name="labtech-e2e-chrome-$$"
  local gateway
  gateway="$(docker network inspect "$DEV_NETWORK" --format '{{(index .IPAM.Config 0).Gateway}}')"
  local test_email="codex-e2e-$(date +%s)-$$@udf.edu.br"
  local cleanup_status=0
  cleanup_e2e() {
    local test_status=$?
    trap - EXIT
    docker stop "$chrome_name" >/dev/null 2>&1 || true
    docker compose exec -T mongo mongosh --quiet rooms-reservation-app --eval \
      "db.authentications.deleteMany({email: '$test_email'}).deletedCount" >/dev/null || cleanup_status=1
    local key
    while IFS= read -r key; do
      [[ -n "$key" ]] || continue
      docker compose exec -T redis redis-cli DEL "$key" >/dev/null || cleanup_status=1
    done < <(docker compose exec -T redis redis-cli --scan --pattern "*$test_email*" 2>/dev/null)
    if [[ "$cleanup_status" -ne 0 ]]; then
      echo "[supreme-test-framework] falha ao limpar dados sintéticos ($test_email)" >&2
      test_status=1
    fi
    exit "$test_status"
  }

  local existing
  existing="$(docker compose exec -T mongo mongosh --quiet rooms-reservation-app --eval \
    "db.authentications.countDocuments({email: '$test_email'})" 2>/dev/null | tail -n 1)"
  if [[ "$existing" != "0" ]]; then
    echo "[supreme-test-framework] e-mail sintético já existe; abortando para preservar dados" >&2
    return 1
  fi

  echo "[supreme-test-framework] iniciando Chrome efêmero ($CHROME_IMAGE)"
  docker run -d --rm --name "$chrome_name" --network host --shm-size=1g \
    -e SE_NODE_MAX_SESSIONS=1 \
    -e VIDEO_READY_PORT=9100 \
    -e SE_START_VNC=false \
    -e SE_START_NO_VNC=false \
    -e SE_RECORD_VIDEO=false \
    -e SE_VIDEO_EVENT_DRIVEN=false \
    "$CHROME_IMAGE" >/dev/null || return 1
  trap cleanup_e2e EXIT

  echo "[supreme-test-framework] E2E real contra Reservas local com conta sintética isolada"
  docker run --rm --network "$DEV_NETWORK" "${PROXY_ARGS[@]}" \
    -v "$FRAMEWORK_SOURCE:/source:ro" \
    -v "$LAB/supreme-test-framework/utils/browser_setup.py:/overlay/browser_setup.py:ro" \
    -v "$LAB/supreme-test-framework/tests/test_browser_setup.py:/overlay/test_browser_setup.py:ro" \
    -e SELENIUM_REMOTE_URL="http://$gateway:4444/wd/hub" \
    -e BASE_URL=http://127.0.0.1:3000 \
    -e API_URL="http://$gateway:5000" \
    -e ENV=production \
    -e TEST_EMAIL="$test_email" \
    -e NO_PROXY="$gateway,127.0.0.1,localhost" \
    -e no_proxy="$gateway,127.0.0.1,localhost" \
    "$PYTHON_IMAGE" sh -ec '
      mkdir -p /workspace
      tar -C /source \
        --exclude=.git --exclude=.worktrees --exclude=__pycache__ \
        --exclude=.pytest_cache --exclude=.venv --exclude=downloads \
        --exclude="*.env" -cf /tmp/source.tar .
      tar -xf /tmp/source.tar -C /workspace
      cd /workspace
      cp /overlay/browser_setup.py utils/browser_setup.py
      mkdir -p tests
      cp /overlay/test_browser_setup.py tests/test_browser_setup.py
      sed -i "s/e2e-ci@udf.edu.br/$TEST_EMAIL/g" features/login.feature
      python -m pip install --disable-pip-version-check --no-cache-dir -r requirements.txt
      python -m compileall -q features page_objects utils tests
      python -m unittest discover -s tests -p "test_browser_setup.py" -v
      python - <<"PY"
import json, os, time, urllib.request
url = os.environ["SELENIUM_REMOTE_URL"].removesuffix("/wd/hub") + "/wd/hub/status"
for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            status = json.load(response)
        if status.get("value", {}).get("ready"):
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit(f"Selenium Grid não ficou pronto: {url}")
PY
      behave --no-color
    '
)

run_alocacao() {
  echo "[teachers-allocation] build + pytest (fora do alvo padrão desta etapa)"
  docker build -q -t labtech-alocacao-tests "$LAB/teachers-allocation/backend" >/dev/null || return 1
  docker run --rm labtech-alocacao-tests \
    sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && pytest -v"
}

case "${1:-all}" in
  python)    run_python_services || status=1 ;;
  internal)  run_internal_apis || status=1 ;;
  auth)      run_auth_service || status=1 ;;
  framework) run_framework_checks || status=1 ;;
  e2e)       run_framework_e2e || status=1 ;;
  alocacao)  run_alocacao || status=1 ;;
  all)
    run_python_services || status=1
    echo
    run_internal_apis || status=1
    echo
    run_auth_service || status=1
    echo
    run_framework_checks || status=1
    ;;
  *)
    echo "uso: $0 [python|internal|auth|framework|alocacao|all]" >&2
    exit 2
    ;;
esac

if [[ "$status" -eq 0 ]]; then
  echo "=== RUN-TESTS: PASS ==="
else
  echo "=== RUN-TESTS: FAIL ==="
fi
exit "$status"
