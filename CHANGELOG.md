# Changelog

## 3.2.0 — 2026-10-30

### Sugestões de alteração
- Quem lê seleciona um trecho e clica em **Sugerir alteração** (texto novo ou só comentário), ou usa o **+** do título
  da seção para propor um acréscimo. Botão **Sugestões** no topo do documento, contagem por seção e nos cartões
  (para quem edita).
- Quem edita **aceita e aplica** (nova versão do tipo "Sugestão aceita"; em Produção pede Minor/Major), **marca como
  aceita** ou **recusa** com motivo; quem sugeriu pode retirar. Se o texto mudou e o trecho não é mais achado (ou
  aparece mais de uma vez), aplicar é recusado e a sugestão continua aberta.
- Permissão nova "Sugerir alterações" (`<tipo>.suggest`). **Migração v6** (automática, com cópia do banco): tabela
  `suggestions` e a permissão entra nas roles do sistema Editor e Visualizador; roles criadas por você não mudam.

### Correções e ajustes
- **Novo playbook** listava templates de runbook e documento; agora só os de playbook.
- **Logo**: com logo, ela aparece sozinha em cima e o nome do workspace embaixo, menor (logos de proporções diferentes
  não ficavam alinhadas com o nome ao lado). No login, o mesmo.
- **"Papéis" passou a se chamar "Roles"** na interface, na ajuda e nas mensagens (`#/admin/papeis` redireciona para
  `#/admin/roles`). Os nomes das ações na auditoria (`papel_criado`…) não mudam.
- **Pastas**: as subpastas começam expandidas (uma pasta recém-criada não "sumia" mais dentro da pai recolhida); em
  telas estreitas a árvore começa aberta; ícone de pasta; menu ⋯ legível e visível em telas de toque; ao excluir uma
  pasta, o destino não oferece mais as subpastas dela (o servidor recusava); listas não reaproveitam mais respostas
  em cache de antes de reiniciar o servidor.

## 3.1.0 — 2026-10-30

### Ligações entre documentos
- O ID de outro documento no texto ou numa caixa do fluxograma vira uma ligação. No fim da documentação, o painel
  **Ligações** mostra quem o documento **cita** e por quem é **referenciado por**, só com o que você pode ver
  (`GET /api/doc/{id}/links`). As ligações ficam no cache (e no cache em disco), sem custo extra na leitura.

### Verificação de pendências
- Selo de **pendências** no topo do documento, para quem pode editar (`GET /api/doc/{id}/lint`): citação a documento
  inexistente e, nos playbooks, caixa sem "ao clicar", passo sem caixa, ID de passo repetido e ramo só no documento
  ou só no fluxograma. A lista leva ao trecho; não impede salvar nem publicar.

## 3.0.0 — 2026-10-30

Reúne as betas 3.0.0-beta.1 a beta.4 (abaixo) e fecha a versão:

### Documentos
- Item **Documentos** no menu lateral, com a mesma biblioteca (pastas, busca, filtros por campo) e o template
  **Documento padrão** (Categoria e Público). Sem fluxograma e sem aprovador.
- Status com nomes próprios para documentos: **Rascunho**, **Em revisão** e **Publicado** (só na interface: o valor
  gravado continua Desenvolvimento, Homologação e Produção).

### Ajuda
- A antiga "Documentação" do menu do perfil passou a se chamar **Ajuda** (rota `#/ajuda`; links e abas antigas com
  `#/docs` redirecionam), para não confundir com o novo item **Documentos**. Novos tópicos: Runbooks, Documentos e
  Pastas.

### Atualização a partir da 2.x
- O banco migra sozinho (v3 → v5) com cópia automática antes; os playbooks não mudam de lugar nem de conteúdo. A 2.2
  continua abrindo o banco migrado (rollback). Veja o passo a passo em INSTALACAO-DOCKER.md (Podman incluído).
- Mudanças de comportamento: aprovador diferente de quem edita (ligado por padrão) e importar substituindo exige a
  permissão de excluir.

