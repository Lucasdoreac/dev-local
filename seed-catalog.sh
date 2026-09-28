#!/usr/bin/env bash
set -euo pipefail

MONGO_HOST="mongo"
MONGO_DATABASE="rooms-reservation-app"
SEED_ARCHIVE="${SEED_ARCHIVE:-/seed/labtech.backup.tar.gz}"

if [[ ! -f "$SEED_ARCHIVE" ]]; then
  echo "ERRO: arquivo de seed não encontrado: $SEED_ARCHIVE" >&2
  exit 1
fi

# Qualquer documento do catálogo impede o `--drop` automático. A atualização
# de dados existentes exige backup e procedimento explícito.
catalog_count="$(mongosh --host "$MONGO_HOST" --quiet "$MONGO_DATABASE" --eval '
  const catalog = ["campus", "rooms", "courses", "disciplines", "offers", "periods", "teachers", "types"];
  print(catalog.reduce((total, name) => total + db.getCollection(name).countDocuments({}), 0));
' | tail -n 1)"

if [[ ! "$catalog_count" =~ ^[0-9]+$ ]]; then
  echo "ERRO: resposta inválida ao contar documentos do catálogo: $catalog_count" >&2
  exit 1
fi

if (( catalog_count > 0 )); then
  echo "Seed automático ignorado: catálogo existente com $catalog_count documentos."
  exit 0
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
tar -xzf "$SEED_ARCHIVE" -C "$tmp_dir" mongo-backups/scripts
mongorestore --host "$MONGO_HOST" --quiet --drop --db "$MONGO_DATABASE" \
  "$tmp_dir/mongo-backups/scripts/scripts"
mongosh --host "$MONGO_HOST" --quiet "$MONGO_DATABASE" --eval '
  db.teachers.updateOne({_id:"coord-sintetico-enf"},
    {$set:{PROFESSOR:"Coordenação Sintética ENF (teste local)", COD_CURS:[31], email:"coordenacao-sintetica@udf.edu.br"}}, {upsert:true});
  db.courses.updateOne({_id:31}, {$set:{COORDINATOR:"coord-sintetico-enf"}});
  print("seed local concluído");
'
