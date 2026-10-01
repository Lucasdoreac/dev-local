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

As fontes são as lanes de lanes.json: uma por PR aberto, lida da branch local
da lane. Repo com mais de uma lane (shared-resources) sobe de cada lane só a
pasta do seu serviço, mais arquivos da raiz e .github/.

Uso:
    ./notebook-sync.py --dry-run          # mostra o que subiria, não toca no caderno
    ./notebook-sync.py                    # sobe as fontes novas
    ./notebook-sync.py --prune            # sobe e apaga as versões antigas deste script
    ./notebook-sync.py --only python-services --prune   # lanes de um repo só
    ./notebook-sync.py --push shared-resources chore/auth-dependencies-focused <sha> --prune
                                          # hook de push: só a lane daquela branch do fork

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

LANES_FILE = LAB / "dev-local" / "lanes.json"


def lane_sources(lanes):
    """Uma fonte por lane. Com várias lanes no mesmo repo, cada uma traz só as
    pastas dos seus serviços (campo compose), a raiz e .github/."""
    per_repo = {}
    for lane in lanes:
        per_repo.setdefault(lane["repo"], []).append(lane)
    sources = []
    for lane in lanes:
        dirs = sorted({d.strip("/") for d in lane["compose"].values()} - {"", "."})
        paths = None
        if len(per_repo[lane["repo"]]) > 1 and dirs:
            paths = tuple(f"{d}/" for d in dirs) + (".github/",)
        sources.append({
            "repo": lane["repo"], "lane": lane["id"], "ref": lane["local_branch"],
            "fork_branch": lane["fork_branch"],
            "label": f"PR #{lane['pr']} {lane['fork_branch']}", "paths": paths,
        })
    return sources


SOURCES = lane_sources(json.loads(LANES_FILE.read_text())["lanes"])
REPOS = sorted({source["repo"] for source in SOURCES})  # usado por install-hooks.sh
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
        if not m:
            continue
        # O valor inteiro (até espaço/aspas) conta: uma URI de teste só revela
        # o host reservado *.example.* depois do "@".
        token = re.match(r"[^\s'\"]*", line[m.start():]).group(0)
        if not any(w in max(m.group(0), token, key=len).lower() for w in PLACEHOLDER_WORDS):
            return True
    return False


def git(repo, *args):
    return subprocess.run(["git", "-C", str(LAB / repo), *args], check=True,
                          capture_output=True, text=True).stdout


def skip(path, repo=None, paths=None):
    name = path.rsplit("/", 1)[-1]
    outside = paths is not None and "/" in path and not path.startswith(paths)
    return (outside or path.startswith(REPO_EXCLUDES.get(repo, ())) or name in SKIP_NAMES or name.startswith(".env.") and name != ".env.example"
            or path.lower().endswith(SKIP_EXT) or any(d in path for d in SKIP_DIRS))


def bundle(repo, ref, commit=None, paths=None):
    """`commit`, se vier, é o que é lido de fato (o hook de push manda o sha
    exato que chegou ao GitHub); `paths` limita às pastas da lane."""
    ref = commit or ref
    sha = git(repo, "rev-parse", "--short", ref).strip()
    parts, excluded, secrets = [], 0, []
    current = []
    size = 0
    for path in git(repo, "ls-tree", "-r", "--name-only", ref).splitlines():
        if skip(path, repo, paths):
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


def title_prefix(source=None, repo=None):
    if source is None:
        return f"{TITLE_PREFIX}{repo} @ "
    return f"{TITLE_PREFIX}{source['repo']} @ {source['label']} "


def old_versions(existing, prefixes, keep_ids):
    """Fontes antigas deste script a apagar: só com os prefixos sincronizados
    agora, e nunca as que ficam (recém-subidas ou já atualizadas). Compara por
    ID: duas fontes podem ter o mesmo título."""
    prefixes = tuple(prefixes)
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
    ap.add_argument("--only", action="append", default=[], help="sincroniza só as lanes deste repo")
    ap.add_argument("--push", nargs=3, metavar=("REPO", "BRANCH_FORK", "SHA"),
                    help="hook de push: sincroniza só a lane desta branch do fork, lendo o SHA enviado")
    args = ap.parse_args()
    sources, commit = list(SOURCES), None
    if args.only:
        unknown = set(args.only) - set(REPOS)
        if unknown:
            print("repo desconhecido:", ", ".join(sorted(unknown)))
            return 2
        sources = [s for s in sources if s["repo"] in args.only]
    if args.push:
        repo, branch, commit = args.push
        sources = [s for s in sources if s["repo"] == repo and s["fork_branch"] == branch]
        if not sources:
            print(f"{repo} {branch} não é branch de lane: caderno não muda")
            return 0
    # Sincronização parcial (hook) só poda versões antigas da própria lane;
    # a completa poda tudo deste script nos repos sincronizados, inclusive
    # fontes de branches que deixaram de ser lanes.
    if args.push:
        prune_prefixes = [title_prefix(s) for s in sources]
    else:
        prune_prefixes = [title_prefix(repo=r) for r in sorted({s["repo"] for s in sources})]

    # 1. Caderno primeiro: sessão expirada = aborta sem tocar em nada.
    if not args.dry_run:
        try:
            existing = nlm("source", "list", NOTEBOOK_ID)
        except Exception as exc:
            print(f"ABORTADO: não consegui ler o caderno ({exc.__class__.__name__}). Rode `nlm login`.")
            return 2
        existing = existing if isinstance(existing, list) else existing.get("sources", [])

    # 2. Empacota e varre segredos.
    bundles, all_secrets = [], []
    for source in sources:
        repo, label = source["repo"], source["label"]
        sha, parts, excluded, secrets = bundle(repo, source["ref"], commit, source["paths"])
        all_secrets += secrets
        scope = f", pastas {' '.join(source['paths'])}" if source["paths"] else ""
        for i, body in enumerate(parts, 1):
            suffix = f" (parte {i}/{len(parts)})" if len(parts) > 1 else ""
            title = f"{title_prefix(source)}{sha}{suffix}"
            header = (f"Código do repositório {repo}, {label}, commit {sha}{scope}. Só arquivos "
                      f"versionados; sem lockfiles, binários e .env. Gerado por dev-local/notebook-sync.py.")
            bundles.append((title, header + body))
        print(f"{repo} @ {label} {sha}: {len(parts)} fonte(s), {sum(map(len, parts)) // 1024} KB, "
              f"{excluded} arquivos excluídos{scope}")
    if all_secrets:
        print("ABORTADO: possível segredo em", ", ".join(all_secrets))
        return 3
    print("varredura de segredos: nada encontrado")
    if args.dry_run:
        for title, _ in bundles:
            print("  subiria:", title)
        print("  podaria (com --prune) fontes antigas com prefixo:", "; ".join(prune_prefixes))
        return 0

    # 3. Sobe o que mudou (versão igual já no caderno = pula); só depois poda.
    by_title = {}
    for s in existing:
        by_title.setdefault(s.get("title"), s.get("id"))
    keep, uploaded = set(), 0
    for title, body in bundles:
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
        for s in old_versions(existing, prune_prefixes, keep):
            nlm("source", "delete", s["id"], "--confirm")
            print("  apagou versão antiga:", s["title"])
    print(f"=== NOTEBOOK SYNC: {uploaded} nova(s), {len(keep) - uploaded} já atualizada(s) ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
