#!/usr/bin/env python3
"""Regras do compose do dev-local que já custaram caro. Lê a configuração
resolvida (todos os perfis) e sai com 1 se alguma regra quebrar.

  * Postgres na versão maior atual (18+), Mongo 8.0+ e Redis 8+.
  * Toda imagem com tag explícita (sem tag = "latest" do dia do pull: não reproduzível).
  * Postgres 18+ com o volume em /var/lib/postgresql: a imagem 18 grava em
    /var/lib/postgresql/18/docker; montar em .../data (padrão até o 17) deixa
    os dados fora do volume nomeado, e eles somem ao recriar o container.

    ./check-compose.py
"""
import json
import pathlib
import re
import subprocess
import sys

MIN_POSTGRES = 18
MIN_MONGO = 8
MIN_REDIS = 8
DEV = pathlib.Path(__file__).resolve().parent


def services():
    out = subprocess.run(["docker", "compose", "--profile", "*", "config", "--format", "json"],
                         cwd=DEV, check=True, capture_output=True, text=True).stdout
    return json.loads(out)["services"]


def problems(svcs):
    found = []
    for name, svc in sorted(svcs.items()):
        image = svc.get("image", "")
        built_here = image.startswith("labtech-dev-")  # construída pelo próprio compose
        if image and not built_here and "@sha256:" not in image and (":" not in image.rsplit("/", 1)[-1] or image.endswith(":latest")):
            found.append(f"{name}: imagem sem tag fixa ({image})")
        rm = re.fullmatch(r"(?:docker\.io/library/)?redis:(\d+)(?:[.\-].*)?", image)
        if rm and int(rm.group(1)) < MIN_REDIS:
            found.append(f"{name}: redis:{rm.group(1)} (mínimo {MIN_REDIS})")
        mm = re.fullmatch(r"(?:docker\.io/library/)?mongo:(\d+)(?:[.\-].*)?", image)
        if mm and int(mm.group(1)) < MIN_MONGO:
            found.append(f"{name}: mongo:{mm.group(1)} (mínimo {MIN_MONGO})")
        m = re.fullmatch(r"(?:docker\.io/library/)?postgres:(\d+)(?:[.\-].*)?", image)
        if not m:
            continue
        major = int(m.group(1))
        targets = [v.get("target") for v in svc.get("volumes", [])]
        if major < MIN_POSTGRES:
            found.append(f"{name}: postgres:{major} (mínimo {MIN_POSTGRES})")
        if major >= 18 and "/var/lib/postgresql" not in targets:
            found.append(f"{name}: postgres:{major} precisa do volume em /var/lib/postgresql (hoje: {targets})")
    return found


def main():
    found = problems(services())
    for p in found:
        print("  ", p)
    print("=== CHECK COMPOSE: " + ("PASS" if not found else f"FAIL ({len(found)})") + " ===")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
