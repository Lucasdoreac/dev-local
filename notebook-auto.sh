#!/usr/bin/env bash
# Rodado pelo launchd a cada 3 h (instalar: ./notebook-auto.sh --install).
# Mantém caderno e site público em dia sem depender de ninguém lembrar:
#   1. reports/prs/gerar.py          fila, textos dos PRs, fila.json e pendencias.json
#   2. publica estagio-publico/data   commit + push só de data/ (dados gerados, sem nomes);
#                                     o push dispara a Action que atualiza o quadro
#   (abrir-proximos.py, que abria o próximo PR da fila antiga, foi aposentado:
#    a fila de reports/prs é anterior aos PRs atuais e não deve ser publicada)
#   4. notebook-sync.py --prune      código das branches de trabalho (só sobe o que mudou)
#   5. notebook-estado.py --prune    fonte "estado e fila" gerada dos dados
#   6. run-tests.sh advisories       OSV nas locks das lanes (Docker); achado = notificação
# Falha = notificação do macOS + dev-local/logs/notebook-auto.log. Nada aqui
# toca no caderno do Estágio (público). Push automático de data/ autorizado pelo
# dono em 25/09/2026.
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
echo "=== $(date '+%Y-%m-%dT%H:%M:%S%z') pid=$$ ==="
falhou=""
alertas=""
LAST_STEP_DETAIL=""
run_logged_step() {
  local label="$1" started ended status output
  shift
  started=$(date +%s)
  echo "ETAPA início: $label em $(date '+%Y-%m-%dT%H:%M:%S%z')"
  output=$("$@" 2>&1)
  status=$?
  if [ -n "$output" ]; then printf '%s\n' "$output"; fi
  ended=$(date +%s)
  echo "ETAPA fim: $label status=$status duração=$((ended - started))s em $(date '+%Y-%m-%dT%H:%M:%S%z')"
  LAST_STEP_DETAIL=""
  if [ "$status" -ne 0 ]; then
    LAST_STEP_DETAIL=$(printf '%s\n' "$output" | grep -E '^(ABORTADO:|GitHub:|=== CHECK ADVISORIES: ERRO|FALHOU:)' | tail -n 1)
    if [ -z "$LAST_STEP_DETAIL" ]; then LAST_STEP_DETAIL=$(printf '%s\n' "$output" | tail -n 1); fi
    LAST_STEP_DETAIL=$(printf '%s' "$LAST_STEP_DETAIL" | tr '\n' ' ' | cut -c 1-220)
  fi
  return "$status"
}
record_failure() {
  local name="$1"
  falhou="${falhou:+$falhou e }$name"
  if [ -n "$LAST_STEP_DETAIL" ]; then
    alertas="${alertas:+$alertas; }$LAST_STEP_DETAIL"
  fi
}
run_logged_step "fila de PRs" python3 ../reports/prs/gerar.py || record_failure "fila"
SITE=../estagio-publico
if [ -z "$falhou" ] && [ -n "$(git -C "$SITE" status --porcelain -- data)" ]; then
  # Dados públicos: nada de e-mail, @conta ou nome do dono antes de publicar.
  if git -C "$SITE" diff -- data | grep '^+' | grep -qiE '[a-z0-9._-]+@[a-z0-9.-]+\.[a-z]|(^|[^a-z0-9])@[a-z0-9-]{2,}|lucas|darlas'; then
    falhou="site (dado com possível identificação; não publicado)"
  elif git -C "$SITE" add data \
      && git -C "$SITE" commit -q -m "dados: fila e pendências atualizadas automaticamente" \
      && git -C "$SITE" pull -q --rebase origin main \
      && git -C "$SITE" push -q origin main; then
    echo "site: data/ publicado"
  else
    falhou="site"
  fi
fi
run_logged_step "sincronização do caderno" ./notebook-sync.py --prune || record_failure "código"
run_logged_step "estado e fila" ./notebook-estado.py --prune || record_failure "estado"
# Advisory em dependência travada das lanes. Sem Docker (Colima parado) só registra.
if docker info >/dev/null 2>&1; then
  adv_started=$(date +%s)
  echo "ETAPA início: checagem de advisories (runner Docker linux/amd64) em $(date '+%Y-%m-%dT%H:%M:%S%z')"
  adv=$(./run-tests.sh advisories 2>&1)
  adv_status=$?
  printf '%s\n' "$adv"
  echo "ETAPA fim: checagem de advisories status=$adv_status duração=$(($(date +%s) - adv_started))s em $(date '+%Y-%m-%dT%H:%M:%S%z')"
  if echo "$adv" | grep -q "CHECK ADVISORIES: FAIL ("; then
    falhou="${falhou:+$falhou e }advisory em $(echo "$adv" | grep -c '✗') dependência(s) das lanes"
    LAST_STEP_DETAIL=$(printf '%s\n' "$adv" | grep '^   ✗' | head -n 1 | cut -c 1-220)
    [ -n "$LAST_STEP_DETAIL" ] && alertas="${alertas:+$alertas; }$LAST_STEP_DETAIL"
  elif ! echo "$adv" | grep -q "CHECK ADVISORIES: PASS ==="; then
    falhou="${falhou:+$falhou e }checagem de advisories"
    LAST_STEP_DETAIL=$(printf '%s\n' "$adv" | grep -E '^=== CHECK ADVISORIES: ERRO|^ERROR|^Error|^Traceback' | tail -n 1 | cut -c 1-220)
    [ -n "$LAST_STEP_DETAIL" ] && alertas="${alertas:+$alertas; }$LAST_STEP_DETAIL"
  fi
else
  echo "ETAPA pulada: advisories; Docker indisponível (nenhuma consulta foi executada)"
fi
if [ -n "$falhou" ]; then
  echo "FALHOU: $falhou${alertas:+ — $alertas}"
  notification="Precisa de atenção: $falhou${alertas:+ — $alertas}. Detalhes em dev-local/logs/notebook-auto.log."
  alert_state=logs/notebook-auto-alert.state
  fingerprint=$(printf '%s' "$falhou|$alertas" | shasum -a 256 | awk '{print $1}')
  now=$(date +%s)
  previous_fingerprint=""
  previous_time=0
  if [ -r "$alert_state" ]; then read -r previous_fingerprint previous_time < "$alert_state"; fi
  alert_age=-1
  if [[ "$previous_time" =~ ^[0-9]+$ ]]; then alert_age=$((now - previous_time)); fi
  if [ "$fingerprint" = "$previous_fingerprint" ] \
      && [ "$alert_age" -ge 0 ] \
      && [ "$alert_age" -lt 86400 ]; then
    echo "NOTIFICAÇÃO suprimida: mesma falha já avisada há ${alert_age}s; repetição após 24 h."
  else
    if osascript -e 'on run argv' -e 'display notification (item 1 of argv) with title "LabTech automação"' -e 'end run' "$notification" 2>/dev/null; then
      printf '%s %s\n' "$fingerprint" "$now" > "$alert_state.tmp.$$" \
        && mv "$alert_state.tmp.$$" "$alert_state"
      echo "NOTIFICAÇÃO enviada: nova falha ou lembrete diário."
    else
      echo "NOTIFICAÇÃO indisponível: osascript não conseguiu entregar o alerta."
    fi
  fi
  exit 1
fi
rm -f logs/notebook-auto-alert.state
echo "EXECUÇÃO OK"
