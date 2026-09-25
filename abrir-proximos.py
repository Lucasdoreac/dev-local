#!/usr/bin/env python3
"""Abre sozinho o próximo PR de cada repositório quando o anterior recebe merge.

Rodado pelo notebook-auto.sh (launchd, a cada 3 h). Para cada repositório da fila
(reports/prs/fila.json, na ordem): acha o primeiro item sem PR aberto na org e o
abre com ./abrir-pr.sh <ID> --sim SE o item anterior do mesmo repositório já
recebeu merge (ou se ele é o primeiro).

Travas:
  * no máximo UM PR por repositório por execução;
  * item anterior fechado SEM merge = para aquele repositório e avisa (precisa de gente);
  * abrir-pr.sh ainda confere a suíte medida na ponta (FAIL ou não medida = não abre);
  * dependência entre repositórios (ex.: PS-3 depende de SR-2) não trava a abertura:
    ela vale para o deploy e está escrita no texto do PR.

    ./abrir-proximos.py --dry-run   # só mostra o que abriria
    ./abrir-proximos.py             # abre
"""
import argparse
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
FILA = HERE.parent / "reports" / "prs" / "fila.json"


def prs_da_org(org, repo):
    """pr/<ID> -> 'open' | 'merged' | 'closed' (PRs do dono, pelo fork)."""
    out = subprocess.run(["gh", "pr", "list", "--repo", f"{org}/{repo}", "--state", "all", "--author", "@me",
                          "--limit", "100", "--json", "headRefName,state"],
                         capture_output=True, text=True, timeout=120, check=True)
    return {p["headRefName"][3:]: p["state"].lower()
            for p in json.loads(out.stdout) if p["headRefName"].startswith("pr/")}


def plano(dados):
    """[(repo, id a abrir | None, motivo)] por repositório."""
    por_repo = {}
    for item in dados["fila"]:
        por_repo.setdefault(item["repo"], []).append(item["id"])
    resultado = []
    for repo, ids in por_repo.items():
        estados = prs_da_org(dados["org"], repo)
        anterior = None
        for pid in ids:
            estado = estados.get(pid)
            if estado == "merged":
                anterior = pid
                continue
            if estado == "open":
                resultado.append((repo, None, f"{pid} aberto, aguardando revisão"))
                break
            if estado == "closed":
                resultado.append((repo, None, f"ATENÇÃO: {pid} foi fechado sem merge; precisa de decisão"))
                break
            # sem PR: abre se o anterior entrou (ou se é o primeiro)
            resultado.append((repo, pid, f"anterior {anterior} aceito" if anterior else "primeiro da fila"))
            break
        else:
            resultado.append((repo, None, "fila deste repositório concluída"))
    return resultado


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dados = json.loads(FILA.read_text())
    atencao, abertos = [], 0
    for repo, pid, motivo in plano(dados):
        if motivo.startswith("ATENÇÃO"):
            atencao.append(f"{repo}: {motivo}")
        if pid is None:
            print(f"{repo}: {motivo}")
            continue
        print(f"{repo}: abre {pid} ({motivo})")
        if not args.dry_run:
            r = subprocess.run([str(HERE / "abrir-pr.sh"), pid, "--sim"], text=True)
            if r.returncode != 0:
                atencao.append(f"{repo}: abrir {pid} falhou (código {r.returncode})")
            else:
                abertos += 1
    print(f"=== ABRIR PRÓXIMOS: {abertos} aberto(s) ===")
    if atencao:
        print("\n".join(atencao))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
