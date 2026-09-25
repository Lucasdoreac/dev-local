#!/usr/bin/env bash
# Abre UM PR da fila (reports/prs/FILA.md) a partir do fork do dono.
# Quem roda é o dono: faz push para o fork e abre PR na org (visível para quem revisa).
#   ./abrir-pr.sh PS-1
# Passos: confere a suíte medida na ponta (reports/prs/verificacao.txt), cria o fork
# se faltar, empurra pr/<ID> para o fork e abre o PR com o texto de reports/prs/<ID>.md.
set -euo pipefail
ID=${1:?uso: $0 <ID da fila, ex.: PS-1>}
LAB=$(cd "$(dirname "$0")/.." && pwd)
PRS="$LAB/reports/prs"
ORG=LabTechUDF
ME=$(gh api user -q .login)

case "$ID" in
  SR-*) REPO=shared-resources ;; PS-*) REPO=python-services ;;
  IU-*) REPO=interfaces-usuario ;; TA-*) REPO=teachers-allocation ;;
  ST-*) REPO=supreme-test-framework ;;
  *) echo "ID desconhecido: $ID"; exit 2 ;;
esac
LINE=$(grep -E "^\| [0-9]+ \| $ID " "$PRS/FILA.md") || { echo "$ID não está na FILA.md (rode reports/prs/gerar.py)"; exit 2; }
TITLE=$(echo "$LINE" | awk -F'|' '{print $3}' | sed -E "s/^ *$ID //; s/ *$//")
DEPS=$(echo "$LINE" | awk -F'|' '{print $8}' | xargs)
BODY="$PRS/$ID.md"

VERIF=$(grep "^$ID " "$PRS/verificacao.txt" 2>/dev/null || true)
case "$ID" in TA-*|ST-*) ;; *)  # sem suíte em container limpo (ST: precisa da pilha no ar)
  [ -n "$VERIF" ] || { echo "Suíte da ponta ainda não medida: rode reports/prs/verificar.sh $ID"; exit 3; }
  echo "$VERIF" | grep -q FAIL && { echo "Suíte FALHANDO na ponta: $VERIF"; exit 3; } ;;
esac
git -C "$LAB/$REPO" rev-parse -q --verify "pr/$ID" >/dev/null || { echo "branch pr/$ID não existe"; exit 2; }

BASE=$(gh repo view "$ORG/$REPO" --json defaultBranchRef -q .defaultBranchRef.name)
echo "PR:       $ID  $TITLE"
echo "Repo:     $ORG/$REPO ($BASE) <- $ME/$REPO:pr/$ID"
echo "Depende:  $DEPS   (abra na ordem; o diff inclui os PRs anteriores ainda não aceitos)"
echo "Suíte:    ${VERIF:-sem suíte}"
read -r -p "Fazer push para o fork e abrir o PR? [s/N] " ok
[ "$ok" = s ] || { echo "nada feito"; exit 0; }

gh repo view "$ME/$REPO" >/dev/null 2>&1 || gh repo fork "$ORG/$REPO" --clone=false
git -C "$LAB/$REPO" remote get-url fork >/dev/null 2>&1 || git -C "$LAB/$REPO" remote add fork "https://github.com/$ME/$REPO.git"
git -C "$LAB/$REPO" push fork "pr/$ID:pr/$ID"
gh pr create --repo "$ORG/$REPO" --base "$BASE" --head "$ME:pr/$ID" --title "$TITLE" --body-file "$BODY"
