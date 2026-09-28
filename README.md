# Runner de testes local

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
E2E_FRAMEWORK_DIR=~/LABTECH/supreme-test-framework/.worktrees/e2e-dependencies-focused \
./run-tests.sh e2e
```

O runner inicia temporariamente `selenium/standalone-chrome:4.48.0-20260905`
em host networking para o browser acessar os links locais em `127.0.0.1`. O
Python/Behave roda em outro container na rede do Compose. Cada execução usa um
e-mail sintético único e remove somente os documentos Mongo e as chaves Redis
desse endereço ao terminar, inclusive quando os cenários falham. O Chrome é
removido ao final; os volumes da aplicação permanecem.
