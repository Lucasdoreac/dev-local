#!/usr/bin/env python3
"""Sobe o código dos repositórios do Reservas como fontes do caderno NotebookLM
"Darlas 2022", para o squad consultar o código de verdade.

Mesmo desenho do refresh do caderno do SOBER (~/Desktop/sober,
app/services/sober_notebook_refresh.py), aplicado aos repos do LabTech:
  * lê o caderno ANTES de tudo; se falhar, aborta sem subir nem apagar;
  * só arquivos versionados no git, lidos do commit da branch (não da pasta:
    `.env` e arquivos locais nunca entram), sem binários nem lockfiles;
  * varredura de segredo no texto empacotado: achou, aborta;
  * sobe TODAS as fontes novas e só então, com --prune, apaga as antigas
    criadas por este script (título "LabTech código: <repo> @ ...").

Uso:
    ./notebook-sync.py --dry-run          # mostra o que subiria, não toca no caderno
    ./notebook-sync.py                    # sobe as fontes novas
    ./notebook-sync.py --prune            # sobe e apaga as versões antigas deste script
    ./notebook-sync.py --ref python-services=main   # outra branch/commit

Nunca manda para o caderno do Estágio (público: o código traz e-mails de
desenvolvedores).
"""
import argparse
import json
import pathlib
import re
import subprocess
import sys

LAB = pathlib.Path(__file__).resolve().parents[1]
NOTEBOOK_ID = "33c068ee-16a4-4fd2-852b-f111adaa5087"  # Darlas 2022
TITLE_PREFIX = "LabTech código: "

# repo -> branch (ponta da pilha de branches locais em 25/09/2026)
REPOS = {
    "python-services": "chore/python-patches",
    "shared-resources": "chore/python-patches",
    "interfaces-usuario": "chore/frontend-patches",
}
# fonte de texto grande demais vira várias partes
MAX_CHARS = 350_000

SKIP_NAMES = {"poetry.lock", "package-lock.json", "yarn.lock", ".env"}
SKIP_EXT = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp", ".woff", ".woff2", ".ttf",
            ".eot", ".pdf", ".zip", ".gz", ".tar", ".typ", ".pyc", ".db", ".sqlite", ".mp4")
SKIP_DIRS = ("node_modules/", "__pycache__/", ".idea/", "PDFs/")

# Segredo de verdade (valor), não a menção do nome da variável.
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    re.compile(r"xkeysib-[0-9a-f]{20,}"),
    re.compile(r"mongodb(\+srv)?://[^:\s/]+:[^@\s{}$<]{6,}@"),
    re.compile(r"(?i)\b(api[_-]?key|secret[_-]?key|password|passwd|token)\s*[:=]\s*['\"][A-Za-z0-9_\-/+=]{16,}['\"]"),
]


def git(repo, *args):
    return subprocess.run(["git", "-C", str(LAB / repo), *args], check=True,
                          capture_output=True, text=True).stdout


def skip(path):
    name = path.rsplit("/", 1)[-1]
    return (name in SKIP_NAMES or name.startswith(".env.") and name != ".env.example"
            or path.lower().endswith(SKIP_EXT) or any(d in path for d in SKIP_DIRS))


def bundle(repo, ref):
    sha = git(repo, "rev-parse", "--short", ref).strip()
    parts, excluded, secrets = [], 0, []
    current = []
    size = 0
    for path in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines():
        if skip(path):
            excluded += 1
            continue
        raw = subprocess.run(["git", "-C", str(LAB / repo), "show", f"{ref}:{path}"],
                             capture_output=True).stdout
        if b"\0" in raw[:8000]:
            excluded += 1
            continue
        text = raw.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if any(p.search(line) for p in SECRET_PATTERNS):
                secrets.append(f"{repo}:{path}:{lineno}")  # nunca o valor
        block = f"\n\n===== {path} =====\n{text}"
        if size + len(block) > MAX_CHARS and current:
            parts.append("".join(current))
            current, size = [], 0
        current.append(block)
        size += len(block)
    if current:
        parts.append("".join(current))
    return sha, parts, excluded, secrets


def nlm(*args):
    out = subprocess.run(["nlm", *args, "--json"], capture_output=True, text=True, timeout=900)
    if out.returncode != 0:
        raise RuntimeError(f"nlm {args[0]} {args[1]} falhou (código {out.returncode})")
    return json.loads(out.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune", action="store_true")
    ap.add_argument("--ref", action="append", default=[], help="repo=branch")
    args = ap.parse_args()
    repos = dict(REPOS)
    for item in args.ref:
        repo, _, ref = item.partition("=")
        repos[repo] = ref

    # 1. Caderno primeiro: sessão expirada = aborta sem tocar em nada.
    if not args.dry_run:
        try:
            existing = nlm("source", "list", NOTEBOOK_ID)
        except Exception as exc:
            print(f"ABORTADO: não consegui ler o caderno ({exc.__class__.__name__}). Rode `nlm login`.")
            return 2
        existing = existing if isinstance(existing, list) else existing.get("sources", [])

    # 2. Empacota e varre segredos.
    sources, all_secrets = [], []
    for repo, ref in repos.items():
        sha, parts, excluded, secrets = bundle(repo, ref)
        all_secrets += secrets
        for i, body in enumerate(parts, 1):
            suffix = f" (parte {i}/{len(parts)})" if len(parts) > 1 else ""
            title = f"{TITLE_PREFIX}{repo} @ {ref} {sha}{suffix}"
            header = (f"Código do repositório {repo}, branch {ref}, commit {sha}. Só arquivos "
                      f"versionados; sem lockfiles, binários e .env. Gerado por dev-local/notebook-sync.py.")
            sources.append((title, header + body))
        print(f"{repo} @ {ref} {sha}: {len(parts)} fonte(s), {sum(map(len, parts)) // 1024} KB, "
              f"{excluded} arquivos excluídos")
    if all_secrets:
        print("ABORTADO: possível segredo em", ", ".join(all_secrets))
        return 3
    print("varredura de segredos: nada encontrado")
    if args.dry_run:
        for title, _ in sources:
            print("  subiria:", title)
        return 0

    # 3. Sobe tudo; só depois poda.
    added = []
    for title, body in sources:
        res = nlm("source", "add", NOTEBOOK_ID, "--text", body, "--title", title, "--wait")
        added.append(title)
        print("  subiu:", title)
    if args.prune:
        old = [s for s in existing if str(s.get("title", "")).startswith(TITLE_PREFIX)
               and s.get("title") not in added]
        for s in old:
            nlm("source", "delete", s["id"], "--confirm")
            print("  apagou versão antiga:", s["title"])
    print(f"=== NOTEBOOK SYNC: {len(added)} fonte(s) no caderno Darlas 2022 ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
