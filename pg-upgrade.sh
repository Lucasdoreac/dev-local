#!/usr/bin/env bash
# Migra os dados de um Postgres do dev-local para a versão nova com pg_dump/pg_restore
# e confere a contagem de linhas tabela a tabela. O volume antigo NÃO é apagado.
# Pré-requisito: o compose.yaml já aponta o serviço para a imagem e o volume novos.
#   ./pg-upgrade.sh <serviço> <imagem antiga> <volume antigo> <usuário> <banco> [perfil]
#   ex.: ./pg-upgrade.sh alocacao-db postgres:17 labtech-dev_alocacao_pgdata17 user resource_allocation
set -euo pipefail
cd "$(dirname "$0")"
svc=$1; old_image=$2; old_vol=$3; user=$4; db=$5; profile=${6:-}
prof=(); [ -n "$profile" ] && prof=(--profile "$profile")
work=$(mktemp -d); trap 'docker rm -f pgup-old >/dev/null 2>&1; rm -rf "$work"' EXIT

counts() {  # contagem exata por tabela, ordenada
  "$@" psql -U "$user" -d "$db" -tAc "select table_schema||'.'||table_name from information_schema.tables where table_type='BASE TABLE' and table_schema not in ('pg_catalog','information_schema') order by 1" |
  while read -r t; do  # < /dev/null: `docker compose exec` lê o stdin e comeria a lista de tabelas
    printf '%s %s\n' "$t" "$("$@" psql -U "$user" -d "$db" -tAc "select count(*) from $t" < /dev/null)"
  done
}

echo "[1/4] dump do volume antigo ($old_vol) com $old_image"
docker run -d --name pgup-old -v "$old_vol":/var/lib/postgresql/data -e POSTGRES_PASSWORD=x "$old_image" >/dev/null
for _ in $(seq 1 60); do docker exec pgup-old pg_isready -U "$user" -d "$db" >/dev/null 2>&1 && break; sleep 2; done
docker exec pgup-old pg_dump -U "$user" -d "$db" -Fc > "$work/dump"
counts docker exec pgup-old > "$work/antes"
docker rm -f pgup-old >/dev/null

echo "[2/4] sobe $svc na versão nova (volume novo)"
docker compose ${prof[@]+"${prof[@]}"} up -d --no-deps "$svc" >/dev/null
# pg_isready já responde durante a inicialização (servidor temporário, só socket,
# banco ainda não criado): espera uma conexão TCP de verdade ao banco.
ready=""
for _ in $(seq 1 90); do
  docker compose ${prof[@]+"${prof[@]}"} exec -T "$svc" psql -h 127.0.0.1 -U "$user" -d "$db" -tAc "select 1" >/dev/null 2>&1 && { ready=1; break; }
  sleep 2
done
[ -n "$ready" ] || { echo "$svc não ficou pronto"; exit 1; }
docker compose ${prof[@]+"${prof[@]}"} exec -T "$svc" psql -U "$user" -d "$db" -tAc "show server_version"

echo "[3/4] restore"
if ! docker compose ${prof[@]+"${prof[@]}"} exec -T "$svc" pg_restore -U "$user" -d "$db" --no-owner --clean --if-exists < "$work/dump"; then
  echo "=== PG UPGRADE $svc: FAIL (pg_restore) ==="; exit 1
fi

echo "[4/4] linhas por tabela, antes x depois"
counts docker compose ${prof[@]+"${prof[@]}"} exec -T "$svc" > "$work/depois"
if diff "$work/antes" "$work/depois" >/dev/null; then
  echo "iguais: $(wc -l < "$work/antes" | tr -d ' ') tabelas, $(awk '{s+=$2} END {print s}' "$work/antes") linhas"
  echo "=== PG UPGRADE $svc: PASS ==="
else
  diff "$work/antes" "$work/depois" || true
  echo "=== PG UPGRADE $svc: FAIL ==="; exit 1
fi