## 3.0.0-beta.4 — 2026-10-30

### Runbooks na interface
- Item **Runbooks** no menu lateral (para quem pode ver runbooks), com a biblioteca: árvore de pastas (contagens,
  "Todos" e "Sem pasta", ações por pasta, arrastar documentos e pastas, navegação por teclado), busca, filtros
  gerados pelos campos do template com contagens, cartões ou lista e "Carregar mais". Em telas estreitas a árvore
  vira um painel recolhível.
- **Novo runbook**: template, nome, ID sugerido, pasta e campos do template. Os campos aparecem como etiquetas no
  topo do runbook.
- Página do runbook: Documentação · Fluxograma (se houver) · Versões; **Adicionar fluxograma** cria o `.drawio` ao
  salvar; **Mover** troca a pasta. Exportação sem fluxograma esconde draw.io, Mermaid, SVG e JPEG; a comparação de
  versões esconde o bloco do fluxograma quando não há.
- `RB-00` e `DOC-00` em qualquer texto viram links (riscados quando o documento não existe para o seu papel).
- Importar runbooks e documentos pela página de cada tipo.

## 3.0.0-beta.3 — 2026-10-30

### Tipos de documento, pastas, campos e templates por tipo (base)
- Três tipos: **Playbook** (`PB-`), **Runbook** (`RB-`, fluxograma opcional) e **Documento** (`DOC-`, sem fluxograma
  e sem aprovador para publicar). Mesmo editor, versões, ciclo de vida, auditoria, exportação e importação. Os IDs
  são únicos entre os tipos; `/api/doc/{id}` vale para todos e `/api/pb/{id}` continua funcionando.
- Arquivos em `runbooks/` e `documentos/` dentro de `MEDUSA_HOME` (criadas no boot). **Os playbooks não se movem** e
  seus arquivos não mudam (teste confere o hash antes e depois do boot).
- **Pastas** (runbooks e documentos): árvore no banco, sem mexer nos arquivos e sem gerar versão; nome único entre
  irmãs, até 6 níveis, sem ciclos; pasta só é excluída vazia ou movendo o conteúdo. Permissão "Gerenciar pastas";
  mover documento exige "Editar". Auditoria: `pasta_criada`, `pasta_renomeada`, `pasta_movida`, `pasta_excluida`,
  `documento_movido`.
- **Campos dinâmicos** definidos pelo template (texto, lista, lista múltipla, data, link), gravados como linhas da
  tabela de propriedades do `.md` (entram no histórico). A biblioteca filtra por tipo, pasta (com subpastas) e
  campos, e devolve contagens por valor (`facets`).
- **Templates por tipo**: lista com filtro por tipo; novo template escolhe o tipo; templates de runbook e documento
  têm abas **Campos** e **Pastas**; o de runbook pode incluir fluxograma modelo. Instalações existentes ganham os
  templates **Runbook padrão** e **Documento padrão** no próximo boot (os existentes não mudam).
- Exportar/importar `.medusa.md` leva o tipo, a pasta e os campos; ao importar, a pasta é recriada se você puder
  gerenciar pastas (senão o documento fica em "Sem pasta", com aviso).
- Novas rotas: `POST /api/doc`, `GET /api/doc/next-id`, `PUT /api/doc/{id}/folder`, `/api/folders` (lista, criar,
  renomear/mover, excluir) e `POST /api/folders/from-template`.

### Banco de dados (migração v5, automática)
- Só acrescenta as tabelas `folders` e `doc_meta`, com a mesma cópia automática antes de migrar
  (`data/backups/playbooks.db.pre-v4-v5-…`). A 2.2 continua abrindo o banco (ignora as tabelas novas).

## 3.0.0-beta.2 — 2026-10-30

### Markdown mais completo
- **Blocos de código** (```` ```bash ```` … ```` ``` ````): nada dentro é interpretado (nem `##`, nem HTML); na leitura,
  nas versões e no HTML exportado ganham o botão **Copiar**. No editor visual, bloco "Código" com a linguagem opcional;
  no modo Markdown, o botão de código cria um bloco quando há várias linhas (ou nada) selecionado.
