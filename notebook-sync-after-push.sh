#!/usr/bin/env bash
# Chamado em segundo plano pelo hook pre-push (instalado por install-hooks.sh).
# Espera o GitHub ter o commit enviado e então sincroniza SÓ aquele repo no
# caderno Darlas 2022. Se o push falhar, não sincroniza. Nunca atrasa o push.
#   notebook-sync-after-push.sh <repo> <branch local> <branch remota> <sha>
set -u
cd "$(dirname "$0")"
repo=$1; local_branch=$2; remote_branch=$3; sha=$4
mkdir -p logs
exec >> logs/notebook-sync.log 2>&1
echo "=== $(date '+%F %T') push de $repo: $local_branch -> origin/$remote_branch ${sha:0:7}"

remote=""
for _ in $(seq 1 "${WAIT_TRIES:-36}"); do   # até 3 min
  remote=$(git -C "../$repo" ls-remote origin "refs/heads/$remote_branch" | cut -f1)
  [ "$remote" = "$sha" ] && break
  sleep "${WAIT_SECONDS:-5}"
done
if [ "$remote" != "$sha" ]; then
  echo "o GitHub não tem ${sha:0:7} em $remote_branch (push falhou ou demorou): nada sincronizado"
  exit 0
fi

if ./notebook-sync.py --only "$repo" --ref "$repo=$remote_branch" --commit "$repo=$sha" --prune ${NOTEBOOK_SYNC_ARGS:-}; then
  echo "ok"
else
  echo "FALHOU (código $?)"
  osascript -e "display notification \"Sync do caderno falhou para $repo. Veja dev-local/logs/notebook-sync.log (sessão expirada? rode nlm login).\" with title \"notebook-sync\"" 2>/dev/null
fi
