#!/usr/bin/env python3
"""Vulnerabilidades conhecidas (base pública OSV, osv.dev) nos poetry.lock do
Reservas e no requirements.txt da Alocação. Só manda nome e versão dos pacotes (informação pública).

    ./audit-python.py            # os 3 serviços
    ./audit-python.py --detalhe  # lista os IDs por pacote

Sai com 1 se algum pacote tiver vulnerabilidade conhecida.
"""
import json
import pathlib
import re
import sys
import urllib.request

LAB = pathlib.Path(__file__).resolve().parents[1]
LOCKS = {
    "python-services": LAB / "python-services/poetry.lock",
    "internal_apis": LAB / "shared-resources/internal_apis/poetry.lock",
    "auth_service": LAB / "shared-resources/auth_service/poetry.lock",
    "teachers-allocation": LAB / "teachers-allocation/backend/requirements.txt",
}


def packages(lock):
    text = lock.read_text()
    if lock.name == "requirements.txt":  # versões fixas "nome==versão"
        return re.findall(r"^([A-Za-z0-9_.\-]+)==([^\s;#]+)", text, re.MULTILINE)
    return re.findall(r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', text)


def osv(pkgs):
    query = {"queries": [{"package": {"name": n, "ecosystem": "PyPI"}, "version": v} for n, v in pkgs]}
    req = urllib.request.Request("https://api.osv.dev/v1/querybatch", data=json.dumps(query).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=60))["results"]


def main():
    detail = "--detalhe" in sys.argv
    total = 0
    for name, lock in LOCKS.items():
        pkgs = packages(lock)
        hits = [(n, v, [x["id"] for x in r["vulns"]]) for (n, v), r in zip(pkgs, osv(pkgs)) if r.get("vulns")]
        total += len(hits)
        print(f"{name}: {len(pkgs)} pacotes, {len(hits)} com vulnerabilidade conhecida")
        for n, v, ids in sorted(hits):
            print(f"   {n} {v}" + (f": {', '.join(ids)}" if detail else f" ({len(ids)})"))
    print("=== AUDIT: " + ("PASS" if total == 0 else f"FAIL ({total} pacotes)") + " ===")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
