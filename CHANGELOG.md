# Changelog

## Não lançado

### Novo visual
- **Barra lateral** no lugar da faixa colorida do topo: logo e nome do workspace, busca ("Buscar", atalho `/`),
  Playbooks, Templates e Administração; perfil e tema no rodapé. Em telas estreitas vira gaveta.
- **Sistema de design minimalista:** fonte **Inter** embutida (`assets/`, licença OFL, sem chamar serviços externos),
  paleta neutra, um único acento, sem gradientes, sombras e raios menores, botões principais monocromáticos.
- **Aparência** reduzida ao essencial: nome do workspace e logo (prévia nos temas claro e escuro). A cor primária,
  o título e o subtítulo da página inicial e o fundo da logo deixaram de ser configuráveis; os valores antigos no
  banco são ignorados. Cada usuário escolhe tema claro ou escuro.
- Página inicial e páginas internas com menos texto: sem faixa de título, sem dicas fixas nas barras dos editores.
- Confirmações dentro da aplicação no lugar do `confirm()` do navegador (que em navegadores embutidos não aparecia
  e fazia botões como "Descartar" parecerem quebrados).
- Arquivos estáticos de `assets/` (a fonte) com cache no navegador.

### Novidades
- **Exportar o fluxograma em JPEG** (alta resolução, 2x), além de SVG.
- **Ícones do Iconoir** no lugar de todos os emojis e símbolos da interface (botões, abas, menus, editores, documentação
  interna). Os ícones ficam embutidos em `icons.js` (MIT), sem depender de CDN.
- **Pontos de dobra nas setas:** com a seta selecionada, o **+** no meio de cada trecho (ou "Adicionar ponto") cria um
  ponto, que se arrasta; dois cliques (ou o ✕ da lista no painel) removem.
- **Rota fixa:** lados de saída/entrada e pontos de dobra não mudam mais ao mover as caixas. Liga sozinha ao escolher
  um lado ou mexer num ponto; "Voltar à rota automática" desfaz. Gravada no `.drawio` (`medusaLock=1`) e no Mermaid
  (`%% @route … lock`).
- **Modo Markdown** no editor de documento: o documento inteiro como texto, com barra de formatação, prévia ao vivo
  (mesmo parser do servidor), imagens por botão, colar ou arrastar, e alternância com o modo Visual a qualquer momento.
- **Alterações em Produção** pedem o tipo da atualização e a descrição: **Minor** soma 1 depois do ponto (2.3 → 2.4),
  **Major** soma 1 antes do ponto (2.3 → 3.0). Vale para documento, fluxograma e restauração de versão; a descrição
  vai para o histórico e para a auditoria.
- **Playbook com duas visualizações:** Fluxograma e Documentação. Fases, passos e ramos já estão na documentação, que
  ganhou índice com subseções; a busca e links antigos (`/fases`, `/ramos`) levam ao trecho, com destaque.

### Correções
- **Trocar de aba durante a edição perdia o conteúdo**, qualquer que fosse a resposta ao aviso. Agora o editor guarda
  um rascunho por aba: não há aviso ao trocar, a aba mostra um ponto de "não salvo" e as alterações voltam ao reabrir.
  Só fechar a aba (com confirmação), descartar ou salvar apagam o rascunho.
- Mover uma caixa voltava os lados das setas para "Automático".
- O menu do perfil não fechava ao escolher uma opção.

### Interface
- "Docs" saiu da barra superior: fica no menu do perfil, junto de Templates, Administração, Trocar senha e Sair.
- Página inicial sem playbooks (em qualquer filtro) mostra só a opção de criar, sem a frase "Nenhum playbook disponível".
- Busca com ícone, controles segmentados (Visual/Markdown, Visual/Código), botões só de ícone com rótulo acessível.
- **Fundo da logo** (Administração → Aparência → Logo): **branco** (padrão, como antes) ou **transparente**. Com
  transparente, logos PNG/SVG sem fundo ficam direto sobre a faixa colorida do topo; o quadro da logo atual mostra as
  áreas transparentes com um quadriculado.

## 2.1.0 — 2026-10-05

