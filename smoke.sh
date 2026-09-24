#!/usr/bin/env bash
# Smoke test do ambiente local (compose labtech-dev): prova, do zero, que o
# produto funciona ponta a ponta e imprime UMA linha de veredito.
#
#   1. serviços respondem (frontend, APIs, MinIO);
#   2. catálogo real carregado (contagens pela internal_apis);
#   3. reserva sintética pela tela até "Evento Enviado com Sucesso!";
#   4. aprovação: Coordenação → Reitoria → approved_by_reitoria.
#
# Evidências (prints) em reports/evidence/<data>/smoke-<HHMM>/.
# Nada sai daqui: login e emails usam o modo desenvolvimento (sem envio).
set -uo pipefail
cd "$(dirname "$0")"
LAB=$(cd .. && pwd)
OUT="$LAB/reports/evidence/$(date +%F)/smoke-$(date +%H%M)"
mkdir -p "$OUT"
fail() { echo "=== SMOKE: FAIL — $1 ==="; exit 1; }
mongo() { docker compose exec -T mongo mongosh --quiet rooms-reservation-app --eval "$1"; }

echo "[1/4] serviços"
for u in http://127.0.0.1:3000/ http://127.0.0.1:5000/apidocs/ \
         http://127.0.0.1:5050/apidocs/ http://127.0.0.1:5081/apispec.json \
         http://127.0.0.1:9000/minio/health/live; do
  ok=""
  for _ in $(seq 1 90); do
    c=$(curl -s -o /dev/null -L -w '%{http_code}' -m 3 "$u")
    [ "$c" = 200 ] && ok=1 && break
    sleep 3
  done
  [ -n "$ok" ] || fail "$u não respondeu 200 (último: $c)"
  echo "      200  $u"
done

# Aquece o bundle do dev server (compilação/1ª entrega são lentas em cold start).
curl -s -o /dev/null -m 120 http://127.0.0.1:3000/static/js/bundle.js || true

echo "[2/4] catálogo"
K=$(docker compose exec -T internal sh -c 'echo "$API_KEY_LIST"' | cut -d, -f1 | tr -d '\r')
cursos=$(curl -s -L -H "x-api-key: $K" http://127.0.0.1:5081/restapi/courses/ | python3 -c "import sys,json;print(json.load(sys.stdin)['pagination']['total_count'])")
salas=$(curl -s -L -H "x-api-key: $K" http://127.0.0.1:5081/restapi/rooms/ | python3 -c "import sys,json;print(json.load(sys.stdin)['pagination']['total_count'])")
echo "      cursos=$cursos salas=$salas"
[ "$cursos" = 42 ] && [ "$salas" = 151 ] || fail "catálogo incompleto (cursos=$cursos salas=$salas; esperado 42/151)"
# Cache de 12h do internal_apis: garante que ele não sirva estado anterior ao seed.
docker compose exec -T redis redis-cli FLUSHALL >/dev/null

# Idempotência: apaga eventos sintéticos de execuções anteriores (senão a sala/horário
# já reservado recusa a nova confirmação).
mongo 'const ev=db.events.find({name:/sintética/},{_id:1}).toArray();
  const oid=ev.map(e=>e._id), str=oid.map(String);
  const q={$or:[{eventId:{$in:str}},{eventId:{$in:oid}},{event_id:{$in:str}},{event_id:{$in:oid}}]};
  ["reservations","send_email","pdfs"].forEach(c=>db[c].deleteMany(q));
  db.events.deleteMany({_id:{$in:oid}}); print("      limpos "+oid.length+" eventos sintéticos anteriores")'
echo "[3/4] reserva sintética pela tela"
node "$LAB/reports/capture-reserva.mjs" "$OUT" | sed 's/^/      /'
evento=$(mongo 'const e=db.events.find({name:/sintética/}).sort({_id:-1}).limit(1).toArray()[0]; print(e ? String(e._id)+" "+e.status : "")')
read -r EID ESTADO <<< "$evento"
[ "$ESTADO" = waiting ] || fail "evento $EID ficou '$ESTADO' depois de confirmar (esperado: waiting)"

echo "[4/4] aprovação Coordenação → Reitoria"
TOKEN=$(mongo "const t=db.send_email.find({eventId:'$EID', step:0, active:true}).sort({_id:-1}).limit(1).toArray()[0]; print(t ? t.tokenId : '')")
[ -n "$TOKEN" ] || fail "sem token de aprovação da Coordenação para $EID"
node "$LAB/reports/capture-aprovacao.mjs" "$EID" "$TOKEN" "$OUT" | grep -E "^[0-9]" | sed 's/^/      /'
FINAL=$(mongo "print(db.events.findOne({_id:ObjectId('$EID')}).status)")

# Gerar o PDF sobrescreve arquivos versionados do python-services (backlog DEV-01).
git -C "$LAB/python-services" checkout -- PDFs/evento.pdf PDFs/evento.typ 2>/dev/null || true

[ "$FINAL" = approved_by_reitoria ] || fail "evento $EID terminou '$FINAL' (esperado: approved_by_reitoria)"
echo "=== SMOKE: PASS — catálogo 42/151, reserva $EID aprovada pela Reitoria; prints em ${OUT#$LAB/} ==="
