#!/usr/bin/env bash
# Executa os gates dos quatro repos em Docker Linux; o Web roda no container
# da pilha integrada e os demais runners são descartáveis.
# Os diretórios padrão apontam para os heads locais dos PRs; cada um pode ser
# substituído por uma variável de ambiente para verificar outro checkout.
# As fontes Python/E2E vão para containers descartáveis; o Web usa o mount
# Compose e grava somente o build de produção ignorado pelo Git.
#
#   ./run-tests.sh                 # harness, API, catálogo, Auth, Web e framework
#   ./run-tests.sh harness|python|internal|auth|frontend|framework|e2e|advisories
#
# O alvo framework reproduz o workflow isolado (compile/import/Behave dry-run).
# O alvo e2e usa runner e Chrome descartáveis em Docker contra a pilha Compose.
set -uo pipefail
cd "$(dirname "$0")"
LAB=$(cd .. && pwd)

PYTHON_SOURCE="${PYTHON_SERVICES_DIR:-}"
INTERNAL_SOURCE="${INTERNAL_APIS_DIR:-}"
AUTH_SOURCE="${AUTH_SERVICE_DIR:-}"
FRAMEWORK_SOURCE="${E2E_FRAMEWORK_DIR:-$LAB/.worktrees/e2e-pr3-without-offers}"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-linux/amd64}"
# TEST_LIBC=musl troca o runner Python por Alpine (cache e tag próprios, pois
# virtualenvs com extensões nativas glibc não servem em musl).
TEST_LIBC="${TEST_LIBC:-glibc}"
case "$TEST_LIBC" in
  glibc) RUNNER_SUFFIX=""; RUNNER_DOCKERFILE_NAME="Dockerfile.test-python" ;;
  musl) RUNNER_SUFFIX="-musl"; RUNNER_DOCKERFILE_NAME="Dockerfile.test-python-musl" ;;
  *) echo "[runner] TEST_LIBC deve ser glibc ou musl" >&2; exit 2 ;;
esac
LATEST_PYTHON_IMAGE="labtech-dev-runner-python${RUNNER_SUFFIX}:3.14.8-${DOCKER_PLATFORM##*/}"
BASELINE_PYTHON_IMAGE="${BASELINE_PYTHON_TEST_IMAGE:-$LATEST_PYTHON_IMAGE}"
PYTHON_SERVICES_TEST_IMAGE="${PYTHON_SERVICES_TEST_IMAGE:-$BASELINE_PYTHON_IMAGE}"
INTERNAL_APIS_TEST_IMAGE="${INTERNAL_APIS_TEST_IMAGE:-$BASELINE_PYTHON_IMAGE}"
AUTH_SERVICE_TEST_IMAGE="${AUTH_SERVICE_TEST_IMAGE:-$LATEST_PYTHON_IMAGE}"
PYTHON_TEST_DOCKERFILE="$LAB/dev-local/dockerfiles/$RUNNER_DOCKERFILE_NAME"
CHROME_IMAGE="selenium/standalone-chrome:4.49.0-20260909@sha256:88dacdd42d93ab738bed045129376b2f965117c5f2e4710693e54695d531380d"
POETRY_VERSION="2.4.1"
DEV_NETWORK="${DEV_TEST_NETWORK:-labtech-dev_default}"
LATEST_PYTHON_IMAGE_READY=0
PLATFORM_CACHE_KEY="${DOCKER_PLATFORM//\//-}$RUNNER_SUFFIX"
TEST_CACHE_ROOT="${LABTECH_TEST_CACHE_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/labtech-dev-local-tests}/$PLATFORM_CACHE_KEY"
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

if [[ "$DOCKER_PLATFORM" != "linux/amd64" ]]; then
  echo "[runner] DOCKER_PLATFORM deve ser linux/amd64; imagens locais estão fixadas nesse alvo" >&2
  exit 2
fi

