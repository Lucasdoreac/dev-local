#!/usr/bin/env bash
# Chamado em segundo plano pelo hook pre-push (instalado por install-hooks.sh).
# Espera o GitHub ter o commit enviado e então sincroniza SÓ a lane daquela
# branch no caderno Darlas 2022 (lanes.json). Branch que não é lane, ou push
# que falhou, não sincroniza. Nunca atrasa o push.
#   notebook-sync-after-push.sh <repo> <branch local> <branch remota> <sha> [remoto]
set -u
cd "$(dirname "$0")"
repo=$1; local_branch=$2; remote_branch=$3; sha=$4; push_remote=${5:-origin}
mkdir -p logs
exec >> logs/notebook-sync.log 2>&1
echo "=== $(date '+%F %T') push de $repo: $local_branch -> $push_remote/$remote_branch ${sha:0:7}"

if ! python3 -c 'import json,sys; sys.exit(not any(l["repo"] == sys.argv[1] and l["fork_branch"] == sys.argv[2] and l.get("notebook", True) for l in json.load(open("lanes.json"))["lanes"]))' "$repo" "$remote_branch"; then
  echo "não é branch de lane do caderno: caderno não muda"
  exit 0
fi

remote=""
for _ in $(seq 1 "${WAIT_TRIES:-36}"); do   # até 3 min
  remote=$(git -C "../$repo" ls-remote "$push_remote" "refs/heads/$remote_branch" | cut -f1)
  [ "$remote" = "$sha" ] && break
  sleep "${WAIT_SECONDS:-5}"
done
if [ "$remote" != "$sha" ]; then
  echo "o GitHub não tem ${sha:0:7} em $push_remote/$remote_branch (push falhou ou demorou): nada sincronizado"
  exit 0
fi

if ./notebook-sync.py --push "$repo" "$remote_branch" "$sha" --prune ${NOTEBOOK_SYNC_ARGS:-}; then
  echo "ok"
else
  echo "FALHOU (código $?)"
  osascript -e "display notification \"Sync do caderno falhou para $repo. Veja dev-local/logs/notebook-sync.log (sessão expirada? rode nlm login).\" with title \"notebook-sync\"" 2>/dev/null
fi
