#!/usr/bin/env bash
# npm audit no package-lock.json do frontend do Reservas, num container node
# descartável (o lockfile entra por stdin; nada é instalado na pasta).
# Sai com 1 se houver vulnerabilidade que o `npm audit fix` (sem --force)
# resolveria. As que exigem versão maior (ex.: presas ao react-scripts/CRA)
# são listadas à parte e não reprovam: dependem da migração do CRA.
#   ./audit-frontend.sh [--strict] [pasta do frontend, relativa a ~/LABTECH]
#   --strict: reprova também qualquer alerta high/critical, mesmo sem correção menor
#   --zero: reprova qualquer alerta
set -uo pipefail
STRICT=""; case "${1:-}" in --strict) STRICT=1; shift ;; --zero) STRICT=2; shift ;; esac
cd "$(dirname "$0")/../${1:-interfaces-usuario/reservas}"   # outro frontend: ./audit-frontend.sh teachers-allocation/frontend
NODE_IMAGE="${NODE_IMAGE:-node:24}"
json=$(COPYFILE_DISABLE=1 tar c package.json package-lock.json |
  docker run --rm -i "$NODE_IMAGE" bash -c 'mkdir /w && tar x -C /w 2>/dev/null && cd /w && npm audit --json 2>/dev/null')
python3 - "$json" "$STRICT" <<'PY'
import json, sys
d = json.loads(sys.argv[1]); v = d.get("vulnerabilities", {}); strict = sys.argv[2] in ("1", "2"); zero = sys.argv[2] == "2"
print("total:", d["metadata"]["vulnerabilities"])
fixable = sorted(n for n, x in v.items() if x.get("fixAvailable") is True)
major = sorted(n for n, x in v.items() if isinstance(x.get("fixAvailable"), dict))
none = sorted(n for n, x in v.items() if x.get("fixAvailable") is False)
direct = {n: x["severity"] for n, x in v.items() if x.get("isDirect")}
print(f"corrigíveis sem versão maior ({len(fixable)}):", ", ".join(fixable) or "-")
print(f"só com versão maior/CRA ({len(major)}), sem correção ({len(none)})")
print("dependências diretas afetadas:", direct or "-")
severe = sorted(n for n, x in v.items() if x["severity"] in ("high", "critical"))
if strict:
    print(f"--strict: high/critical ({len(severe)}):", ", ".join(severe) or "-")
if zero:
    print(f"--zero: qualquer alerta ({len(v)}):", ", ".join(sorted(v)) or "-")
fail = bool(fixable) or (strict and bool(severe)) or (zero and bool(v))
print("=== AUDIT FRONT: " + ("PASS" if not fail else "FAIL") + (" (zero)" if zero else " (strict)" if strict else "") + " ===")
sys.exit(1 if fail else 0)
PY
