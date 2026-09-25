#!/usr/bin/env bash
# Rodado pelo launchd a cada 3 h (instalar: ./notebook-auto.sh --install).
# Mantém o caderno Darlas 2022 em dia sem depender de push:
#   1. notebook-sync.py --prune   código das branches de trabalho (só sobe o que mudou)
#   2. notebook-estado.py --prune fonte "estado e fila" gerada dos dados
# Falha = notificação do macOS + dev-local/logs/notebook-auto.log. Nada aqui
# toca no caderno do Estágio (público).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
LABEL=br.labtech.notebook-auto
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [ "${1:-}" = "--install" ]; then
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>$HERE/notebook-auto.sh</string></array>
  <key>StartInterval</key><integer>10800</integer>
  <key>RunAtLoad</key><false/>
</dict></plist>
PL
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null
  launchctl bootstrap "gui/$(id -u)" "$PLIST" && echo "instalado: a cada 3 h ($PLIST)"
  exit $?
fi
if [ "${1:-}" = "--uninstall" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null; rm -f "$PLIST"; echo "removido"; exit 0
fi

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
cd "$HERE"
mkdir -p logs
exec >> logs/notebook-auto.log 2>&1
echo "=== $(date '+%F %T')"
falhou=""
./notebook-sync.py --prune || falhou="código"
./notebook-estado.py --prune || falhou="${falhou:+$falhou e }estado"
if [ -n "$falhou" ]; then
  echo "FALHOU: $falhou"
  osascript -e "display notification \"Atualização do caderno falhou ($falhou). Veja dev-local/logs/notebook-auto.log (sessão expirada? rode nlm login).\" with title \"LabTech caderno\"" 2>/dev/null
  exit 1
fi
echo "ok"