# Compose is the canonical selection for the three integrated Python services.
# The runner reads the resolved build contexts, then exports them back so any
# Compose command later in this script uses exactly the same source trees.
COMPOSE_CONFIG="$(docker compose config --format json)" || {
  echo "[runner] não foi possível resolver as fontes com docker compose config" >&2
  exit 1
}
compose_context() {
  python3 -c 'import json,sys; print(json.load(sys.stdin)["services"][sys.argv[1]]["build"]["context"])' "$1" <<<"$COMPOSE_CONFIG"
}
PYTHON_SOURCE="${PYTHON_SOURCE:-$(compose_context api)}"
INTERNAL_SOURCE="${INTERNAL_SOURCE:-$(compose_context internal)}"
AUTH_SOURCE="${AUTH_SOURCE:-$(compose_context auth)}"
export PYTHON_SERVICES_DIR="$PYTHON_SOURCE"
export INTERNAL_APIS_DIR="$INTERNAL_SOURCE"
export AUTH_SERVICE_DIR="$AUTH_SOURCE"
PROXY_ARGS=(
  -e "HTTP_PROXY=${DEV_TEST_PROXY:-}"
  -e "HTTPS_PROXY=${DEV_TEST_PROXY:-}"
  -e "http_proxy=${DEV_TEST_PROXY:-}"
  -e "https_proxy=${DEV_TEST_PROXY:-}"
)

status=0

run_harness_tests() {
  echo "[dev-local] unittest do harness em Docker Linux"
  ensure_python_test_image "$LATEST_PYTHON_IMAGE" || return 1
  docker run --platform "$DOCKER_PLATFORM" --rm --network none \
    -v "$LAB:/workspace/LABTECH:ro" \
    -w /workspace/LABTECH/dev-local \
    "$LATEST_PYTHON_IMAGE" \
    python -m unittest discover -s tests -v
}

ensure_python_test_image() {
  local image="$1"
  if [[ "$image" != "$LATEST_PYTHON_IMAGE" || "$LATEST_PYTHON_IMAGE_READY" -eq 1 ]]; then
    return 0
  fi
  docker build --quiet \
    --platform "$DOCKER_PLATFORM" \
    --tag "$LATEST_PYTHON_IMAGE" \
    --build-arg "POETRY_VERSION=$POETRY_VERSION" \
    --file "$PYTHON_TEST_DOCKERFILE" \
    "$(dirname "$PYTHON_TEST_DOCKERFILE")" >/dev/null || return 1
  local actual_platform
  actual_platform="$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")" || return 1
  if [[ "$actual_platform" != "$DOCKER_PLATFORM" ]]; then
    echo "[runner] imagem $image está em $actual_platform; esperado $DOCKER_PLATFORM" >&2
    return 1
  fi
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

  docker run --platform "$DOCKER_PLATFORM" --rm --network "$network" "${PROXY_ARGS[@]}" \
    "${PYTHON_CACHE_ARGS[@]}" "${PYTHON_CACHE_ENVS[@]}" \
    -v "$source:/source:ro" \
    -e TEST_COMMAND="$test_command" \
    -e MONGO_URI=mongodb://localhost:27017 \
    -e MONGO_DATABASE=labtech_test \
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
    docker run --platform "$DOCKER_PLATFORM" -d --rm --name "$redis_name" --network "$DEV_NETWORK" \
      redis:8.10.1@sha256:5edb5f1591cd35076057573171f40e0439ec7fbbb38e04d56c0efae810d99d47 \
      redis-server --save "" --appendonly no >/dev/null || exit 1

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

run_frontend() {
  echo "[interfaces-usuario/reservas] build SPA + testes na worktree montada"
  docker compose exec -T reservas sh -ec 'cd /app && yarn build && yarn test'
}

