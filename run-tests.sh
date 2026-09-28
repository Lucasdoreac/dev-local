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
# O alvo e2e usa runner e Chrome descartáveis em Docker contra a pilha Compose.
set -uo pipefail
cd "$(dirname "$0")"
LAB=$(cd .. && pwd)

PYTHON_SOURCE="${PYTHON_SERVICES_DIR:-$LAB/python-services/.worktrees/python-deps-on-gate}"
INTERNAL_SOURCE="${INTERNAL_APIS_DIR:-$LAB/shared-resources/.worktrees/catalog-deps-on-gate/internal_apis}"
AUTH_SOURCE="${AUTH_SERVICE_DIR:-$LAB/shared-resources/.worktrees/auth-dependencies-focused/auth_service}"
FRAMEWORK_SOURCE="${E2E_FRAMEWORK_DIR:-$LAB/supreme-test-framework/.worktrees/e2e-dependencies-focused}"
LATEST_PYTHON_IMAGE="labtech-dev-runner-python:3.14.7"
BASELINE_PYTHON_IMAGE="${BASELINE_PYTHON_TEST_IMAGE:-$LATEST_PYTHON_IMAGE}"
PYTHON_SERVICES_TEST_IMAGE="${PYTHON_SERVICES_TEST_IMAGE:-$BASELINE_PYTHON_IMAGE}"
INTERNAL_APIS_TEST_IMAGE="${INTERNAL_APIS_TEST_IMAGE:-$BASELINE_PYTHON_IMAGE}"
AUTH_SERVICE_TEST_IMAGE="${AUTH_SERVICE_TEST_IMAGE:-$LATEST_PYTHON_IMAGE}"
PYTHON_TEST_DOCKERFILE="$LAB/dev-local/dockerfiles/Dockerfile.test-python"
CHROME_IMAGE="selenium/standalone-chrome:4.49.0-20260909"
POETRY_VERSION="2.4.1"
DEV_NETWORK="${DEV_TEST_NETWORK:-labtech-dev_default}"
LATEST_PYTHON_IMAGE_READY=0
TEST_CACHE_ROOT="${LABTECH_TEST_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/labtech-dev-local-tests}"
POETRY_CACHE_HOST="$TEST_CACHE_ROOT/pypoetry"
PIP_CACHE_HOST="$TEST_CACHE_ROOT/pip"
mkdir -p "$POETRY_CACHE_HOST" "$PIP_CACHE_HOST" || {
  echo "[runner] não foi possível criar o cache local de dependências" >&2
  exit 1
}
PYTHON_CACHE_ARGS=(
  -v "$POETRY_CACHE_HOST:/root/.cache/pypoetry"
  -v "$PIP_CACHE_HOST:/root/.cache/pip"
)
PYTHON_CACHE_ENVS=(
  -e POETRY_CACHE_DIR=/root/.cache/pypoetry
  -e PIP_CACHE_DIR=/root/.cache/pip
)
PROXY_ARGS=(
  -e "HTTP_PROXY=${DEV_TEST_PROXY:-}"
  -e "HTTPS_PROXY=${DEV_TEST_PROXY:-}"
  -e "http_proxy=${DEV_TEST_PROXY:-}"
  -e "https_proxy=${DEV_TEST_PROXY:-}"
)

status=0

ensure_python_test_image() {
  local image="$1"
  if [[ "$image" != "$LATEST_PYTHON_IMAGE" || "$LATEST_PYTHON_IMAGE_READY" -eq 1 ]]; then
    return 0
  fi
  docker build --quiet \
    --tag "$LATEST_PYTHON_IMAGE" \
    --build-arg "POETRY_VERSION=$POETRY_VERSION" \
    --file "$PYTHON_TEST_DOCKERFILE" \
    "$(dirname "$PYTHON_TEST_DOCKERFILE")" >/dev/null || return 1
  LATEST_PYTHON_IMAGE_READY=1
}

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
  local name="$1" source="$2" test_command="$3" network="${4:-bridge}" image="${5:-$LATEST_PYTHON_IMAGE}"
  describe_source "$name" "$source" || return 1
  ensure_python_test_image "$image" || return 1
  [[ -f "$source/pyproject.toml" && -f "$source/poetry.lock" ]] || {
    echo "[$name] pyproject.toml ou poetry.lock ausente" >&2
    return 1
  }

  docker run --rm --network "$network" "${PROXY_ARGS[@]}" \
    "${PYTHON_CACHE_ARGS[@]}" "${PYTHON_CACHE_ENVS[@]}" \
    -v "$source:/source:ro" \
    -e TEST_COMMAND="$test_command" \
    -e REDIS_URL="${REDIS_URL:-}" \
    "$image" sh -ec '
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
    "PYTHONPATH=src poetry run pytest -q" bridge "$PYTHON_SERVICES_TEST_IMAGE"
}