- **Listas numeradas** (`1.`, `2.` …; a numeração de uma lista continuada, como `4.` depois de um bloco de código, é
  mantida) e listas com `*` e `+`. Linha recuada logo abaixo de um item continua o item (quebra de linha). Listas
  aninhadas ainda não existem: o sub-item aparece como continuação do item de cima.
- **Introdução:** o texto entre a linha de versão e a primeira seção deixou de ser descartado ao salvar. Aparece no
  topo da documentação e tem um cartão próprio no editor.
- **Links** `[texto](url)` com `http`, `https`, `mailto` ou `#/…` (outro playbook); links externos abrem em nova aba.
  Qualquer outro esquema (`javascript:`, `data:`…) é mostrado como texto.
- Arquivos `.md` existentes **não mudam** até alguém salvar; os 22 playbooks de referência relidos pelo parser novo
  geram o mesmo Markdown que antes.

### Correções
- Um bloco de código com linha longa não alarga mais a página (rola dentro do bloco).

## 3.0.0-beta.1 — 2026-10-30

### Papéis e permissões personalizados
- **Administração → Papéis:** crie papéis marcando, numa matriz ação × tipo de documento, o que cada um pode fazer
  (ver, ver rascunhos, criar, editar, alterar status, pode aprovar, restaurar versões, importar, exportar, excluir),
  além das permissões da plataforma (templates, usuários, papéis, auditoria, logs, SSO, aparência, reset).
  Duplicar, restaurar padrão (Editor e Visualizador) e excluir realocando os usuários.
- Os papéis do sistema **Administrador**, **Editor** e **Visualizador** têm exatamente as permissões de antes
  (verificado por teste que compara rota a rota com a 2.2). O Administrador não pode ser alterado nem excluído.
- Sem escalada: quem gerencia papéis ou usuários sem ser administrador só concede o que tem e não mexe em
  usuários ou papéis mais fortes. Mudanças valem na próxima requisição. Auditoria: `papel_criado`,
  `papel_alterado` (permissões que entraram e saíram), `papel_excluido`, `usuario_alterado` com `papel`.
- Usuários, SSO e linha de comando aceitam qualquer papel: o mapeamento de grupos do SSO tem um campo por papel
  (vence o de maior prioridade) e `server.py adduser --role <chave>` valida no banco.
- A interface mostra menus, abas e botões conforme as permissões; a Administração mostra só as sub-abas permitidas.

### Aprovação por outra pessoa (ligada por padrão)
- Para ir a **Produção**, o aprovador precisa ser **diferente de quem está publicando** e **de quem fez a última
  alteração** do conteúdo (pelo login). O diálogo lista só quem pode aprovar e explica quem ficou de fora; sem
  candidatos, orienta a pedir a um administrador (o administrador conta como aprovador).
- Chave em **Administração → Aparência → Governança** (`governanca_alterada` na auditoria). Playbooks que já estão em
  Produção não mudam; a regra vale nas próximas promoções. A auditoria de `status_alterado` ganhou `aprovador_login`.

### Banco de dados (migração v4, automática)
- Só acrescenta: tabela `roles`, coluna `users.role_id` (preenchida com o perfil atual) e `login_attempts.updated`.
  A coluna `users.role` continua como espelho: a 2.2 abre o banco migrado (usuário com papel personalizado entra como
  Visualizador). **Antes de migrar, o app copia o banco** para `data/backups/playbooks.db.pre-v3-v4-<data-hora>`
  (guarda as 5 cópias mais recentes). Isso não substitui o backup do volume.

### Mudanças de comportamento
- Importar **substituindo** um playbook exige a permissão de **excluir** (na 2.2, ser administrador).
- Promover a Produção exige aprovador diferente (veja acima).

## 2.2.0 — 2026-10-30

