#!/usr/bin/env python3
"""Fonte de estado atual do caderno Darlas 2022, gerada só a partir de dados.

Modelo aprovado pelo dono em 25/09/2026: nenhum texto livre é escrito aqui; a
fonte junta o que já é medido ou versionado:
  * reports/prs/FILA.md e reports/prs/<ID>.md (fila, dependências, seção Deploy);
  * reports/prs/verificacao.txt (suíte medida na ponta de cada PR);
  * estado real de cada PR no GitHub (gh: aberto / mergeado / fechado);
  * SOURCES do notebook-sync.py (lane de PR de cada fonte de código);
  * deploys live dos oito serviços Reservas consultados diretamente no Render;
  * última ronda registrada em MISSAO.md, com a data original preservada.

Igual ao notebook-sync.py: lê o caderno antes (sessão expirada = aborta sem
tocar em nada), sobe a versão nova e só então, com --prune, apaga as versões
anteriores DESTE script (título "LabTech estado: ..."). Conteúdo igual ao que já
está no caderno = não sobe nada (o título leva um hash do conteúdo).

    ./notebook-estado.py --dry-run     # imprime a fonte, não toca no caderno
    ./notebook-estado.py --prune       # sobe e apaga a versão anterior
"""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
LAB = HERE.parent
PRS = LAB / "reports" / "prs"
TITLE_PREFIX = "LabTech estado: "
ORG = "LabTechUDF"
RENDER_TARGETS = (
    ("Production", "reservas-api", "API"),
    ("Production", "reservas-auth", "Auth"),
    ("Production", "reservas-catalog", "Catálogo"),
    ("Production", "reservas-web", "Web"),
    ("Staging", "reservas-staging-api", "API"),
    ("Staging", "reservas-staging-auth", "Auth"),
    ("Staging", "reservas-staging-catalog", "Catálogo"),
    ("Staging", "reservas-staging-web", "Web"),
)
GH_MAX_ATTEMPTS = 3
GH_RETRY_DELAYS = (2, 5)
GH_SECRET = re.compile(r"(?i)\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer\s+[A-Za-z0-9._~+/-]+=*)")

