#!/usr/bin/env python3
"""Confere cada lane de lanes.json: worktree local, branch do fork e head do PR.

Uma lane é um PR aberto na organização, a worktree onde ele é editado e a
branch do fork que o PR publica. Sem este mapa, cada sessão acabava criando
outra branch variante. Sai com 1 se algo divergir.

  * worktree existe, está na branch local declarada e sem alterações rastreadas;
  * HEAD da worktree = branch do fork = head do PR (aberto, base e dono certos);
  * Compose e run-tests.sh usam exatamente as worktrees das lanes;
  * `git push` simples na worktree publica na branch do PR: upstream
    fork/<branch do PR> e push.default=upstream (config só da worktree).

    ./check-lanes.py             # completo (git ls-remote + gh)
    ./check-lanes.py --offline   # só checagens locais
"""
import json
import pathlib
import re
import subprocess
import sys

DEV = pathlib.Path(__file__).resolve().parent
LAB = DEV.parent
FRAMEWORK_DEFAULT = re.compile(r'E2E_FRAMEWORK_DIR:-\$LAB/([^}"]+)\}')


def load_lanes(path=DEV / "lanes.json"):
    data = json.loads(pathlib.Path(path).read_text())
    lanes = data["lanes"]
    ids = [lane["id"] for lane in lanes]
    if len(ids) != len(set(ids)):
        raise ValueError("ids de lane repetidos")
    for lane in lanes:
        missing = set(lane["parents"]) - set(ids)
        if missing:
            raise ValueError(f"{lane['id']}: lanes pai inexistentes {sorted(missing)}")
    return data


def lane_source(lane, subdir, lab=LAB):
    return str((lab / lane["worktree"] / subdir).resolve())


def compose_problems(lanes, services, lab=LAB):
    found = []
    for lane in lanes:
        for service, subdir in lane["compose"].items():
            expected = lane_source(lane, subdir, lab)
            svc = services.get(service, {})
            # reservas builds the harness Node image; only app images build from the lane.
            context = svc.get("build", {}).get("context")
            mounts = [v.get("source") for v in svc.get("volumes", [])]
            if context not in (None, str(DEV)) and context != expected:
                found.append(f"{lane['id']}: compose {service} constrói {context}, esperado {expected}")
            if expected not in mounts:
                found.append(f"{lane['id']}: compose {service} não monta {expected}")
    return found


def runtests_problems(lanes, script_text):
    e2e = [lane for lane in lanes if lane["repo"] == "supreme-test-framework"]
    match = FRAMEWORK_DEFAULT.search(script_text)
    if not e2e:
        return []
    if not match:
        return ["run-tests.sh: padrão de E2E_FRAMEWORK_DIR não encontrado"]
    if match.group(1) != e2e[0]["worktree"]:
        return [f"e2e: run-tests.sh usa {match.group(1)}, esperado {e2e[0]['worktree']}"]
    return []


def git(worktree, *args):
    return subprocess.run(["git", "-C", str(worktree), *args],
                          capture_output=True, text=True).stdout.strip()


def local_checks(lane):
    found, warnings = [], []
    worktree = LAB / lane["worktree"]
    if not worktree.is_dir():
        return [f"{lane['id']}: worktree ausente {lane['worktree']}"], warnings, None
    branch = git(worktree, "branch", "--show-current")
    if branch != lane["local_branch"]:
        found.append(f"{lane['id']}: worktree em {branch or 'HEAD destacado'}, esperado {lane['local_branch']}")
    if git(worktree, "status", "--porcelain", "--untracked-files=no"):
        found.append(f"{lane['id']}: alterações rastreadas sem commit")
    upstream = git(worktree, "rev-parse", "--abbrev-ref", f"{lane['local_branch']}@{{upstream}}")
    if upstream != f"fork/{lane['fork_branch']}":
        found.append(f"{lane['id']}: upstream {upstream or 'ausente'}; o PR publica fork/{lane['fork_branch']}")
    push_default = git(worktree, "config", "push.default") or "simple"
    if lane["local_branch"] != lane["fork_branch"] and push_default != "upstream":
        found.append(f"{lane['id']}: push.default={push_default}; nomes diferentes exigem upstream")
    return found, warnings, git(worktree, "rev-parse", "HEAD")


def remote_checks(lane, head, data):
    found = []
    worktree = LAB / lane["worktree"]
    line = git(worktree, "ls-remote", "fork", f"refs/heads/{lane['fork_branch']}")
    fork_sha = line.split()[0] if line else ""
    result = subprocess.run(
        ["gh", "pr", "view", str(lane["pr"]), "--repo", f"{data['org']}/{lane['repo']}",
         "--json", "state,headRefOid,headRefName,baseRefName,headRepositoryOwner"],
        capture_output=True, text=True)
    if result.returncode != 0:
        return [f"{lane['id']}: gh falhou para PR #{lane['pr']}: {result.stderr.strip()}"], ""
    pr = json.loads(result.stdout)
    expected = {
        "state": "OPEN",
        "headRefName": lane["fork_branch"],
        "baseRefName": lane["base"],
        "owner": data["fork_owner"],
    }
    actual = {
        "state": pr["state"],
        "headRefName": pr["headRefName"],
        "baseRefName": pr["baseRefName"],
        "owner": pr["headRepositoryOwner"]["login"],
    }
    for key, value in expected.items():
        if actual[key] != value:
            found.append(f"{lane['id']}: PR #{lane['pr']} {key}={actual[key]}, esperado {value}")
    if not fork_sha:
        found.append(f"{lane['id']}: fork/{lane['fork_branch']} não existe")
    elif head and not (head == fork_sha == pr["headRefOid"]):
        found.append(f"{lane['id']}: divergência worktree {head[:7]} / fork {fork_sha[:7]} / PR {pr['headRefOid'][:7]}")
    return found, pr["headRefOid"]


def main(argv):
    offline = "--offline" in argv
    data = load_lanes()
    lanes = data["lanes"]
    problems, warnings = [], []

    services = json.loads(subprocess.run(
        ["docker", "compose", "config", "--format", "json"],
        cwd=DEV, check=True, capture_output=True, text=True).stdout)["services"]
    problems += compose_problems(lanes, services)
    problems += runtests_problems(lanes, (DEV / "run-tests.sh").read_text())

    for lane in lanes:
        found, warned, head = local_checks(lane)
        problems += found
        warnings += warned
        pr_head = ""
        if not offline and head:
            found, pr_head = remote_checks(lane, head, data)
            problems += found
        print(f"{lane['id']:8} {lane['repo']}#{lane['pr']:<3} "
              f"wt={(head or '-')[:7]} pr={(pr_head or '-')[:7]} {lane['worktree']}")

    for warning in warnings:
        print(f"   AVISO: {warning}")
    for problem in problems:
        print(f"   ✗ {problem}")
    mode = "local" if offline else "completo"
    if problems:
        print(f"=== CHECK LANES ({mode}): FAIL ({len(problems)}) ===")
        return 1
    print(f"=== CHECK LANES ({mode}): PASS ===")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
