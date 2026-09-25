#!/usr/bin/env python3
"""Fonte "estado e fila" do caderno Darlas 2022, gerada SÓ a partir de dados.

Modelo aprovado pelo dono em 25/09/2026: nenhum texto livre é escrito aqui; a
fonte junta o que já é medido ou versionado:
  * reports/prs/FILA.md e reports/prs/<ID>.md (fila, dependências, seção Deploy);
  * reports/prs/verificacao.txt (suíte medida na ponta de cada PR);
  * estado real de cada PR no GitHub (gh: aberto / mergeado / fechado);
  * REPOS do notebook-sync.py (branch de cada fonte de código);
  * reports/notebook-sources/pendencias.md (lista curada de pendências).

Igual ao notebook-sync.py: lê o caderno antes (sessão expirada = aborta sem
tocar em nada), sobe a versão nova e só então, com --prune, apaga as versões
anteriores DESTE script (título "LabTech estado: ..."). Conteúdo igual ao que já
está no caderno = não sobe nada (o título leva um hash do conteúdo).

    ./notebook-estado.py --dry-run     # imprime a fonte, não toca no caderno
    ./notebook-estado.py --prune       # sobe e apaga a versão anterior
"""
import argparse
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
LAB = HERE.parent
PRS = LAB / "reports" / "prs"
PENDENCIAS = LAB / "reports" / "notebook-sources" / "pendencias.md"
TITLE_PREFIX = "LabTech estado: "
ORG = "LabTechUDF"

