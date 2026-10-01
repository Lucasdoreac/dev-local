---
name: pr-lane
description: Procedimento obrigatório para alterar, validar ou publicar código dos repositórios de aplicação LabTech (python-services, shared-resources, interfaces-usuario, supreme-test-framework) por meio das lanes de PR declaradas em dev-local/lanes.json. Usar antes de editar uma worktree de PR, criar branch/worktree, dar push ao fork, abrir/atualizar PR na organização ou reorganizar branches.
---

# Lanes de PR

Uma lane é um PR aberto na organização (`LabTechUDF`), a worktree local onde ele
é editado e a branch do fork (`Lucasdoreac`) que ele publica.
`~/LABTECH/dev-local/lanes.json` é o único mapa; não guarde esse vínculo em
outro lugar. Caminhos de `lanes.json` são relativos a `~/LABTECH`.

## 1. Conferir antes de tocar

```bash
cd ~/LABTECH/dev-local && ./check-lanes.py
```

Só continue com PASS. Em FAIL, relate o item e pare: não "conserte" criando
branch, trocando upstream ou mudando a seleção do Compose sem decidir com o
usuário qual lado está certo.

## 2. Escolher a lane

- A mudança pertence a um PR existente: edite somente na `worktree` dessa lane,
  com caminho absoluto. Nunca em outra worktree com a mesma branch ou SHA.
- A mudança não pertence a nenhum PR: crie uma lane nova (seção 5).
- Nunca crie variante de uma lane existente (`-focused`, `-current-gate`,
  `-on-prNN`, `clean/...`). Se o PR precisa de outra forma, altere a própria lane.

## 3. Validar

Em Docker Linux `linux/amd64`, conforme o impacto, a partir de `~/LABTECH/dev-local`:
`./run-tests.sh python|internal|auth|frontend|framework|harness`; `e2e` só com as
regras de dados de `~/LABTECH/CLAUDE.md`. Código montado mudou: `docker compose
restart <serviço>`; lock/Dockerfile mudou: `docker compose up -d --build <serviço>`.
Confirmar regressão falhando antes e passando depois quando corrigir comportamento.

## 4. Publicar

```bash
git -C <worktree> commit ...    # autor é o usuário; sem trailers ou atribuição de IA
git -C <worktree> push          # upstream + push.default=upstream já apontam para o PR
cd ~/LABTECH/dev-local && ./check-lanes.py   # deve passar com o novo SHA
```

- Push publica no Staging: as lanes API #68, Auth #31, Catálogo #30 e Web #41
  são as branches dos serviços Staging no Render, com auto-deploy após CI verde
  no fork (`checksPass`). Só publique o que já passou na validação local.
- Nunca `--force` sem pedido explícito; nunca push para o remoto `origin` da
  organização, nem merge de PR da organização.
- Atualize a descrição do PR (`gh pr edit <n> --repo LabTechUDF/<repo>`) com o
  resultado final, versões anteriores→novas, validação do SHA atual e limites.

## 5. Lane nova

1. O pai é o head da lane de que a mudança depende, ou a base da organização.
   Prefira branch local com o mesmo nome da branch do fork.
2. Crie e configure:

   ```bash
   git -C ~/LABTECH/<repo> fetch origin
   git -C ~/LABTECH/<repo> worktree add .worktrees/<id> -b <branch> <SHA do pai>
   git -C ~/LABTECH/<repo> config extensions.worktreeConfig true
   git -C ~/LABTECH/<repo>/.worktrees/<id> config --worktree push.default upstream
   ```

3. Acrescente a lane a `lanes.json` (`id`, `repo`, `pr`, `base`, `parents`,
   `worktree`, `local_branch`, `fork_branch`, `compose`) por PR em
   `Lucasdoreac/dev-local`. Se ela entra na pilha, ajuste o Compose junto.
4. Depois da validação integrada: `git push -u fork <branch>` e PR do fork para
   a base da organização. Lane com pai ainda não mesclado carrega os commits do
   pai; diga isso no PR ou espere o merge do pai.

## 6. Depois do merge na organização

Retire a lane de `lanes.json`, aponte o Compose para a fonte que a substitui e
rebaseie as lanes filhas na nova base, validando cada uma. Reescrever uma branch
já publicada exige `--force-with-lease` e pedido explícito do usuário.

## Não fazer sem pedido explícito

Excluir branch, worktree, tag ou volume; merge ou deploy; escrita em dados.
Branches fora de `lanes.json` não são candidatas a merge: classifique-as antes
de agir.