### Desempenho
- **Cache de documentos** (`library.py`): cada playbook é interpretado uma vez e só volta a ser lido quando o arquivo
  muda (edição feita por fora aparece em até 1 s). Resumos e índice de busca também vão para
  `data/cache/biblioteca.json`, então o servidor sobe pronto mesmo com centenas de playbooks.
- **Lista leve e detalhe sob demanda:** `GET /api/library` (resumo paginado e filtrável, ~0,1 KB por playbook
  comprimido), `GET /api/doc/{id}` (o playbook aberto) e `GET /api/bootstrap` (usuário, marca, catálogo e times). A
  interface deixou de baixar todos os playbooks inteiros a cada carga. Com 500 playbooks: lista em ~1 ms (2 KB com
  gzip) contra 2,9 s (21 MB) antes; 32 acessos simultâneos em ~30 ms contra ~20 s e conexões derrubadas.
- **Busca no servidor** (`GET /api/search`): sem acento, título vale mais que passo/ramo, que vale mais que texto;
  navegação por `↑` `↓` `Enter`.
- **HTTP/1.1** com keep-alive, **gzip**, **ETag/304** nas listas e documentos e **estáticos versionados**
  (`app.js?v=<versão>-<hash>`, cache de 1 ano; o `index.html` é sempre revalidado), o que também impede o navegador de
  misturar JavaScript antigo com a API nova.
- Banco: uma conexão por thread (WAL, `synchronous=NORMAL`) e a sessão validada fica 15 s em memória.
- `GET /api/data` continua funcionando (agora a partir do cache), mas está deprecado e sai na 3.1.
  `/api/doc/{id}/…` é sinônimo de `/api/pb/{id}/…`.

### Segurança e robustez
- **Gravação atômica** de `.md`, `.drawio`, `mappings.json` e templates (arquivo temporário + troca).
- **Revisão obrigatória** em toda gravação de playbook e de template (sem ela: 400 em vez de sobrescrever às cegas).
- Fluxograma com no máximo 400 caixas, 800 setas e 500 caracteres por linha; seta sem `id` é recusada (antes dava erro 500).
- **Sessão:** o cookie é renovado com o uso (o prazo de 8 h sem uso passa a valer de fato) e há uma duração máxima
  (24 h). Variáveis novas: `MEDUSA_SESSION_IDLE_HOURS` e `MEDUSA_SESSION_MAX_HOURS`.
- Conexões paradas são encerradas após 30 s; no máximo 32 requisições processadas ao mesmo tempo (as demais
  aguardam); `Content-Length` inválido devolve 400.
- Login com mais de 80 caracteres é cortado (chave de bloqueio e auditoria); a tabela de tentativas não cresce sem limite.
- Sessão expirada no meio da edição guarda o rascunho antes de pedir o login.
- A importação do formato antigo de usuários (`users.json`) voltou a funcionar.

### Mudança de comportamento
- **Importar substituindo** um playbook existente agora exige ser **administrador** (equivale a excluí-lo, e o editor
  não pode excluir). Editores continuam importando com outro ID.

### Menu lateral
- O botão do menu fica sempre visível e **recolhe/expande o menu também no desktop** (tecla `[`); a escolha fica salva
  no navegador. Em telas estreitas, a gaveta ganhou botão de fechar, fecha com `Esc`, devolve o foco ao botão e
  bloqueia o conteúdo atrás enquanto está aberta.
- **Correção:** abrir o menu numa janela estreita e depois alargá-la deixava a página em branco (a classe do botão,
  `side-open`, também escondia o `body`).

### Para quem mantém
- Testes automatizados (`python3 -m unittest discover -s tests`): matriz de permissões comparada com a da versão
  anterior, migração e rollback do banco, cache, camada HTTP e parser.
- `tools/bench.py` e as medições em `docs/benchmark-base.txt` e `docs/benchmark-2.2.txt`.
- Dockerfile copia todos os `.py` (`COPY *.py`): arquivo novo esquecido não derruba mais o contêiner no boot.

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