run_framework_checks() {
  describe_source supreme-test-framework "$FRAMEWORK_SOURCE" || return 1
  ensure_python_test_image "$LATEST_PYTHON_IMAGE" || return 1
  [[ -f "$FRAMEWORK_SOURCE/pyproject.toml" && -f "$FRAMEWORK_SOURCE/poetry.lock" ]] || {
    echo "[supreme-test-framework] pyproject.toml ou poetry.lock ausente" >&2
    return 1
  }

  echo "[supreme-test-framework] instalação congelada Poetry + compile/import/Behave dry-run"
  docker run --platform "$DOCKER_PLATFORM" --rm --network bridge "${PROXY_ARGS[@]}" \
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
      poetry install --no-interaction --no-ansi --no-root
      poetry run pip check
      if [ -d tests ]; then
        poetry run python -m unittest discover -s tests -v
      fi
      poetry run python -m compileall -q features page_objects utils
      poetry run python -c "from utils.browser_setup import setup_webdriver; assert callable(setup_webdriver)"
      poetry run behave --dry-run --no-color
    '
}

run_framework_e2e() (
  describe_source supreme-test-framework "$FRAMEWORK_SOURCE" || return 1
  ensure_python_test_image "$LATEST_PYTHON_IMAGE" || return 1
  [[ -f "$FRAMEWORK_SOURCE/pyproject.toml" && -f "$FRAMEWORK_SOURCE/poetry.lock" ]] || {
    echo "[supreme-test-framework] pyproject.toml ou poetry.lock ausente" >&2
    return 1
  }
  if ! docker network inspect "$DEV_NETWORK" >/dev/null 2>&1; then
    echo "[supreme-test-framework] rede Docker ausente: $DEV_NETWORK (suba dev-local primeiro)" >&2
    return 1
  fi

  local chrome_name="labtech-e2e-chrome-$$"
  local web_name="labtech-e2e-web-$$"
  # Alias fixo: é a origem que o CORS do compose aceita para o E2E.
  local web_alias="labtech-e2e-web"
  # Isolated synthetic account: checked for pre-existence and removed by
  # cleanup_e2e before/after the run.
  local test_email="${E2E_TEST_EMAIL:-e2e-ci@udf.edu.br}"
  if [[ ! "$test_email" =~ ^[A-Za-z0-9._+-]+@[A-Za-z0-9.-]+$ ]]; then
    echo "[supreme-test-framework] E2E_TEST_EMAIL deve ser um endereço simples" >&2
    return 1
  fi
  local cleanup_status=0
  cleanup_e2e() {
    local test_status=$?
    trap - EXIT
    docker rm -f "$chrome_name" "$web_name" >/dev/null 2>&1 || true
    docker compose exec -T mongo mongosh --quiet rooms-reservation-app --eval \
      "db.authentications.deleteMany({email: '$test_email'}).deletedCount" >/dev/null || cleanup_status=1
    local redis_keys key remaining_redis_keys attempt
    # O último pedido autenticado pode terminar no serviço Auth logo depois que
    # o navegador é encerrado. Revarrer algumas vezes também cobre essa escrita tardia.
    for attempt in 1 2 3 4 5; do
      redis_keys="$(docker compose exec -T redis redis-cli --scan --pattern "*$test_email*" 2>/dev/null)"
      [[ -n "$redis_keys" ]] || break
      while IFS= read -r key; do
        [[ -n "$key" ]] || continue
        docker compose exec -T redis redis-cli DEL "$key" >/dev/null || cleanup_status=1
      done <<< "$redis_keys"
      sleep 1
    done
    remaining_redis_keys="$(docker compose exec -T redis redis-cli --scan --pattern "*$test_email*" 2>/dev/null | wc -l | tr -d ' ')"
    if [[ "$remaining_redis_keys" != "0" ]]; then
      echo "[supreme-test-framework] $remaining_redis_keys chave(s) Redis sintética(s) permaneceram após limpeza" >&2
      cleanup_status=1
    fi
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
  if [[ "${E2E_WEB_MODE:-dev}" == "static" ]]; then
    # Build do Web na worktree montada (RESERVAS_WEB_DIR, ou a padrão do override) e servidor
    # estático: o dev server do Vite junto do Chrome não cabe na VM de 4 GB (timeout do renderer).
    local web_dir="${RESERVAS_WEB_DIR:-$PWD/../.worktrees/web-email-logo/reservas}"
    [[ "$web_dir" = /* ]] || web_dir="$PWD/$web_dir"
    echo "[supreme-test-framework] Web estático: build de $web_dir"
    docker compose run --rm --no-deps -e VITE_API_BASE_URL=http://api:5000 reservas \
      sh -ec 'cd /app && yarn install --frozen-lockfile --ignore-scripts && yarn build' >/dev/null || return 1
    docker run -d --name "$web_name" --platform "$DOCKER_PLATFORM" --network "$DEV_NETWORK" \
      --network-alias "$web_alias" \
      -v "$(cd "$web_dir" && pwd)/build/client:/site:ro" \
      -v "$PWD/serve-static.py:/serve-static.py:ro" \
      "$LATEST_PYTHON_IMAGE" python /serve-static.py /site 3000 >/dev/null || return 1
  else
    docker compose run -d --no-deps --name "$web_name" \
      -e VITE_API_BASE_URL=http://api:5000 -e "E2E_HOST=$web_alias" reservas >/dev/null || return 1
    docker network disconnect "$DEV_NETWORK" "$web_name" || return 1
    docker network connect --alias "$web_alias" "$DEV_NETWORK" "$web_name" || return 1
  fi
  docker run --platform "$DOCKER_PLATFORM" -d --name "$chrome_name" --network "$DEV_NETWORK" \
    --network-alias "$chrome_name" --shm-size=1g \
    -e SE_NODE_MAX_SESSIONS=1 \
    -e VIDEO_READY_PORT=9100 \
    -e SE_START_VNC=false \
    -e SE_START_NO_VNC=false \
    -e SE_RECORD_VIDEO=false \
    -e SE_VIDEO_EVENT_DRIVEN=false \
    "$CHROME_IMAGE" >/dev/null || return 1
  trap cleanup_e2e EXIT

  # Modo resiliência (opt-in, padrão desligado): os cenários @drafts que param a API/o Auth precisam do socket
  # do Docker, montado só aqui e só com E2E_ALLOW_SERVICE_CONTROL=1. O framework só pode parar api e auth do
  # projeto Compose informado (padrão: o da rede $DEV_NETWORK) e religa o que parou ao fim de cada cenário.
  local resilience_args=()
  if [[ "${E2E_ALLOW_SERVICE_CONTROL:-}" == "1" ]]; then
    local compose_project="${E2E_COMPOSE_PROJECT:-$(docker network inspect "$DEV_NETWORK" \
      --format '{{index .Labels "com.docker.compose.project"}}' 2>/dev/null)}"
    [[ -n "$compose_project" ]] || {
      echo "[supreme-test-framework] E2E_COMPOSE_PROJECT não definido e não deduzido da rede $DEV_NETWORK" >&2
      return 1
    }
    echo "[supreme-test-framework] controle de serviços ligado: o runner recebe o socket do Docker (projeto $compose_project)"
    resilience_args+=(-v /var/run/docker.sock:/var/run/docker.sock
      -e E2E_ALLOW_SERVICE_CONTROL=1 -e "E2E_COMPOSE_PROJECT=$compose_project")
  fi
  # navigator.locks só existe em contexto seguro; em HTTP na rede Docker o Chrome precisa tratar a origem do Web
  # como segura (Production é HTTPS). Passe a origem, ex.: E2E_TREAT_ORIGIN_AS_SECURE=http://labtech-e2e-web:3000.
  [[ -z "${E2E_TREAT_ORIGIN_AS_SECURE:-}" ]] || resilience_args+=(-e "E2E_TREAT_ORIGIN_AS_SECURE=$E2E_TREAT_ORIGIN_AS_SECURE")

  echo "[supreme-test-framework] E2E na rede Docker por aliases de serviço; conta sintética isolada"
  docker run --platform "$DOCKER_PLATFORM" --rm --network "$DEV_NETWORK" "${PROXY_ARGS[@]}" ${resilience_args[@]+"${resilience_args[@]}"} \
    "${PYTHON_CACHE_ARGS[@]}" "${PYTHON_CACHE_ENVS[@]}" \
    -v "$FRAMEWORK_SOURCE:/source:ro" \
    -e SELENIUM_REMOTE_URL="http://$chrome_name:4444/wd/hub" \
    -e E2E_WEB_URL="http://$web_alias:3000/organizer" \
    -e BASE_URL="http://$web_alias:3000" \
    -e API_URL=http://api:5000 \
    -e ENV=production \
    -e TEST_EMAIL="$test_email" \
    -e E2E_BEHAVE_ARGS="${E2E_BEHAVE_ARGS:-}" \
    -e E2E_MONGO_URI="${E2E_MONGO_URI:-mongodb://mongo:27017}" \
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
      poetry install --no-interaction --no-ansi --no-root
      poetry run pip check
      poetry run python -m compileall -q features page_objects utils
      if [ -d tests ]; then
        poetry run python -m compileall -q tests
        poetry run python -m unittest discover -s tests -v
      fi
      poetry run python - <<"PY"
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
      # E2E_BEHAVE_ARGS (vazio por padrão = comportamento inalterado) repassa argumentos ao behave,
      # por exemplo --tags=drafts; é intencionalmente separado em palavras.
      # shellcheck disable=SC2086
      poetry run behave --no-color -D "BASE_URL=$BASE_URL" -D "API_URL=$API_URL" $E2E_BEHAVE_ARGS
    '
)

run_advisories() {
  echo "[dev-local] OSV nas locks das lanes em Docker Linux"
  ensure_python_test_image "$LATEST_PYTHON_IMAGE" || return 1
  docker run --platform "$DOCKER_PLATFORM" --rm --network bridge "${PROXY_ARGS[@]}" \
    -v "$LAB:/workspace/LABTECH:ro" \
    -w /workspace/LABTECH/dev-local \
    "$LATEST_PYTHON_IMAGE" \
    sh -ec 'python check-advisories.py --self-test && python check-advisories.py'
}

run_alocacao() {
  echo "[teachers-allocation] build + pytest (fora do alvo padrão desta etapa)"
  docker build --platform "$DOCKER_PLATFORM" -q -t labtech-alocacao-tests "$LAB/teachers-allocation/backend" >/dev/null || return 1
  docker run --platform "$DOCKER_PLATFORM" --rm labtech-alocacao-tests \
    sh -c "pip install -q --root-user-action=ignore -r requirements-dev.txt && pytest -v"
}

case "${1:-all}" in
  harness)   run_harness_tests || status=1 ;;
  python)    run_python_services || status=1 ;;
  internal)  run_internal_apis || status=1 ;;
  auth)      run_auth_service || status=1 ;;
  frontend)  run_frontend || status=1 ;;
  framework) run_framework_checks || status=1 ;;
  e2e)       run_framework_e2e || status=1 ;;
  advisories) run_advisories || status=1 ;;
  alocacao)  run_alocacao || status=1 ;;
  all)
    run_harness_tests || status=1
    echo
    run_python_services || status=1
    echo
    run_internal_apis || status=1
    echo
    run_auth_service || status=1
    echo
    run_frontend || status=1
    echo
    run_framework_checks || status=1
    ;;
  *)
    echo "uso: $0 [harness|python|internal|auth|frontend|framework|e2e|advisories|alocacao|all]" >&2
    exit 2
    ;;
esac

if [[ "$status" -eq 0 ]]; then
  echo "=== RUN-TESTS: PASS ==="
else
  echo "=== RUN-TESTS: FAIL ==="
fi
exit "$status"
