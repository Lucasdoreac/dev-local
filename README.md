# Runner de testes local

## Remoto e integração

O remoto atual `origin` é `https://github.com/Lucasdoreac/dev-local` e será a
referência para a integração na branch `main`. Este repositório pessoal é a casa
remota do harness; não há dependência de um repositório homônimo na organização.
O PR #1 para `origin/main` é o gate de revisão; não faça push direto nem merge
em `main` sem pedido explícito.

Nos quatro repositórios de aplicação o fluxo é outro: o código é publicado no
fork pessoal (remoto `fork`) e vai de lá como PR para o `origin` da organização.
O `dev-local` não tem PR organizacional; o remoto `organization-origin-pending`
apenas preserva a URL inacessível.

## Lanes de PR

`lanes.json` é o mapa único de cada PR aberto na organização: repositório,
número, base, PRs pai, worktree local, branch local e branch do fork que o PR
publica. Mude código de um PR apenas na worktree da sua lane; trabalho novo vira
uma lane nova empilhada sobre o pai, não uma branch variante.
`./check-lanes.py` confere se worktree, branch do fork e head do PR têm o mesmo
SHA e se Compose e `run-tests.sh` usam essas worktrees (`--offline` pula
GitHub). Cada worktree de lane tem upstream `fork/<branch do PR>` e
`push.default=upstream` só nela (`git config --worktree`), então `git push`
simples atualiza o PR certo; o check falha se isso mudar. O procedimento
completo (conferir, editar, validar, publicar, lane nova, pós-merge) está em
`.claude/skills/pr-lane/SKILL.md`, ligado em `~/LABTECH/.claude/skills/pr-lane`.
`notebook-sync.py` também lê `lanes.json`: uma fonte do caderno por lane (em
repo com várias lanes, só as pastas de cada serviço), e o hook de push
sincroniza apenas a lane cuja branch do fork recebeu o commit. Lane com `"notebook": false`
(por exemplo, só o Dockerfile sobre outra lane) não vira fonte do caderno.

## Advisories e o limite da main

`./run-tests.sh advisories` roda `check-advisories.py` no runner Docker: primeiro
um self-test (o OSV precisa acusar pinos vulneráveis conhecidos), depois uma
consulta OSV de todas as versões travadas nas locks de cada lane (só as locks que
a lane altera; em `shared-resources` cada lane traz a lock do serviço irmão como
está na main da org). Sai 1 com achado e 2 se a consulta falhar. O LaunchAgent
roda a checagem a cada 3 h e notifica achados; sem Docker, só registra no log.

Advisory em pacote marcado `[BLOQUEADO PELO PAI]` (faixa do pai impede o bump):

1. Confirmar o advisory (OSV/GHSA), versão corrigida, alcance no código e se é
   runtime ou só build; registrar em `reports/VULNERABILIDADES.csv`.
2. Web: fixar a versão corrigida com `resolutions` no `package.json` da lane Web
   e `yarn install`; Python: preferir versão corrigida aceita pelo pai; se não
   existir, fork corrigido do pai em lane própria, nunca editar o lock à mão.
3. Validar o conjunto em Docker `linux/amd64` (suítes, build, smoke e E2E real)
   e publicar pela skill `pr-lane`, dizendo no PR que excede a faixa do pai.

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
  Alpine (Auth/Catálogo, lanes `auth` e `catalog`): `TEST_LIBC=musl ./run-tests.sh auth|internal`
  usa o runner `Dockerfile.test-python-musl` (cache e tag próprios); `compose.alpine.yaml`
  sobe as imagens de produção dessas lanes na pilha (`COMPOSE_FILE=compose.yaml:compose.override.yaml:compose.alpine.yaml`).
- `run-tests.sh` e os scripts deste diretório orquestram serviços e verificações;
  não são outro lugar para declarar dependências da aplicação.
- `audit-frontend.sh` é um utilitário manual legado: usa `npm`/`package-lock.json`
  e o checkout Web da raiz, enquanto o fluxo ativo usa Yarn e `yarn.lock`. Não é
  chamado pelo gate atual; fica como pendência de reparo ou aposentadoria, sem
  ser tratado como auditoria canônica do Web.

`./run-tests.sh all` roda os testes do harness em um container Linux isolado,
API, Catálogo, Auth, build/test do Web pelo Compose e checks unitários/dry-run
do framework E2E. A pilha Compose deve estar ativa. Para rodar só os testes do
harness, use `./run-tests.sh harness`; o runner inclui Docker CLI e Compose
pinados e não recebe o socket do daemon. O E2E real no browser fica no alvo
separado `e2e`, pois cria uma conta sintética que precisa de banco isolado e
backup validado.

Para isolar o Web: `./run-tests.sh frontend`. Isso executa `yarn build` seguido
de `yarn test` dentro do container `reservas`; não usa Node/Yarn do host.

## Runtime por gate