spec = importlib.util.spec_from_file_location("notebook_sync", HERE / "notebook-sync.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def fila():
    """Linhas da FILA.md: (n, id, título, repo, commits, fecha, depende)."""
    rows = []
    for line in (PRS / "FILA.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 7 and cells[0].isdigit():
            n, pr, repo, branch, commits, closes, deps = cells
            pid, _, title = pr.partition(" ")
            rows.append({"id": pid, "titulo": title, "repo": repo, "branch": branch.strip("`"),
                         "commits": commits, "fecha": closes, "depende": deps})
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


def gh_json(label, args, *, max_attempts=GH_MAX_ATTEMPTS, sleep=time.sleep):
    """Executa gh com retry limitado para falhas de transporte e erro visível."""
    transient_markers = (
        "tls handshake timeout", "i/o timeout", "connection reset", "connection refused",
        "temporary failure", "no such host", "unexpected eof", "eof", "timed out",
        "502", "503", "504", "429", "secondary rate limit",
    )
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        try:
            out = subprocess.run(args, capture_output=True, text=True, timeout=120)
            detail = out.stderr.strip()
            if out.returncode == 0:
                if attempt > 1:
                    print(f"GitHub: {label} respondeu na tentativa {attempt}/{max_attempts}.")
                return json.loads(out.stdout)
            last_error = detail or f"gh encerrou com código {out.returncode} sem mensagem de erro"
            retryable = any(marker in last_error.lower() for marker in transient_markers)
            exit_detail = f"código {out.returncode}"
        except subprocess.TimeoutExpired as exc:
            raw = exc.stderr or "tempo limite de 120 s excedido"
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="replace")
            last_error = str(raw).strip() or "tempo limite de 120 s excedido"
            retryable = True
            exit_detail = "timeout após 120 s"

        last_error = GH_SECRET.sub("[REDACTED]", last_error)
        if retryable and attempt < max_attempts:
            delay = GH_RETRY_DELAYS[min(attempt - 1, len(GH_RETRY_DELAYS) - 1)]
            print(f"GitHub: {label} falhou ({exit_detail}; tentativa {attempt}/{max_attempts}): "
                  f"{last_error}. Nova tentativa em {delay} s.")
            sleep(delay)
            continue
        advice = ("Verifique a conectividade com api.github.com e repita a automação."
                  if retryable else "Verifique `gh auth status` e as permissões do repositório.")
        raise RuntimeError(f"GitHub: {label} falhou ({exit_detail}, tentativa {attempt}/{max_attempts}): "
                           f"{last_error}. {advice}")


def prs_no_github(rows):
    """id da fila -> (estado, número), pela branch do fork de cada linha. Falha do gh = aborta."""
    repos = {r["repo"] for r in rows}
    por_branch = {(r["repo"], r["branch"]): r["id"] for r in rows}
    state = {}
    for repo in sorted(repos):
        prs = gh_json(f"listar PRs de {ORG}/{repo}",
                      ["gh", "pr", "list", "--repo", f"{ORG}/{repo}", "--state", "all",
                       "--author", "@me", "--limit", "100",
                       "--json", "number,headRefName,headRefOid,state"])
        for pr in prs:
            pid = por_branch.get((repo, pr["headRefName"]))
            if pid and pid not in state:  # o mais recente vem primeiro
                state[pid] = (pr["state"].lower(), pr["number"],
                              pr["headRefName"], pr["headRefOid"])
    return state


def render_json(label, args, run=None):
    """Lê metadados do Render sem registrar config/env nem o JSON bruto."""
    run = run or subprocess.run
    try:
        out = run(args, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Render: {label} excedeu 120 s") from exc
    except OSError as exc:
        raise RuntimeError(f"Render: {label} não pôde iniciar ({exc.__class__.__name__})") from exc
    if out.returncode != 0:
        detail = GH_SECRET.sub("[REDACTED]", out.stderr.strip())
        raise RuntimeError(f"Render: {label} falhou (código {out.returncode}): "
                           f"{detail or 'sem mensagem do CLI'}")
    try:
        return json.loads(out.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Render: {label} retornou JSON inválido") from exc


def render_snapshot(prs=None, run=None):
    """Resume os últimos deploys live dos oito serviços, consultados agora."""
    run = run or subprocess.run
    records = render_json("listar serviços", ["render", "services", "--output", "json"], run)
    available = {}
    for record in records:
        service = record.get("service", {})
        environment = record.get("environment", {}).get("name")
        key = (environment, service.get("name"))
        if key in {(env, name) for env, name, _ in RENDER_TARGETS}:
            available[key] = service

    lines = ["## Render — deploys consultados nesta execução", ""]
    pr_by_branch = {details[2]: (pid, details) for pid, details in (prs or {}).items()}
    missing = []
    for environment, name, label in RENDER_TARGETS:
        service = available.get((environment, name))
        if not service:
            missing.append(f"{environment}/{name}")
            continue
        deploys = render_json(f"listar deploys de {environment}/{name}",
                              ["render", "deploys", "list", service["id"], "--output", "json"], run)
        live = next((deploy for deploy in deploys if deploy.get("status") == "live"), None)
        latest = deploys[0] if deploys else None
        sha = (live or {}).get("commit", {}).get("id", "")
        detail = f"live `{sha[:7]}`" if sha else "sem deploy live"
        if latest and latest.get("status") != "live":
            latest_sha = latest.get("commit", {}).get("id", "")[:7]
            detail += f"; último deploy `{latest.get('status')}`" + (f" em `{latest_sha}`" if latest_sha else "")
        auto = "ligado" if service.get("autoDeploy") == "yes" else "desligado"
        branch = service.get("branch") or "sem branch declarada"
        relation = ""
        current_pr = pr_by_branch.get(branch)
        if current_pr:
            pid, (state, number, _, head_sha) = current_pr
            if sha and sha == head_sha:
                relation = f"; live SHA coincide com o head atual do PR {pid} (#{number}, {state})"
            else:
                relation = f"; PR {pid} (#{number}, {state}) tem head `{head_sha[:7]}`, " \
                           "diferente do SHA live"
        lines.append(f"- {environment} {label}: {detail}; branch configurada `{branch}`; "
                     f"auto-deploy {auto}{relation}.")
    if missing:
        raise RuntimeError("Render: serviços Reservas ausentes na consulta: " + ", ".join(missing))
    return lines


def latest_mission_round():
    """Último resumo/ação registrado no quadro; preserva sua própria data."""
    path = LAB / "MISSAO.md"
    text = path.read_text() if path.exists() else ""
    match = re.search(r"^## Última ronda\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    if not match:
        return "Sem última ronda registrada no quadro MISSAO.md."
    return " ".join(match.group(1).split())


ESTADO = {"open": "aberto, em revisão", "merged": "mergeado", "closed": "fechado sem merge"}


def build():
    rows, verif = fila(), verificacao()
    gh = prs_no_github(rows)
    render_lines = render_snapshot(gh)
    mission_round = latest_mission_round()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# 🧱 LabTech — estado atual (consultado em {generated})",
        "",
        "Esta é a fonte mais recente de estado operacional. Para perguntas sobre o estado atual, "
        "use esta fonte antes de conversas antigas ou notas históricas do caderno. "
        "Os SHAs live abaixo vêm de consulta ao Render nesta execução; fontes de código não provam deploy. "
        "PRs vêm de consulta ao GitHub nesta execução. PR aberto significa apenas que não foi mesclado "
        "no GitHub; não prova que seu código está ausente de Production. Branch configurada também não "
        "prova o conteúdo live: só declare correspondência quando o SHA live coincidir com o head do PR. "
        "Rondas de MISSAO.md são registros históricos, não estado de deploy nem próximo passo automaticamente "
        "vigente. Se uma consulta falha, esta fonte não é atualizada.",
        "",
        "## PRs na organização",
    ]
    abertos = [(r, gh[r["id"]]) for r in rows if r["id"] in gh]
    if abertos:
        for r, (st, num, _, _) in abertos:
            lines.append(f"- {r['id']} → {ORG}/{r['repo']}#{num}: {ESTADO.get(st, st)}; "
                         f"head `{gh[r['id']][3][:7]}`. {r['titulo']}")
    else:
        lines.append("- Nenhum PR aberto ainda.")
    faltam = [r for r in rows if r["id"] not in gh]
    lines += ["", f"## Fila local ({len(rows)} PRs; {len(faltam)} ainda não abertos)",
              "Os PRs de um repo formam uma pilha: o próximo só abre depois do merge do anterior."]
    for r in rows:
        partes = [f"**{r['id']}** ({r['repo']}) {r['titulo']}"]
        st = gh.get(r["id"])
        partes.append(f"estado: {ESTADO.get(st[0], st[0]) + ' (#' + str(st[1]) + ', head ' + st[3][:7] + ')' if st else 'na fila local'}")
        partes.append(f"depende de: {r['depende']}")
        if r["fecha"] not in ("—", ""):
            partes.append(f"fecha: {r['fecha']}")
        partes.append(f"suíte na ponta: {verif.get(r['id'], 'sem suíte medida')}")
        nota = deploy_note(r["id"])
        if nota:
            partes.append(f"deploy: {nota}")
        lines.append("- " + "; ".join(partes))
    lines += ["", "## Deploys live no Render"] + render_lines
    lines += ["", "## Última ronda registrada no quadro MISSAO.md", mission_round,
              "A data apresentada na própria ronda é a data do registro, não a hora desta consulta.",
              "", "## Código sincronizado (uma fonte por lane de PR)"]
    lines += [f"- {s['repo']}: {s['label']}" for s in sync.SOURCES]
    lines += [""]
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
    title = f"{TITLE_PREFIX}visão atual do Reservas {digest}"
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