run_internal_apis() {
  echo "[shared-resources/internal_apis] install congelado + pytest"
  run_poetry_suite internal_apis "$INTERNAL_SOURCE" \
    "PYTHONPATH=src poetry run pytest src/Tests -q" bridge "$INTERNAL_APIS_TEST_IMAGE"
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
      "PYTHONPATH=. poetry run pytest tests -q" "$DEV_NETWORK" "$AUTH_SERVICE_TEST_IMAGE"
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
  ensure_python_test_image "$LATEST_PYTHON_IMAGE" || return 1
  [[ -f "$FRAMEWORK_SOURCE/requirements.txt" ]] || {
    echo "[supreme-test-framework] requirements.txt ausente" >&2
    return 1
  }

  echo "[supreme-test-framework] install de requirements + compile/import/Behave dry-run"
  docker run --rm --network bridge "${PROXY_ARGS[@]}" \
    "${PYTHON_CACHE_ARGS[@]}" "${PYTHON_CACHE_ENVS[@]}" \
    -v "$FRAMEWORK_SOURCE:/source:ro" \
    "$LATEST_PYTHON_IMAGE" sh -ec '
      mkdir -p /workspace
      tar -C /source \
        --exclude=.git --exclude=.worktrees --exclude=__pycache__ \
        --exclude=.pytest_cache --exclude=.venv --exclude=downloads \
        --exclude="*.env" -cf /tmp/source.tar .
      tar -xf /tmp/source.tar -C /workspace
      cd /workspace
      python -m pip install --disable-pip-version-check -r requirements.txt
      python -m unittest discover -s tests -v
      python -m compileall -q features page_objects utils
      python -c "from utils.browser_setup import setup_webdriver; assert callable(setup_webdriver)"
      behave --dry-run --no-color
    '
}

run_framework_e2e() (
  describe_source supreme-test-framework "$FRAMEWORK_SOURCE" || return 1
  ensure_python_test_image "$LATEST_PYTHON_IMAGE" || return 1
  [[ -f "$FRAMEWORK_SOURCE/requirements.txt" ]] || {
    echo "[supreme-test-framework] requirements.txt ausente" >&2
    return 1
  }
  if ! docker network inspect "$DEV_NETWORK" >/dev/null 2>&1; then
    echo "[supreme-test-framework] rede Docker ausente: $DEV_NETWORK (suba dev-local primeiro)" >&2
    return 1
  fi

  local chrome_name="labtech-e2e-chrome-$$"
  local web_name="labtech-e2e-web-$$"
  local web_alias="$web_name"
  local test_email="codex-e2e-$(date +%s)-$$@udf.edu.br"
  local cleanup_status=0
  cleanup_e2e() {
    local test_status=$?
    trap - EXIT
    docker rm -f "$chrome_name" "$web_name" >/dev/null 2>&1 || true
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

  echo "[supreme-test-framework] iniciando frontend e Chrome efêmeros na rede $DEV_NETWORK"
  trap cleanup_e2e EXIT
  docker compose run -d --no-deps --name "$web_name" \
    -e VITE_API_BASE_URL=http://api:5000 -e "E2E_HOST=$web_alias" reservas >/dev/null || return 1
  docker network disconnect "$DEV_NETWORK" "$web_name" || return 1
  docker network connect --alias "$web_alias" "$DEV_NETWORK" "$web_name" || return 1
  docker run -d --name "$chrome_name" --network "$DEV_NETWORK" \
    --network-alias "$chrome_name" --shm-size=1g \
    -e SE_NODE_MAX_SESSIONS=1 \
    -e VIDEO_READY_PORT=9100 \
    -e SE_START_VNC=false \
    -e SE_START_NO_VNC=false \
    -e SE_RECORD_VIDEO=false \
    -e SE_VIDEO_EVENT_DRIVEN=false \
    "$CHROME_IMAGE" >/dev/null || return 1
  trap cleanup_e2e EXIT

  echo "[supreme-test-framework] E2E na rede Docker por aliases de serviço; conta sintética isolada"
  docker run --rm --network "$DEV_NETWORK" "${PROXY_ARGS[@]}" \
    "${PYTHON_CACHE_ARGS[@]}" "${PYTHON_CACHE_ENVS[@]}" \
    -v "$FRAMEWORK_SOURCE:/source:ro" \
    -e SELENIUM_REMOTE_URL="http://$chrome_name:4444/wd/hub" \
    -e E2E_WEB_URL="http://$web_alias:3000/organizer" \
    -e BASE_URL="http://$web_alias:3000" \
    -e API_URL=http://api:5000 \
    -e ENV=production \
    -e TEST_EMAIL="$test_email" \
    -e NO_PROXY="$chrome_name,$web_alias,api,127.0.0.1,localhost" \
    -e no_proxy="$chrome_name,$web_alias,api,127.0.0.1,localhost" \
    "$LATEST_PYTHON_IMAGE" sh -ec '
      mkdir -p /workspace
      tar -C /source \
        --exclude=.git --exclude=.worktrees --exclude=__pycache__ \
        --exclude=.pytest_cache --exclude=.venv --exclude=downloads \
        --exclude="*.env" -cf /tmp/source.tar .
      tar -xf /tmp/source.tar -C /workspace
      cd /workspace
      sed -i "s/e2e-ci@udf.edu.br/$TEST_EMAIL/g" features/login.feature
      python -m pip install --disable-pip-version-check -r requirements.txt
      python -m compileall -q features page_objects utils tests
      python -m unittest discover -s tests -v
      python - <<"PY"
import json, os, time, urllib.request
targets = {
    "Selenium Grid": (os.environ["SELENIUM_REMOTE_URL"].removesuffix("/wd/hub") + "/wd/hub/status", lambda data: data.get("value", {}).get("ready")),
    "frontend": (os.environ["E2E_WEB_URL"], lambda response: response.status == 200),
}
for label, (url, ready) in targets.items():
    for _ in range(90):
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                data = json.load(response) if label == "Selenium Grid" else response
                if ready(data):
                    break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise SystemExit(f"{label} não ficou pronto na rede Docker: {url}")
PY
      behave --no-color -D "BASE_URL=$BASE_URL" -D "API_URL=$API_URL"
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
