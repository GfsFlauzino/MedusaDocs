# Changelog

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
