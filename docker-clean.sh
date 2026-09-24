#!/usr/bin/env bash
# Higiene do Docker no Colima (ver ~/LABTECH/CLAUDE.md).
#
# O disco da VM do Colima só cresce: apagar imagem/container não devolve o
# espaço ao macOS. Sem o `fstrim` no fim, "limpar" não libera nada no Mac.
#
#   ./docker-clean.sh          # limpeza segura (padrão)
#   ./docker-clean.sh --deep --yes   # + imagens não usadas há 72h (de QUALQUER projeto)
#   ./docker-clean.sh --force  # ignora a checagem de outra sessão ativa
#
# NUNCA apaga volumes (têm dados do Mongo/MinIO): só lista os órfãos.
set -uo pipefail
PROJECT=labtech-dev
DEEP=""; YES=""; FORCE=""
for a in "$@"; do
  case "$a" in
    --deep) DEEP=1 ;; --yes) YES=1 ;; --force) FORCE=1 ;;
    *) echo "uso: $0 [--deep --yes] [--force]" >&2; exit 2 ;;
  esac
done

# Duas sessões mexendo no mesmo compose se atropelam (containers somem no
# meio de um smoke). Não limpa enquanto houver up/down/smoke em andamento.
if [ -z "$FORCE" ] && ps aux | grep -E "smoke\.sh|docker compose (up|down)|run-tests\.sh" | grep -v grep | grep -v "docker-clean" >/dev/null; then
  echo "Há smoke/compose/run-tests em andamento (outra sessão?). Aguarde ou use --force." >&2
  exit 1
fi

free_gb() { df -g /System/Volumes/Data | awk 'NR==2 {print $4}'; }
echo "Livre no Mac antes: $(free_gb) GB"

# 1. containers parados DESTE projeto (não toca nos de outros projetos)
docker container prune -f --filter "label=com.docker.compose.project=$PROJECT" >/dev/null
# 2. imagens penduradas e tags de rascunho (:test, :lockcheck) sem container
docker image prune -f >/dev/null
for tag in $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E ':(test|lockcheck)$'); do
  docker rmi "$tag" >/dev/null 2>&1 && echo "removida tag de rascunho: $tag"
done
# 3. cache de build com mais de 24h
docker builder prune -f --filter until=24h >/dev/null

# 4. opcional: imagens paradas há mais de 72h, de qualquer projeto
if [ -n "$DEEP" ]; then
  if [ -z "$YES" ]; then echo "--deep apaga imagens de outros projetos; repita com --yes" >&2; exit 2; fi
  docker image prune -a -f --filter "until=72h" >/dev/null
fi

# 5. volumes: só lista (têm dados). Apagar exige aprovação explícita.
# "dangling" = nenhum container usa AGORA. Com o stack parado, os volumes do próprio
# projeto (labtech-dev_*: Mongo, Postgres, MinIO...) também aparecem assim, mas têm
# dados e NÃO são órfãos: só conta o que não é do projeto.
orphans=$(docker volume ls -qf dangling=true | grep -v "^${PROJECT}_" | wc -l | tr -d ' ')
echo "Volumes órfãos de outros projetos (NÃO apagados): $orphans"
echo "Volumes do projeto (dados; mantidos): $(docker volume ls -q | grep -c "^${PROJECT}_")"

# 6. devolve o espaço ao macOS; sem isto nada acima libera disco no Mac
colima ssh -- sudo fstrim -av 2>&1 | grep -E "trimmed" | head -3

echo "Livre no Mac depois: $(free_gb) GB"
docker system df
