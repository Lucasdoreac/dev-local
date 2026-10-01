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
- Preserve worktrees, alterações locais, volumes e dados. Antes de qualquer
  teste que grave em banco, valide um backup e use dados/contas isolados.
- O remoto atual `origin` é o repositório pessoal `Lucasdoreac/dev-local`; a
  branch `main` é seu alvo de integração e o PR para ela é o gate. A URL
  organizacional fica preservada como `organization-origin-pending` até existir
  `LabTechUDF/dev-local`; então os PRs organizacionais voltam a ser o destino.
- Só abra o PR depois de integrar e validar o escopo completo como conjunto
  coerente em Docker Linux. Não publique PR parcial nem deixe o resultado pronto
  apenas local. Não faça push direto/merge em `main`, deploy/produção, exclusões
  ou escritas em dados sem solicitação explícita.
- Não adicione funcionalidades ao ajustar o harness. Reutilize evidências
  válidas e registre no estado canônico do projeto qualquer mudança relevante.