O runner lê as fontes de API, Auth e Catálogo da configuração resolvida pelo
Compose e usa os mesmos checkouts. `PYTHON_SERVICES_DIR`, `AUTH_SERVICE_DIR` e
`INTERNAL_APIS_DIR` podem selecionar outra worktree; a seleção também vale para
os mounts do Compose. Os locks atuais desses branches pedem Python 3.14.8. Para builds de
dependências nativas nessa versão, o runner prepara uma imagem reutilizável com
compilador, headers de `libffi`/OpenSSL e `pkg-config`; essas ferramentas ficam
fora das imagens de aplicação.

Exemplos para validar os branches de refresh:

```sh
PYTHON_SERVICES_DIR=~/LABTECH/python-services/.worktrees/approval-security-hardening \
PYTHON_SERVICES_TEST_IMAGE=labtech-dev-runner-python:3.14.8-amd64 \
./run-tests.sh python

INTERNAL_APIS_DIR=~/LABTECH/shared-resources/.worktrees/pr30-without-weekdays/internal_apis \
INTERNAL_APIS_TEST_IMAGE=labtech-dev-runner-python:3.14.8-amd64 \
./run-tests.sh internal
```

O runner constrói a imagem Python 3.14.8 na primeira validação que precisa
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

### Fontes alternativas e Web estático

- `RESERVAS_WEB_DIR` aponta o serviço `reservas` (e o E2E) para outra worktree do Web, como
  `PYTHON_SERVICES_DIR`, `AUTH_SERVICE_DIR` e `INTERNAL_APIS_DIR` fazem com os outros serviços
  (por exemplo, a worktree de integração). Sem a variável vale a worktree da lane do #41.
- `E2E_WEB_MODE=static ./run-tests.sh e2e` faz o build do Web e o serve com `serve-static.py`
  em vez do servidor de desenvolvimento do Vite. Na VM Colima de 4 GB o dev server junto do
  Chrome estoura o renderer (timeout ao abrir a página); o servidor estático quase não custa
  memória. Padrão (`dev`) inalterado.
- `E2E_BEHAVE_ARGS` repassa argumentos ao `behave` no E2E (vazio por padrão, comportamento
  inalterado): `E2E_BEHAVE_ARGS="--tags=drafts"` roda os cenários que só existem nos Drafts do Web
  (o `behave.ini` do framework os ignora por padrão). `E2E_MONGO_URI` (padrão
  `mongodb://mongo:27017`) só importa para os cenários que semeiam dados, e a semeadura recusa
  qualquer host que não seja o Mongo local.
- Só o código montado mudou (API, Auth, Catálogo ou Web em outra worktree, locks iguais):
  `docker compose up -d --no-build <serviço>` (ou `restart`) basta; `--build` com a VM
  disputada por outras sessões pode demorar dezenas de minutos sem necessidade.

### Modo resiliência dos Drafts (cenários que param a API/o Auth ou usam duas abas)

Opt-in; sem as variáveis o E2E é o de sempre (sem socket do Docker, sem parar serviço). Roda com
`E2E_BEHAVE_ARGS="--tags=drafts"` (ou `--tags=drafts --tags=rooms`, um cenário só) e o Web estático:

```sh
cd ~/LABTECH/dev-local
E2E_WEB_MODE=static RESERVAS_WEB_DIR=<worktree do Web> \
E2E_FRAMEWORK_DIR=<worktree do framework> \
E2E_BEHAVE_ARGS="--tags=drafts" \
E2E_ALLOW_SERVICE_CONTROL=1 \
E2E_TREAT_ORIGIN_AS_SECURE=http://labtech-e2e-web:3000 \
./run-tests.sh e2e
```

- `E2E_ALLOW_SERVICE_CONTROL=1` monta o socket do Docker **só no runner do E2E** e deixa o framework parar e
  religar `api` e `auth` (nenhum outro serviço) do projeto Compose `E2E_COMPOSE_PROJECT` (padrão: o projeto
  da rede `labtech-dev_default`). Cada cenário religa o que parou, mesmo quando falha.
- `E2E_TREAT_ORIGIN_AS_SECURE=<origem do Web>` faz o Chrome tratar essa origem HTTP como segura; sem isso
  `navigator.locks` não existe e o cenário das duas abas (#47) mede o Web sem o lock. Production é HTTPS.
- A API da pilha precisa servir `/auth/logout` (cenário do Sair): suba `api` e `auth` das worktrees de
  integração, com `PYTHON_SERVICES_DIR=<integration-api> AUTH_SERVICE_DIR=<integration-auth>/auth_service
  docker compose up -d --no-build api auth`, e volte ao padrão ao fim (`up -d --no-build api auth` sem as variáveis).
- Antes: backup validado do Mongo (`mongodump --archive --gzip` e `mongorestore --dryRun`). Entre execuções: o
  Auth aceita 3 pedidos de link por e-mail a cada 15 min e conta falhas de validação; apague as chaves
  `flask_cache_rl:*` do Redis local (`redis-cli --scan --pattern 'flask_cache_rl:*'`, só na pilha local) e
  confirme que `authentications` não tem registro do e-mail sintético, ou o runner aborta.
- Resíduo conhecido: o cenário que envia o pedido gera um PDF; o documento em `pdfs` é removido pelo framework,
  mas o objeto no MinIO local (`labtech/reservation-pd…`) fica. Não afeta o Mongo nem outros projetos.

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
