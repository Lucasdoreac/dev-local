#!/usr/bin/env python3
"""Consulta o OSV para todas as dependências travadas das lanes de lanes.json.

Lê as locks que cada lane altera (pasta do serviço ou raiz; ver owned_locks) (poetry.lock e yarn.lock v1),
remove duplicatas e manda uma única consulta querybatch ao OSV. Pacotes que
reports/DEPENDENCIAS.csv marca como bloqueados pela faixa do pai aparecem
destacados: um advisory neles pede o playbook "Advisory em pacote bloqueado"
do README, não um bump comum.

Saída: 0 sem achados, 1 com achados, 2 se a consulta falhar.

    ./check-advisories.py              # locks das lanes
    ./check-advisories.py --self-test  # confirma que o OSV detecta pinos vulneráveis conhecidos
    ./run-tests.sh advisories          # o mesmo, no runner Docker linux/amd64
"""
import csv
import json
import pathlib
import re
import sys
import tomllib
import urllib.request

DEV = pathlib.Path(__file__).resolve().parent
LAB = DEV.parent
OSV_BATCH = "https://api.osv.dev/v1/querybatch"
# Pinos com advisories publicados há anos; se o OSV não os acusar, a consulta
# não está funcionando e o resultado "0 achados" não vale.
KNOWN_VULNERABLE = [("PyPI", "jinja2", "2.10"), ("npm", "lodash", "4.17.15")]
LOCK_NAMES = ("poetry.lock", "yarn.lock")
YARN_ENTRY = re.compile(r'^"?((?:@[^@/"\s]+/)?[^@"\s]+)@[^\n]*:\n  version "([^"]+)"', re.M)


def parse_poetry_lock(text):
    return {("PyPI", p["name"].lower(), p["version"]) for p in tomllib.loads(text).get("package", [])}


def parse_yarn_lock(text):
    return {("npm", name, version) for name, version in YARN_ENTRY.findall(text)}


def owned_locks(lane, lanes):
    """Locks que a lane altera. Em repo com vários serviços (shared-resources)
    cada lane carrega a lock do outro serviço como está na main da org; quem a
    atualiza é a lane irmã, então ela não entra aqui. Lane fora do Compose
    (ex.: só Dockerfile) herda as locks do pai no mesmo repo."""
    dirs = [d.strip("/") for d in lane["compose"].values() if d.strip("/") not in ("", ".")]
    if not dirs and lane["compose"]:
        dirs = [""]
    if not dirs:
        by_id = {other["id"]: other for other in lanes}
        same_repo = [by_id[p] for p in lane["parents"] if by_id[p]["repo"] == lane["repo"]]
        if same_repo:
            return owned_locks(same_repo[0], lanes)
        dirs = [""]
    return [f"{d}/{name}" if d else name for d in dirs for name in LOCK_NAMES]


def lane_locks(lanes, lab=LAB):
    """Mapeia cada lock distinta (por conteúdo) às lanes que a usam."""
    found = {}
    for lane in lanes:
        worktree = lab / lane["worktree"]
        paths = sorted(worktree / name for name in owned_locks(lane, lanes) if (worktree / name).exists())
        if not paths:
            raise FileNotFoundError(f"lane {lane['id']}: nenhuma lock em {lane['worktree']}")
        for path in paths:
            text = path.read_text()
            entry = found.setdefault(text, {"lanes": [], "file": path.name})
            entry["lanes"].append(lane["id"])
    return found


def packages_from_locks(locks):
    packages = {}
    for text, entry in locks.items():
        parsed = parse_yarn_lock(text) if entry["file"].endswith("yarn.lock") else parse_poetry_lock(text)
        for package in parsed:
            packages.setdefault(package, set()).update(entry["lanes"])
    return packages


def blocked_packages(csv_path=LAB / "reports" / "DEPENDENCIAS.csv"):
    if not pathlib.Path(csv_path).exists():
        return set()
    with open(csv_path) as handle:
        return {row["package"].lower() for row in csv.DictReader(handle) if row["status"] != "latest"}


def osv_querybatch(packages):
    """Lista de IDs de advisory por pacote, na mesma ordem."""
    queries = [{"package": {"ecosystem": eco, "name": name}, "version": version} for eco, name, version in packages]
    results = []
    for start in range(0, len(queries), 1000):
        body = json.dumps({"queries": queries[start:start + 1000]}).encode()
        request = urllib.request.Request(OSV_BATCH, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=60) as response:
            results += [[v["id"] for v in r.get("vulns", [])] for r in json.load(response)["results"]]
    return results


def findings(packages, query=osv_querybatch):
    ordered = sorted(packages)
    return [(package, ids) for package, ids in zip(ordered, query(ordered)) if ids]


def main(argv, query=osv_querybatch):
    try:
        if "--self-test" in argv:
            hits = findings(set(KNOWN_VULNERABLE), query)
            for (eco, name, version), ids in hits:
                print(f"self-test: {eco} {name} {version} -> {len(ids)} advisory(s)")
            if len(hits) != len(KNOWN_VULNERABLE):
                print("=== CHECK ADVISORIES: SELF-TEST FAIL (OSV não acusou pino vulnerável conhecido) ===")
                return 2
            print("=== CHECK ADVISORIES: SELF-TEST PASS ===")
            return 0
        lanes = json.loads((DEV / "lanes.json").read_text())["lanes"]
        packages = packages_from_locks(lane_locks(lanes))
        blocked = blocked_packages()
        hits = findings(packages, query)
    except Exception as exc:  # rede, OSV ou lock ilegível: não é "sem achados"
        print(f"=== CHECK ADVISORIES: ERRO ({exc.__class__.__name__}: {exc}) ===")
        return 2
    print(f"{len(packages)} pacotes travados em {len(lanes)} lanes; {len(blocked)} bloqueados pelo pai")
    for (eco, name, version), ids in hits:
        mark = " [BLOQUEADO PELO PAI: ver playbook]" if name in blocked else ""
        print(f"   ✗ {eco} {name} {version}: {', '.join(ids)} (lanes {', '.join(sorted(packages[(eco, name, version)]))}){mark}")
    if hits:
        print(f"=== CHECK ADVISORIES: FAIL ({len(hits)}) ===")
        return 1
    print("=== CHECK ADVISORIES: PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