### Novidades
- **Imagens na documentação.** No editor de documento: **＋ Imagem**, colar (Ctrl+V) ou arrastar para a seção.
  PNG, JPG, WEBP ou GIF até 3 MB, com legenda opcional. Os arquivos ficam em `imagens/` na pasta do playbook, com
  nome pelo conteúdo (nunca sobrescritos: versões antigas continuam mostrando as imagens que tinham), e entram no
  `.md` como Markdown comum. Na leitura, clique amplia. O servidor confere o tipo real do arquivo e aplica as mesmas
  permissões do playbook (visualizador não vê imagens de playbooks em Desenvolvimento).
- Exportações com imagens: o pacote `.medusa.md` leva as imagens (e a importação as grava), o HTML e a impressão as
  embutem no arquivo, e o Markdown vira `.zip` com a pasta `imagens/`.
- **Resetar aplicação** (Administração, só administrador): volta a instalação ao estado de recém-configurada, com
  confirmação digitando `RESETAR`, como na exclusão de playbook. Opcionalmente restaura configurações, remove os
  demais usuários e apaga a auditoria. Tudo vai para `data/lixeira/reset__<data-hora>/`, com cópia do banco.
- **Página inicial:** além dos cartões, **lista grande** e **lista pequena**; a escolha fica salva por usuário.

### Melhorias
- **Aparência** reorganizada em quatro cartões simétricos (Identidade, Logo, Página inicial, Prévia), com campos de
  cor alinhados, rodapé de ações na mesma altura e prévia do título e subtítulo da página inicial.
- A aba **Versões** do playbook perdeu o ícone, no padrão das demais abas.
- Ações destrutivas (excluir, resetar) usam vermelho fixo, independente da cor da marca.
- Administração não transborda mais na horizontal em telas estreitas.

## 2.0.0 — 2026-10-05

### Novidades
- **Versionamento automático.** Gravações em Desenvolvimento e Homologação somam 1 depois do ponto (0.1 → 0.2);
  publicar em Produção, ou alterar um playbook publicado, gera a próxima versão cheia (0.4 → 1.0, 1.0 → 2.0).
  Republicar sem alteração mantém o número.
- **Histórico de versões** (aba Versões): cada gravação guarda o conteúdo completo. É possível ler qualquer versão
  como documentação completa, com o fluxograma clicável daquele momento (e baixar em HTML ou imprimir), comparar
  duas versões (documento linha a linha e caixas/setas do fluxograma) e restaurar uma versão (editores).
- **Encaminhamento de logs em JSON** (Administração → Logs e retenção): HTTP/HTTPS, syslog (RFC 5424, UDP/TCP) e
  arquivo JSON Lines, no padrão Elastic Common Schema, com fila em segundo plano, tentativas, teste e status.
  Exportação da auditoria em JSON Lines.
- **Retenção de logs:** auditoria guardada por 30 dias (ajustável), com limpeza automática.
- **Login único (SSO) opcional** por OpenID Connect: authorization code + PKCE, state e nonce, ID token validado pela
  assinatura RS256 (JWKS), emissor, audiência e validade. Perfis por grupos do provedor, criação no primeiro login ou
  só pré-cadastrados, domínios permitidos, login por senha para todos ou só para administradores.
- Usuários com autenticação **local** ou **SSO**; logins com `@` e até 80 caracteres.
- `MEDUSA_TRUST_PROXY=1`: IP real do usuário atrás de proxy reverso (auditoria e bloqueio de login).
- Auditoria registra o IP de origem de cada ação e a versão gerada em cada gravação.

### Correções
- **Logo:** a imagem agora se ajusta ao espaço do cabeçalho em qualquer proporção (larga, alta, sem tamanho
  definido ou muito grande). Antes, `max-width/max-height` em porcentagem dentro de uma caixa de largura automática
  não tinham referência e a logo não encolhia.

### Banco de dados
- Migração automática para o esquema v3: colunas `auth` e `sso_subject` em `users`, tabelas `sso_states` e
  `pb_versions`. Instalações anteriores são migradas ao iniciar; playbooks existentes ganham um registro inicial
  no histórico na primeira alteração.

## 1.0.0 — 2026-10-03

Primeira versão open source: playbooks com documento e fluxograma ligados, editores sem código, ramos
sincronizados, templates com times e tags, perfis, ciclo de vida, auditoria, exportação/importação, white label e Docker.
