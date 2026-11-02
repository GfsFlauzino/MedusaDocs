# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

- **Analistas de SOC e CSIRT (N1, N2, resposta a incidentes):** leem playbooks, runbooks e documentos em duas
  situações de mesmo peso: **durante um incidente**, sob pressão, precisando abrir o playbook certo, seguir o
  fluxograma do seu time e achar o passo em segundos; e **na preparação**, estudando, treinando e revisando o material
  fora do calor do incidente. Podem sugerir alterações nos textos.
- **Editores do time de segurança:** escrevem e mantêm os documentos, fluxogramas e templates sem código, promovem pelo
  ciclo de vida (Desenvolvimento → Homologação → Produção) e aceitam ou recusam sugestões dos analistas.
- **Administradores da instalação:** usuários, roles e permissões, SSO, logs/retenção, aparência (nome e logo do
  workspace), governança e reset.

Cada instalação é de uma organização diferente: o produto é open source e white label.

## Product Purpose

Base interativa de resposta a incidentes: cada playbook une um documento (fases, passos, ramos, critérios) e um
fluxograma por time, ligados entre si (clicar numa caixa do fluxograma leva ao trecho do documento). Runbooks
(procedimentos, fluxograma opcional) e Documentos (políticas, normas, guias) usam o mesmo editor, versões, ciclo de
vida, auditoria e templates. Sucesso: o analista encontra e segue o procedimento certo rapidamente durante o
incidente, e o time mantém o material vivo, revisado e auditável.

## Positioning

Produto **open source distribuído para vários SOCs/CSIRTs**, cada um com seu nome e logo. O que o distingue:

- documento e fluxograma do mesmo playbook são uma coisa só, navegável nos dois sentidos, com raias por time;
- formatos abertos e portáveis (`.md` + `.drawio` em disco; troca entre instalações em `.medusa.md`, Markdown + Mermaid);
- instalação trivial: só a biblioteca padrão do Python 3, ou uma imagem Docker, sem dependências externas;
- governança de time de segurança embutida: roles por tipo de documento e ação, aprovação de Produção por pessoa
  diferente de quem editou, versões e auditoria de tudo.

## Operating Context

- Uso em navegador dentro da rede da organização, normalmente atrás de proxy reverso com HTTPS; instância única
  (SQLite + arquivos em `MEDUSA_HOME`).
- Interface em português do Brasil.
- Fluxos centrais: biblioteca (cartões ou listas, pastas e filtros por campo), abas como num navegador, busca no
  servidor (atalho `/`), visualizações Fluxograma e Documentação, Versões, editores, Sugestões, Ligações e Pendências.
- Integra-se ao ambiente do time por SSO (OpenID Connect) e envio de auditoria ao SIEM (JSON por HTTP(S), syslog ou
  arquivo JSON Lines).

## Capabilities and Constraints

- Tipos de documento: Playbook (`PB-`, fluxograma obrigatório, passos e ramos, exige aprovador), Runbook (`RB-`,
  fluxograma opcional, pastas e campos), Documento (`DOC-`, sem fluxograma nem aprovador; ciclo exibido como
  Rascunho → Em revisão → Publicado).
- Permissões `área.ação` por tipo; terminologia de interface: **Roles** (não "papéis").
- Só biblioteca padrão do Python no servidor; JavaScript puro no navegador, com CSP estrita (sem script inline).
  Rejeitados por decisão: Redis, ORM, frameworks assíncronos, múltiplos processos.
- As cores do fluxograma fazem parte do modelo dos playbooks e não mudam com a aparência.
- White label: nome do workspace e logo configuráveis pelo administrador; tema claro e escuro por usuário.
- Migrações do banco são sempre aditivas, com backup antes, e permitem rollback para a versão anterior.

## Brand Commitments

- Nome padrão do produto: **Medusa Docs**; cada instalação pode substituí-lo pelo nome e logo do seu workspace, então a
  interface não pode depender da marca padrão para funcionar ou parecer completa.
- A pasta `playbook-app/logo/` (logo de cobras em degraus) **não é compromisso de marca**: não usar.

## Evidence on Hand

- Ícones do Iconoir (MIT), embutidos em `icons.js`; fonte Inter embutida em `assets/` (OFL).
- Template Padrão com raias SOC N1, SOC N2 e CSIRT e times de apoio com descrições genéricas.
- Não há depoimentos, clientes, métricas de adoção nem casos publicados: não inventar.

## Product Principles

1. **Rápido no incidente, profundo na preparação:** o caminho até o passo certo é curto; o detalhe está a um clique.
2. **A marca é do cliente:** white label de verdade; o produto recua para o nome e a logo de quem instala.
3. **Aberto e portável:** os arquivos são a fonte da verdade e saem da ferramenta sem perda.
4. **Governança sem atrito:** controle de quem edita, aprova e publica, com tudo auditável, sem burocracia na leitura.
5. **Simples de instalar e manter:** nada além do Python e de uma imagem Docker.