spec = importlib.util.spec_from_file_location("notebook_sync", HERE / "notebook-sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def fila():
    """Linhas da FILA.md: (n, id, título, repo, commits, fecha, depende)."""
    rows = []
    for line in (PRS / "FILA.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0].isdigit():
            n, pr, repo, _branch, commits, closes, deps = cells
            pid, _, title = pr.partition(" ")
            rows.append({"id": pid, "titulo": title, "repo": repo, "commits": commits,
                         "fecha": closes, "depende": deps})
    return rows


def verificacao():
    path = PRS / "verificacao.txt"
    out = {}
    for line in path.read_text().splitlines() if path.exists() else []:
        pid, _, rest = line.partition(" ")
        out[pid] = rest.replace("Tests ", "").replace("  ", " ")
    return out


def deploy_note(pid):
    text = (PRS / f"{pid}.md").read_text() if (PRS / f"{pid}.md").exists() else ""
    m = re.search(r"^## Deploy\n(.+?)(?:\n\n|\n## )", text, re.S | re.M)
    return " ".join(m.group(1).split()) if m else ""


def prs_no_github(repos):
    """head pr/<ID> -> (estado, número). Falha do gh = aborta (não publica estado errado)."""
    state = {}
    for repo in sorted(repos):
        out = subprocess.run(["gh", "pr", "list", "--repo", f"{ORG}/{repo}", "--state", "all",
                              "--author", "@me", "--limit", "100",
                              "--json", "number,headRefName,state"],
                             capture_output=True, text=True, timeout=120)
        if out.returncode != 0:
            raise RuntimeError(f"gh pr list {repo} falhou")
        for pr in json.loads(out.stdout):
            head = pr["headRefName"]
            if head.startswith("pr/"):
                state[head[3:]] = (pr["state"].lower(), pr["number"])
    return state


def pendencias_resolvidas():
    """Números das pendências cujo cartão [D-n] foi fechado no quadro público."""
    out = subprocess.run(["gh", "issue", "list", "--repo", "Lucasdoreac/estagio-publico", "--label", "pendencia",
                          "--state", "closed", "--limit", "100", "--json", "title"],
                         capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise RuntimeError("gh issue list (pendências) falhou")
    return [m.group(1) for i in json.loads(out.stdout) if (m := re.match(r"\[D-(\d+)\]", i["title"]))]


ESTADO = {"open": "aberto, em revisão", "merged": "mergeado", "closed": "fechado sem merge"}


def build():
    rows, verif = fila(), verificacao()
    gh = prs_no_github({r["repo"] for r in rows})
    lines = [
        "# 🧱 LabTech — estado e fila de PRs (gerado automaticamente)",
        "",
        "Fonte gerada por dev-local/notebook-estado.py só a partir de dados (fila de PRs, suíte medida "
        "na ponta de cada PR, estado dos PRs no GitHub, branches sincronizadas, lista de pendências). "
        "Substitui versões anteriores desta fonte. Código atualizado: fontes \"LabTech código: <repo> @ <branch>\".",
        "",
        "## PRs na organização",
    ]
    abertos = [(r, gh[r["id"]]) for r in rows if r["id"] in gh]
    if abertos:
        for r, (st, num) in abertos:
            lines.append(f"- {r['id']} → {ORG}/{r['repo']}#{num}: {ESTADO.get(st, st)}. {r['titulo']}")
    else:
        lines.append("- Nenhum PR aberto ainda.")
    faltam = [r for r in rows if r["id"] not in gh]
    lines += ["", f"## Fila local ({len(rows)} PRs; {len(faltam)} ainda não abertos)",
              "Os PRs de um repo formam uma pilha: o próximo só abre depois do merge do anterior."]
    for r in rows:
        partes = [f"**{r['id']}** ({r['repo']}) {r['titulo']}"]
        st = gh.get(r["id"])
        partes.append(f"estado: {ESTADO.get(st[0], st[0]) + ' (#' + str(st[1]) + ')' if st else 'na fila local'}")
        partes.append(f"depende de: {r['depende']}")
        if r["fecha"] not in ("—", ""):
            partes.append(f"fecha: {r['fecha']}")
        partes.append(f"suíte na ponta: {verif.get(r['id'], 'sem suíte medida')}")
        nota = deploy_note(r["id"])
        if nota:
            partes.append(f"deploy: {nota}")
        lines.append("- " + "; ".join(partes))
    lines += ["", "## Código sincronizado (branch de trabalho de cada repo)"]
    lines += [f"- {repo}: {ref}" for repo, ref in sync.REPOS.items()]
    pend = re.sub(r"<!--.*?-->\n?", "", PENDENCIAS.read_text(), flags=re.S).strip()
    # Pendência resolvida no quadro público (cartão [D-n] fechado) sai daqui também.
    for n in pendencias_resolvidas():
        pend = re.sub(rf"^{n}\. .*?(?=^\d+\. |^- |\Z)", "", pend, flags=re.S | re.M)
    lines += ["", "## O que falta (depende de pessoas ou decisões)", pend, ""]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune", action="store_true")
    args = ap.parse_args()

    if not args.dry_run:
        try:
            existing = sync.nlm("source", "list", sync.NOTEBOOK_ID)
        except Exception as exc:
            print(f"ABORTADO: não consegui ler o caderno ({exc.__class__.__name__}). Rode `nlm login`.")
            return 2
        existing = existing if isinstance(existing, list) else existing.get("sources", [])

    try:
        body = build()
    except Exception as exc:
        print(f"ABORTADO: não consegui montar o estado ({exc}).")
        return 2
    secrets = [line for line in body.splitlines() if sync.looks_like_secret(line)]
    if secrets:
        print("ABORTADO: possível segredo na fonte gerada")
        return 3
    digest = hashlib.sha256(body.encode()).hexdigest()[:8]
    title = f"{TITLE_PREFIX}fila de PRs e pendências {digest}"
    if args.dry_run:
        print(body)
        print("título:", title)
        return 0

    ours = [s for s in existing if str(s.get("title", "")).startswith(TITLE_PREFIX)]
    if any(s.get("title") == title for s in ours):
        print("=== NOTEBOOK ESTADO: já atualizado ===")
        keep = {s["id"] for s in ours if s.get("title") == title}
    else:
        res = sync.nlm("source", "add", sync.NOTEBOOK_ID, "--text", body, "--title", title, "--wait")
        new_id = res.get("id") or res.get("source_id") or (res.get("source") or {}).get("id")
        if not new_id:
            print("ABORTADO antes da poda: não recebi o ID da fonte nova")
            return 4
        keep = {new_id}
        print("  subiu:", title)
    if args.prune:
        for s in ours:
            if s.get("id") not in keep:
                sync.nlm("source", "delete", s["id"], "--confirm")
                print("  apagou versão antiga:", s["title"])
    print("=== NOTEBOOK ESTADO: ok ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
