#!/usr/bin/env bash
# Rodado pelo launchd a cada 3 h (instalar: ./notebook-auto.sh --install).
# Mantém caderno e site público em dia sem depender de ninguém lembrar:
#   1. reports/prs/gerar.py          fila, textos dos PRs, fila.json e pendencias.json
#   2. publica estagio-publico/data   commit + push só de data/ (dados gerados, sem nomes);
#                                     o push dispara a Action que atualiza o quadro
#   3. abrir-proximos.py             abre o próximo PR de cada repo quando o anterior recebe merge
#   4. notebook-sync.py --prune      código das branches de trabalho (só sobe o que mudou)
#   5. notebook-estado.py --prune    fonte "estado e fila" gerada dos dados
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
echo "=== $(date '+%F %T')"
falhou=""
python3 ../reports/prs/gerar.py || falhou="fila"
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
# Próximo PR de cada repositório abre sozinho quando o anterior recebe merge.
abertos=$(./abrir-proximos.py 2>&1); rc=$?
echo "$abertos"
novos=$(echo "$abertos" | sed -n 's/^\([a-z-]*\): abre \([A-Z]*-[0-9]*\).*/\2/p' | xargs)
if [ -n "$novos" ]; then
  gh workflow run sync-quadro.yml --repo Lucasdoreac/estagio-publico >/dev/null 2>&1
  osascript -e "display notification \"PR aberto automaticamente: $novos\" with title \"LabTech fila\"" 2>/dev/null
fi
[ $rc -eq 0 ] || falhou="${falhou:+$falhou e }fila de PRs ($(echo "$abertos" | grep -E 'ATENÇÃO|falhou' | head -1))"
./notebook-sync.py --prune || falhou="${falhou:+$falhou e }código"
./notebook-estado.py --prune || falhou="${falhou:+$falhou e }estado"
if [ -n "$falhou" ]; then
  echo "FALHOU: $falhou"
  osascript -e "display notification \"Precisa de atenção: $falhou. Detalhes em dev-local/logs/notebook-auto.log.\" with title \"LabTech automação\"" 2>/dev/null
  exit 1
fi
echo "ok"
