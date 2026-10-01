# Harness LabTech — instruções para agentes

Leia `CLAUDE.md` antes de agir e preserve todo estado local existente.

- Trabalhe em português, um item por vez, com rastreabilidade.
- Aplicações, builds, instalações e suítes rodam em contêiner Docker Linux;
  nunca use runtime do macOS para validar a aplicação. Use
  `DOCKER_PLATFORM=linux/amd64` explicitamente (o harness atual fixa imagens
  nessa arquitetura) e confira `docker compose config` e `docker image inspect`.
- Compose e `run-tests.sh` devem resolver para os mesmos checkouts de API, Auth
  e Catálogo; o gate Web roda dentro do serviço Compose que monta a worktree
  selecionada. Manifestos e locks pertencem a cada repositório de aplicação.
- Código dos repositórios de aplicação só muda pelas lanes de `lanes.json`,
  seguindo `.claude/skills/pr-lane/SKILL.md` (Codex lê o arquivo; Claude o
  carrega como skill `pr-lane`).
- Preserve worktrees, alterações locais, volumes e dados. Antes de qualquer
  teste que grave em banco, valide um backup e use dados/contas isolados.
- O remoto canônico `origin` do harness é `Lucasdoreac/dev-local`; a branch
  `main` é seu alvo de integração. Não dependa de um repositório homônimo na
  organização.
- Só abra/atualize o PR depois de validar o escopo completo como conjunto
  coerente em Docker Linux. Não publique PR parcial nem deixe o resultado pronto
  apenas local. Não faça push direto/merge em `main`, deploy/produção, exclusões
  ou escritas em dados sem solicitação explícita.
- Não adicione funcionalidades ao ajustar o harness. Reutilize evidências
  válidas e registre no estado canônico do projeto qualquer mudança relevante.
