# Regras permanentes do harness

Agentes Claude também devem ler `AGENTS.md`; Codex e Claude seguem o mesmo
contrato.

O propósito deste repositório é a pilha integrada local de Reservas. `compose.yaml`
e seu override selecionam serviços, plataformas, fontes montadas e volumes.
`run-tests.sh` deriva API/Auth/Catálogo do Compose resolvido e executa build/test
Web dentro do serviço que monta a worktree selecionada; mantenha esses vínculos
ao alterar worktrees ou comandos; `lanes.json` é o mapa PR ↔ worktree ↔ fork e
`./check-lanes.py` deve passar antes de editar ou publicar uma lane. Cada aplicação mantém seu próprio manifesto e
lock. Os Dockerfiles de API/Auth/Catálogo são usados por seus workflows de imagem;
confira a configuração Render separadamente. Os Dockerfiles deste repositório
servem à pilha de desenvolvimento e ao runner de testes.

Valide sempre em Docker Linux com `DOCKER_PLATFORM=linux/amd64`, alvo fixado nas
imagens atuais. Inspecione a
configuração e os mounts efetivos antes de subir serviços. Preserve volumes e
backups. Testes que gravem no banco exigem backup validado e dados isolados.

O remoto canônico `origin` do harness é `Lucasdoreac/dev-local`; `main` é o alvo
de integração. Não dependa de um repositório homônimo na organização.

Antes de abrir/atualizar PR, integre e valide a pilha e os fluxos pertinentes
como um todo coerente. Não abra PR parcial; não faça merge, deploy/produção,
exclusões nem escritas em dados sem solicitação explícita. Envie código pronto
ao `origin` por branch de revisão, sem deixá-lo apenas local; não faça push
direto para `main`.
