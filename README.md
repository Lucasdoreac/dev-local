# Runner de testes local

## Remoto e integração

O remoto atual `origin` é `https://github.com/Lucasdoreac/dev-local` e será a
referência para a integração na branch `main`. O repositório organizacional
`LabTechUDF/dev-local` ainda não existe; sua URL está preservada localmente como
`organization-origin-pending`. Quando a organização criar essa casa, ela volta a
ser o destino de PR organizacional. Até lá, trate o PR para `origin/main` como o
gate de revisão; não faça push direto nem merge em `main` sem pedido explícito.

## Compose local

`compose.yaml` define a pilha compartilhada; `compose.override.yaml` seleciona as
worktrees locais em revisão e as allowlists de desenvolvimento. O Docker Compose
carrega os dois arquivos automaticamente ao executar os comandos desta pasta.
Antes de subir serviços, confira os contextos e as plataformas com
`docker compose config`.

## Dono de cada configuração

- Cada aplicação mantém seu próprio manifesto e lock: `pyproject.toml` com
  `poetry.lock` em API/Auth/Catálogo/E2E e `package.json` com `yarn.lock` no Web.
- `compose.yaml` e o auto-carregado `compose.override.yaml` são a fonte da pilha
integrada, plataforma, mounts e seleção das worktrees. O runner deriva API,
Auth e Catálogo da configuração resolvida; `PYTHON_SERVICES_DIR`,
`AUTH_SERVICE_DIR` e `INTERNAL_APIS_DIR` selecionam a mesma fonte para Compose
e testes. Allowlist pessoal de desenvolvimento é injetada com
`DEV_AUTH_EMAIL_ALLOWLIST` e `DEV_VITE_AUTH_EMAIL_ALLOWLIST` pelo ambiente ou
arquivo `.env` local, que não deve ser versionado.
- Os `Dockerfile`s de API/Auth/Catálogo empacotam código para seus workflows de
  imagem. A configuração Render deve ser conferida separadamente.
  `dockerfiles/Dockerfile.poetry` atende a pilha local, que monta worktrees em
  runtime; `dockerfiles/Dockerfile.test-python` é o runner isolado de testes.
  `Dockerfile.reservas` fornece a base Node/Yarn para o Web montado. Esses
  Dockerfiles têm ciclos diferentes e não substituem os locks.
- `run-tests.sh` e os scripts deste diretório orquestram serviços e verificações;
  não são outro lugar para declarar dependências da aplicação.
- `audit-frontend.sh` é um utilitário manual legado: usa `npm`/`package-lock.json`
  e o checkout Web da raiz, enquanto o fluxo ativo usa Yarn e `yarn.lock`. Não é
  chamado pelo gate atual; fica como pendência de reparo ou aposentadoria, sem
  ser tratado como auditoria canônica do Web.

`./run-tests.sh all` roda API, Catálogo, Auth, build/test do Web pelo Compose e
checks unitários/dry-run do framework E2E. A pilha Compose deve estar ativa. O
E2E real no browser fica no alvo separado `e2e`, pois cria uma conta sintética
que precisa de banco isolado e backup validado.

Para isolar o Web: `./run-tests.sh frontend`. Isso executa `yarn build` seguido
de `yarn test` dentro do container `reservas`; não usa Node/Yarn do host.

## Runtime por gate

O runner lê as fontes de API, Auth e Catálogo da configuração resolvida pelo
Compose e usa os mesmos checkouts. `PYTHON_SERVICES_DIR`, `AUTH_SERVICE_DIR` e
`INTERNAL_APIS_DIR` podem selecionar outra worktree; a seleção também vale para
os mounts do Compose. Os locks atuais desses branches pedem Python 3.14.7. Para builds de
dependências nativas nessa versão, o runner prepara uma imagem reutilizável com
compilador, headers de `libffi`/OpenSSL e `pkg-config`; essas ferramentas ficam
fora das imagens de aplicação.

Exemplos para validar os branches de refresh:

```sh
PYTHON_SERVICES_DIR=~/LABTECH/python-services/.worktrees/approval-security-hardening \
PYTHON_SERVICES_TEST_IMAGE=labtech-dev-runner-python:3.14.7-amd64 \
./run-tests.sh python

INTERNAL_APIS_DIR=~/LABTECH/shared-resources/.worktrees/pr30-without-weekdays/internal_apis \
INTERNAL_APIS_TEST_IMAGE=labtech-dev-runner-python:3.14.7-amd64 \
./run-tests.sh internal
```

O runner constrói a imagem Python 3.14.7 na primeira validação que precisa
dela. Em rede restrita, configure `DEV_TEST_PROXY` conforme abaixo.

No perfil Colima atual, os containers resolvem os endereços IPv4 do PyPI, mas
essa rota externa não conclui a conexão. O Mac acessa o PyPI por IPv6. Para
baixar dependências durante os checks, use o encaminhador HTTPS local restrito
do próprio projeto.

Em um terminal, na raiz do repositório:

```sh
python3 dev-local/pypi-connect-proxy.py
```

Em outro terminal:

```sh
cd dev-local
DEV_TEST_PROXY=http://host.lima.internal:18888 ./run-tests.sh all
```

O encaminhador escuta somente no loopback do Mac e aceita `CONNECT` na porta
443 apenas para `pypi.org`, `files.pythonhosted.org` e `pypi.python.org`. Ele
não encaminha tráfego da aplicação e não altera dados ou volumes. Encerre-o
com `Ctrl-C` quando terminar os checks.

## E2E real no Chrome em Docker

Com a pilha Reservas ativa e a rede PyPI-only iniciada, rode:

```sh
cd ~/LABTECH/dev-local
DEV_TEST_PROXY=http://host.lima.internal:18888 \
E2E_FRAMEWORK_DIR=~/LABTECH/.worktrees/e2e-pr3-without-offers \
./run-tests.sh e2e
```

O runner inicia temporariamente o frontend E2E, `selenium/standalone-chrome`
e o Python/Behave como containers na rede Docker do Compose. O browser e os
testes encontram o frontend pelo alias efêmero da execução e a API pelo alias
`api`; não usam a porta publicada no Mac, `127.0.0.1` ou o Chrome instalado
no host. O endereço publicado da aplicação continua útil para uma pessoa abrir
o frontend no navegador e conferir o fluxo manualmente.

Cada execução usa um e-mail sintético único e remove somente os documentos
Mongo e as chaves Redis desse endereço ao terminar, inclusive quando os
cenários falham. Os containers do frontend E2E, Chrome e runner são removidos
ao final; os serviços e volumes da aplicação permanecem. O proxy PyPI é
necessário apenas quando a rede Docker não consegue baixar dependências
diretamente.
