#!/usr/bin/env bash
# Instala o hook pre-push em todos os repos de REPOS do notebook-sync.py: a cada push para o GitHub, o
# código daquele repo é sincronizado com o caderno Darlas 2022 (em segundo
# plano, depois que o push chega). Hooks não são versionados pelo git, por
# isso ficam aqui. Não sobrescreve hook que não seja deste script.
#   ./install-hooks.sh
set -eu
DEV=$(cd "$(dirname "$0")" && pwd)
for repo in $(python3 -c 'import importlib.util as u;s=u.spec_from_file_location("n","'"$DEV"'/notebook-sync.py");m=u.module_from_spec(s);s.loader.exec_module(m);print(" ".join(m.REPOS))'); do
  hook="$DEV/../$repo/.git/hooks/pre-push"
  if [ -e "$hook" ] && ! grep -q "notebook-sync-after-push" "$hook"; then
    echo "$repo: já existe um pre-push que não é deste script; não mexi"; continue
  fi
  cat > "$hook" <<HOOK
#!/usr/bin/env bash
# Instalado por dev-local/install-hooks.sh: depois do push, sincroniza o código
# deste repo com o caderno Darlas 2022. Nunca bloqueia nem atrasa o push.
repo=\$(basename "\$(git rev-parse --show-toplevel)")
zero=0000000000000000000000000000000000000000
while read -r local_ref local_sha remote_ref remote_sha; do
  [ "\$local_sha" = "\$zero" ] && continue          # apagando branch remota
  case "\$local_ref" in refs/heads/*) ;; *) continue ;; esac
  case "\$remote_ref" in refs/heads/*) ;; *) continue ;; esac
  nohup "$DEV/notebook-sync-after-push.sh" "\$repo" "\${local_ref#refs/heads/}" "\${remote_ref#refs/heads/}" "\$local_sha" >/dev/null 2>&1 &
done
exit 0
HOOK
  chmod +x "$hook"
  echo "$repo: pre-push instalado"
done
