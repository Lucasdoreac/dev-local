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
    ./notebook-sync.py --only python-services --prune   # um repo só (usado pelo hook de push)

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

# repo -> branch (ponta da pilha de branches locais em 25/09/2026). Dos 16 repos da
# org, estes são os que interessam ao Reservas; ficam de fora java-services e
# eventos-angular (arquivados), Hi.Events (fork sem commits), CoOps (métricas),
# RAG-TCC (outro projeto), demo-repository (modelo vazio), crispy-octo-cluster
# (só o nginx do gateway descartado) e CLI (lançador genérico; o dev-local faz isso).
REPOS = {
    "python-services": "feat/issue-64-submit-unico",
    "shared-resources": "chore/graphene-3",
    "interfaces-usuario": "feat/issue-64-submit-unico",
    "scripts": "main",
    "entidades": "main",
    "teachers-allocation": "chore/runtime-updates",
    "supreme-test-framework": "master",
    "ajuda-documentacao": "main",
}
# Dados que não sobem (nomes de professores, cópia do banco da UDF).
REPO_EXCLUDES = {
    "scripts": ("collection/", "new_collection/"),
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


# Valor de exemplo (".env.example", README): contém uma destas palavras.
PLACEHOLDER_WORDS = ("your", "here", "change", "example", "placeholder", "dummy", "xxx",
                     "sua", "chave", "troque", "replace", "fake", "falsa")


def looks_like_secret(line):
    for pattern in SECRET_PATTERNS:
        m = pattern.search(line)
        if m and not any(w in m.group(0).lower() for w in PLACEHOLDER_WORDS):
            return True
    return False


def git(repo, *args):
    return subprocess.run(["git", "-C", str(LAB / repo), *args], check=True,
                          capture_output=True, text=True).stdout


def skip(path, repo=None):
    name = path.rsplit("/", 1)[-1]
    return (path.startswith(REPO_EXCLUDES.get(repo, ())) or name in SKIP_NAMES or name.startswith(".env.") and name != ".env.example"
            or path.lower().endswith(SKIP_EXT) or any(d in path for d in SKIP_DIRS))


def bundle(repo, ref, commit=None):
    """`ref` dá o nome (título); `commit`, se vier, é o que é lido de fato
    (o hook de push manda o sha exato que chegou ao GitHub)."""
    ref_name, ref = ref, commit or ref
    sha = git(repo, "rev-parse", "--short", ref).strip()
    parts, excluded, secrets = [], 0, []
    current = []
    size = 0
    for path in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines():
        if skip(path, repo):
            excluded += 1
            continue
        raw = subprocess.run(["git", "-C", str(LAB / repo), "show", f"{ref}:{path}"],
                             capture_output=True).stdout
        if b"\0" in raw[:8000]:
            excluded += 1
            continue
        text = raw.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if looks_like_secret(line):
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


def old_versions(existing, synced_repos, keep_ids):
    """Fontes antigas deste script a apagar: só dos repos sincronizados agora, e
    nunca as que ficam (recém-subidas ou já atualizadas). Compara por ID: duas
    fontes podem ter o mesmo título."""
    prefixes = tuple(f"{TITLE_PREFIX}{repo} @ " for repo in synced_repos)
    return [s for s in existing
            if str(s.get("title", "")).startswith(prefixes) and s.get("id") not in keep_ids]


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
    ap.add_argument("--only", action="append", default=[], help="sincroniza só este repo")
    ap.add_argument("--commit", action="append", default=[], help="repo=sha: lê este commit (título mantém a branch)")
    args = ap.parse_args()
    repos = dict(REPOS)
    for item in args.ref:
        repo, _, ref = item.partition("=")
        repos[repo] = ref
    if args.only:
        unknown = set(args.only) - set(repos)
        if unknown:
            print("repo desconhecido:", ", ".join(sorted(unknown)))
            return 2
        repos = {r: repos[r] for r in args.only}

    commits = dict(item.partition("=")[::2] for item in args.commit)

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
        sha, parts, excluded, secrets = bundle(repo, ref, commits.get(repo))
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

    # 3. Sobe o que mudou (versão igual já no caderno = pula); só depois poda.
    by_title = {}
    for s in existing:
        by_title.setdefault(s.get("title"), s.get("id"))
    keep, uploaded = set(), 0
    for title, body in sources:
        if title in by_title:
            keep.add(by_title[title])
            print("  já atualizado:", title)
            continue
        res = nlm("source", "add", NOTEBOOK_ID, "--text", body, "--title", title, "--wait")
        new_id = res.get("id") or res.get("source_id") or (res.get("source") or {}).get("id")
        if not new_id:
            print("ABORTADO antes da poda: não recebi o ID da fonte nova", title)
            return 4
        keep.add(new_id)
        uploaded += 1
        print("  subiu:", title)
    if args.prune:
        for s in old_versions(existing, repos, keep):
            nlm("source", "delete", s["id"], "--confirm")
            print("  apagou versão antiga:", s["title"])
    print(f"=== NOTEBOOK SYNC: {uploaded} nova(s), {len(keep) - uploaded} já atualizada(s) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
