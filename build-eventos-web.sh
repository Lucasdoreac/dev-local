#!/usr/bin/env bash
# Constrói a imagem do eventos-angular a partir do CONTEÚDO DO GIT, não da pasta.
#
# O repo tem src/app/shared/Utils/ E src/app/shared/utils/ (imports em minúsculas).
# No macOS (disco sem diferenciar maiúsculas) as duas pastas viram uma só, e o
# build em Linux não acha ./shared/utils/theme.service. `git archive` preserva as
# duas como estão no Git. Nada é alterado no repo (arquivado).
#
# O build de produção do Angular precisa de memória: com o stack todo ligado a VM
# de 4 GB mata o esbuild (exit 137). Pare os frontends antes:
#   docker compose stop reservas alocacao-web && ./build-eventos-web.sh
#   docker compose start reservas alocacao-web
set -euo pipefail
cd "$(dirname "$0")/../_outros/eventos-angular"
git archive HEAD | docker build -t labtech-dev-eventos-web -
