#!/usr/bin/env python3
"""Copy the Staging API's Brevo settings into this local harness .env.

This helper only reads Render. It never updates a Render service, deploys, or
copies database, SMTP, auth, or recipient settings. Secrets are never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
SERVICE_NAME = "reservas-staging-api"
API_ROOT = "https://api.render.com/v1"
SYNC_MAP = {
    "BREVO_API_KEY": "DEV_BREVO_API_KEY",
    "BREVO_SENDER_EMAIL": "DEV_BREVO_SENDER_EMAIL",
    "BREVO_SENDER_NAME": "DEV_BREVO_SENDER_NAME",
    "EMAIL_DRY_RUN": "DEV_EMAIL_DRY_RUN",
}
LOCAL_RECIPIENT_KEYS = ("DEV_APPROVAL_EMAIL", "DEV_EMAIL_RECIPIENT_ALLOWLIST")


class SyncError(Exception):
    pass


def render_token() -> str:
    token = os.environ.get("RENDER_API_KEY", "").strip()
    if token:
        return token

    config = Path.home() / ".render" / "cli.yaml"
    if not config.is_file():
        raise SyncError("Render CLI não está autenticado: ~/.render/cli.yaml não encontrado.")
    ruby = subprocess.run(
        [
            "ruby",
            "-ryaml",
            "-e",
            'd=YAML.safe_load(File.read(ARGV.fetch(0)), aliases: false); '
            'print(d.dig("api", "key").to_s)',
            str(config),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if ruby.returncode != 0 or not ruby.stdout.strip():
        raise SyncError("Não foi possível ler a credencial local do Render CLI.")
    return ruby.stdout.strip()


def render_get(path: str, token: str):
    request = Request(
        f"{API_ROOT}{path}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise SyncError(
                f"Render negou leitura (HTTP {exc.code}); confira o acesso somente de leitura."
            ) from None
        raise SyncError(f"Render API respondeu HTTP {exc.code}.") from None
    except (URLError, TimeoutError, json.JSONDecodeError):
        raise SyncError("Não foi possível ler as variáveis do Render agora.") from None


def list_items(payload, wrapper: str) -> list[dict]:
    if not isinstance(payload, list):
        raise SyncError("Formato inesperado na resposta de lista do Render.")
    items = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        item = row.get(wrapper, row)
        if isinstance(item, dict):
            items.append(item)
    return items


def fetch_staging_env(token: str) -> dict[str, str]:
    services = list_items(render_get("/services?limit=100", token), "service")
    matches = [service for service in services if service.get("name") == SERVICE_NAME]
    if len(matches) != 1 or not matches[0].get("id"):
        raise SyncError(f"Esperava exatamente um serviço Render chamado {SERVICE_NAME}.")

    service = matches[0]
    if service.get("type") not in (None, "web_service"):
        raise SyncError("O serviço Staging encontrado não é um Web Service.")
    detail = render_get(f"/services/{quote(service['id'], safe='')}", token)
    if not isinstance(detail, dict) or detail.get("name") != SERVICE_NAME:
        raise SyncError("A identidade do serviço Staging não pôde ser confirmada.")
    linked_groups = detail.get("envGroupIds") or detail.get("envGroups") or []
    if linked_groups:
        raise SyncError(
            "O API Staging tem grupos de ambiente vinculados; esta sincronização cobre apenas variáveis diretas."
        )

    rows = list_items(
        render_get(f"/services/{quote(service['id'], safe='')}/env-vars?limit=100", token),
        "envVar",
    )
    if len(rows) >= 100:
        raise SyncError("A lista de variáveis atingiu o limite de uma página; sincronização cancelada.")
    remote = {row.get("key"): row.get("value") for row in rows if isinstance(row.get("key"), str)}

    if str(remote.get("EMAIL_PROVIDER", "")).strip().casefold() != "brevo":
        raise SyncError("O API Staging não declara EMAIL_PROVIDER=brevo.")
    if str(remote.get("EMAIL_DRY_RUN", "")).strip().casefold() != "false":
        raise SyncError("O envio real não está habilitado no API Staging; nada foi sincronizado.")
    selected = {source: remote.get(source) for source in SYNC_MAP}
    if any(not isinstance(value, str) or not value for value in selected.values()):
        raise SyncError("Falta uma variável Brevo necessária no API Staging.")
    if "\n" in selected["BREVO_API_KEY"] or "\r" in selected["BREVO_API_KEY"]:
        raise SyncError("A chave Brevo tem formato inesperado.")
    return selected


def unquote_env(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        quote_char = value[0]
        value = value[1:-1]
        if quote_char == '"':
            value = value.replace("\\n", "\n").replace("\\r", "\r").replace('\\"', '"').replace("\\\\", "\\")
        else:
            value = value.replace("\\'", "'")
        return value
    return re.split(r"\s+#", value, maxsplit=1)[0].strip()


def read_env(path: Path) -> tuple[list[str], dict[str, str], dict[str, int]]:
    if not path.is_file():
        raise SyncError(f"Arquivo local não encontrado: {path}")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    values: dict[str, str] = {}
    locations: dict[str, int] = {}
    for index, line in enumerate(lines):
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*?)(?:\r?\n)?$", line)
        if not match:
            continue
        key, raw = match.groups()
        if key in values:
            raise SyncError(f"A variável {key} aparece mais de uma vez em {path.name}.")
        values[key] = unquote_env(raw)
        locations[key] = index
    return lines, values, locations


def quote_env(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise SyncError("Uma variável selecionada contém quebra de linha; arquivo não alterado.")
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def check_local_recipient(values: dict[str, str]) -> None:
    approval, allowlist = (values.get(key, "").strip() for key in LOCAL_RECIPIENT_KEYS)
    recipients = [part.strip() for part in allowlist.split(",") if part.strip()]
    if not approval or len(recipients) != 1 or recipients[0].casefold() != approval.casefold():
        raise SyncError(
            "A allowlist local precisa conter apenas o endereço de DEV_APPROVAL_EMAIL; nenhuma variável foi alterada."
        )
    if "@" not in approval:
        raise SyncError("DEV_APPROVAL_EMAIL local não é um endereço de email válido.")


def env_is_gitignored(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(path.parent), "check-ignore", "-q", "--", path.name],
            check=False,
            capture_output=True,
        )
    except OSError:
        return False
    return result.returncode == 0


def write_atomic(path: Path, content: str) -> None:
    fd, temporary_name = tempfile.mkstemp(prefix=".env-render-sync-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    finally:
        if temporary.exists():
            temporary.unlink()


def sync(env_path: Path, apply: bool) -> None:
    env_path = env_path.expanduser().resolve()
    if env_path.name != ".env" or not env_is_gitignored(env_path):
        raise SyncError("Destino precisa ser um arquivo .env ignorado pelo Git.")

    lines, local, locations = read_env(env_path)
    check_local_recipient(local)
    remote = fetch_staging_env(render_token())
    updates = {SYNC_MAP[source]: value for source, value in remote.items()}

    new_lines = list(lines)
    for key, value in updates.items():
        line = f"{key}={quote_env(value)}\n"
        if key in locations:
            old = new_lines[locations[key]]
            ending = "\r\n" if old.endswith("\r\n") else "\n" if old.endswith("\n") else ""
            new_lines[locations[key]] = line.rstrip("\n") + ending
        else:
            if new_lines and not new_lines[-1].endswith(("\n", "\r")):
                new_lines[-1] += "\n"
            new_lines.append(line)

    if apply:
        write_atomic(env_path, "".join(new_lines))
        _, verified, _ = read_env(env_path)
        check_local_recipient(verified)
        if any(verified.get(key) != value for key, value in updates.items()):
            raise SyncError("A conferência posterior da configuração local falhou.")
        print(f"Sincronizadas {len(updates)} variáveis para {env_path}; valores ocultos.")
    else:
        print(
            f"Prévia: {len(updates)} variáveis Brevo do {SERVICE_NAME} seriam atualizadas em {env_path};"
            " valores ocultos. Use --apply para gravar."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
        help="Arquivo .env ignorado pelo Git (padrão: .env deste harness).",
    )
    parser.add_argument("--apply", action="store_true", help="Grava as variáveis selecionadas no .env local.")
    args = parser.parse_args()
    try:
        sync(args.env_file, args.apply)
    except SyncError as exc:
        print(f"Erro: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
