---
name: Medusa Docs
description: Base interativa de playbooks, runbooks e documentos de resposta a incidentes, white label.
colors:
  signal-blue: "#3B5BDB"
  signal-blue-deep: "#2F4AC0"
  signal-blue-ink: "#3451C9"
  signal-blue-soft: "#EEF2FF"
  signal-blue-dark-theme: "#7C93FF"
  signal-blue-ink-dark-theme: "#9DB0FF"
  signal-blue-soft-dark-theme: "#1B2140"
  graphite: "#18181B"
  graphite-hover: "#2E2E33"
  paper: "#FFFFFF"
  sidebar-mist: "#F7F7F8"
  surface-sunk: "#F4F4F5"
  hover-wash: "#F0F0F2"
  hairline: "#E8E8EB"
  hairline-strong: "#DCDCE0"
  text-muted: "#71717A"
  text-faint: "#A1A1AA"
  night: "#0F0F11"
  night-sidebar: "#131316"
  night-surface: "#161619"
  night-surface-sunk: "#1E1E22"
  night-hairline: "#27272C"
  night-text: "#EDEDEF"
  night-muted: "#9B9BA4"
  status-review: "#B45309"
  status-review-base: "#F59E0B"
  status-production: "#15803D"
  status-production-base: "#22C55E"
  danger: "#DC2626"
  danger-soft: "#FEF2F2"
  danger-ink: "#B91C1C"
  field-line: "#8E8E96"
typography:
  display:
    fontFamily: "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "28px"
    fontWeight: 600
    letterSpacing: "-0.015em"
  headline:
    fontFamily: "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "22px"
    fontWeight: 600
    letterSpacing: "-0.015em"
  title:
    fontFamily: "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    letterSpacing: "-0.015em"
  body:
    fontFamily: "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "14px"
    fontWeight: 400
    lineHeight: 1.55
    fontFeature: "\"cv11\", \"ss03\""
  label:
    fontFamily: "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "12.5px"
    fontWeight: 500
  overline:
    fontFamily: "Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Helvetica, Arial, sans-serif"
    fontSize: "12px"
    fontWeight: 600
    letterSpacing: "0.06em"
  mono:
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
    fontSize: "0.86em"
rounded:
  xs: "5px"
  sm: "7px"
  md: "10px"
  lg: "14px"
  xl: "16px"
  pill: "999px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
  page-x: "28px"
  sidebar: "236px"
components:
  button-primary:
    backgroundColor: "{colors.graphite}"
    textColor: "{colors.paper}"
    typography: "{typography.label}"
    rounded: "{rounded.sm}"
    padding: "7px 14px"
  button-primary-hover:
    backgroundColor: "{colors.graphite-hover}"
  button-ghost:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.sm}"
    padding: "7px 14px"
  button-ghost-hover:
    backgroundColor: "{colors.hover-wash}"
  button-soft:
    backgroundColor: "{colors.surface-sunk}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.sm}"
    padding: "7px 14px"
  button-danger:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.danger}"
    rounded: "{rounded.sm}"
    padding: "7px 14px"
  button-danger-hover:
    backgroundColor: "{colors.danger}"
    textColor: "{colors.paper}"
  input:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.sm}"
    padding: "7px 10px"
  card:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.md}"
    padding: "16px 18px"
  chip:
    backgroundColor: "{colors.surface-sunk}"
    textColor: "{colors.graphite}"
    rounded: "{rounded.pill}"
    padding: "1px 9px"
  status-development:
    backgroundColor: "{colors.surface-sunk}"
    textColor: "{colors.text-muted}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  status-review:
    textColor: "{colors.status-review}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  status-production:
    textColor: "{colors.status-production}"
    rounded: "{rounded.pill}"
    padding: "2px 9px"
  nav-item:
    textColor: "{colors.text-muted}"
    rounded: "{rounded.sm}"
    padding: "7px 10px"
  nav-item-active:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.graphite}"
  modal:
    backgroundColor: "{colors.paper}"
    rounded: "{rounded.lg}"
    width: "520px"
---

# Design System: Medusa Docs

## Overview

**Creative North Star: "O Manual de Campo"**

O Medusa Docs é uma ferramenta de trabalho para quem responde a incidentes. Como um bom manual de campo, ele tem de
ser legível sob pressão, sem enfeite, com tudo no lugar esperado, e esconder a profundidade até o momento em que ela é
necessária. O analista abre o playbook certo, segue o fluxograma do seu time e chega ao passo em segundos; o mesmo
material, fora do incidente, aguenta horas de leitura e revisão.

O sistema é minimalista por função, não por moda: uma família tipográfica (Inter), uma paleta neutra levemente fria,
um único acento (Azul Sinal) e ação principal monocromática em Grafite. Superfícies são planas e separadas por linhas
finas; a sombra existe para o que flutua (menus, modais, avisos), não para o que está em repouso. A densidade é de
aplicação: texto base de 14px, controles compactos, muitas informações por tela sem aperto. O produto é white label,
então a moldura recua: nome e logo do workspace são do cliente, e nada no visual pode depender da marca padrão para
parecer completo. As cores das raias, formas e setas do fluxograma pertencem ao modelo do playbook e ficam fora deste
sistema.

Rejeitados explicitamente: painel "hacker" neon (fundo preto com verde ou ciano, estética de terminal), SaaS colorido
(gradientes, ilustrações, vários acentos, cartões com sombra forte) e intranet corporativa antiga (tabelas densas,
bordas pesadas, ícones datados).

**Key Characteristics:**
- Uma fonte, uma tinta, um acento: Inter, Grafite e Azul Sinal.
- Plano com borda: linhas de 1px organizam; sombra só no que flutua ou responde ao hover.
- Componentes firmes e diretos: a ação principal tem o maior contraste da tela e um alvo claro.
- Status do ciclo de vida (Desenvolvimento, Homologação, Produção) é o único lugar com cor semântica constante.
- Tema claro e escuro por usuário, com os mesmos papéis de cor nos dois.

## Colors

Neutros levemente frios com um acento azul usado como sinal; o resto da cor é semântica de status e perigo.

### Primary
- **Azul Sinal** (`signal-blue`; no tema escuro `signal-blue-dark-theme`): foco de campos, seleção de texto,
  indicadores de escolha (opções marcadas, passos do assistente), links e o ID do documento aberto. Variações:
  `signal-blue-ink` para texto e links sobre fundo claro, `signal-blue-soft` para o fundo de uma opção escolhida,
  `signal-blue-deep` para pressionado.

### Neutral
- **Grafite** (`graphite`): texto principal e fundo do botão primário; no tema escuro inverte para quase branco
  (#FAFAFA) com texto Grafite. `graphite-hover` no hover do primário.
- **Papel** (`paper`): fundo da página, cartões, campos e modais no tema claro.
- **Névoa da Lateral** (`sidebar-mist`): fundo do menu lateral, o único plano que difere da página em repouso.
- **Superfície Rebaixada** (`surface-sunk`): cabeçalhos de tabela, chips, botão suave, contadores, blocos de código.
- **Lavagem de Hover** (`hover-wash`): fundo de qualquer item de lista, menu ou botão fantasma sob o ponteiro.
- **Linha Fina** (`hairline`) e **Linha Firme** (`hairline-strong`): bordas de cartões e divisórias; a firme em
  campos, botões fantasma e no hover de cartões.
- **Texto Apagado** (`text-muted`) e **Texto Discreto** (`text-faint`): metadados, rótulos, IDs, contagens, ícones
  em repouso e placeholders.
- **Noite** (`night`, `night-sidebar`, `night-surface`, `night-surface-sunk`, `night-hairline`, `night-text`,
  `night-muted`): os mesmos papéis no tema escuro.

### Tertiary
- **Âmbar de Homologação** (`status-review` sobre tinta de `status-review-base` a 10%): status Homologação e avisos.
- **Verde de Produção** (`status-production` sobre tinta de `status-production-base` a 10%): status Produção e o aviso
  de documento publicado.
- **Perigo** (`danger`, fundo `danger-soft`): ações destrutivas, erros de formulário e avisos de exclusão. Texto de
  erro sobre `danger-soft` usa `danger-ink` (#B91C1C no claro, 5.9:1; no escuro é o próprio Perigo), porque o Perigo
  puro fica abaixo de 4.5:1 sobre a tinta.

### Named Rules
**The One Signal Rule.** O Azul Sinal marca foco, seleção e o que é clicável; nunca vira fundo de botão primário,
faixa decorativa ou ilustração. A ação principal é Grafite.

**The Earned Color Rule.** Fora do Azul Sinal, cor só aparece com significado: status do ciclo de vida, perigo ou as
cores do fluxograma que vêm do modelo. Nenhuma cor nova sem um significado novo.

## Typography

**Display Font:** Inter (com ui-sans-serif, -apple-system, Segoe UI, Roboto, Helvetica, Arial)
**Body Font:** Inter, a mesma família
**Label/Mono Font:** ui-monospace, SFMono-Regular, Menlo, Consolas para código e blocos de código

**Character:** uma única família variável, embutida no app (sem rede), com os recursos "cv11" e "ss03" ligados para
números e letras mais legíveis. A hierarquia vem de tamanho e peso, nunca de uma segunda fonte.

### Hierarchy
- **Display** (600, 28px, -0.015em): título do documento aberto na visualização de documentação.
- **Headline** (600, 22px, -0.015em): título de página (biblioteca, administração) e do cabeçalho do playbook.
- **Title** (600, 15–16px): título de cartão, de seção do documento (h2 18px, h3 15px) e de modal (15px).
- **Body** (400, 14px, 1.55): todo o texto corrido e a interface; tabelas em 13.8px; botões em 13.5px (500).
- **Label** (500, 12.5px): rótulos de campo, metadados e IDs (IDs em 600 com números tabulares).
- **Overline** (600, 12px, 0.06em, maiúsculas): títulos de grupo, como "sect-title" e rótulos de governança (11px).

### Named Rules
**The Tabular ID Rule.** IDs (PB-01, RB-03, DOC-02), contagens e versões usam números tabulares, para que listas
alinhem e o olho ache o documento pelo ID.

## Layout

Aplicação de painel único: menu lateral fixo de 236px à esquerda (logo e nome do workspace, busca, navegação, perfil e
tema no rodapé) e uma área de conteúdo com barra de abas fixa no topo (44px, translúcida com desfoque). O conteúdo fica
num contêiner de até 1280px com 24px no topo e 28px nas laterais. A biblioteca usa grade de cartões
`auto-fill, minmax(320px, 1fr)` com 12px de espaço, ou listas grande e pequena. A documentação usa índice fixo de 250px
à esquerda e o texto em seções-cartão ao lado, com 28px de espaço.

Ritmo de espaçamento em passos de 4px, com os valores reais 4, 6, 8, 10, 12, 16, 18, 24 e 28. Cartões têm 16×18px de
respiro interno.

Responsivo por ponto de quebra, sem fluidez tipográfica: em 900px o menu lateral vira gaveta (com fundo escurecido e
`Esc` para fechar) e as margens caem para 16px; em 1000px e 1180px grades de duas colunas viram uma; em 760px e 560px as
tabelas de lista escondem colunas secundárias. O menu também recolhe no desktop (tecla `[`), com a escolha salva no
navegador.

## Elevation & Depth

O sistema é plano com borda. Em repouso, a profundidade vem de linhas de 1px e de um único plano tonal diferente (o
menu lateral); a sombra aparece em resposta a estado (hover de cartão, item ativo do menu) e no que flutua acima da
página (resultados da busca, menus, modais e avisos rápidos). No tema escuro as sombras ficam mais densas para seguir
visíveis sobre fundos quase pretos.

### Shadow Vocabulary
- **Contorno** (`box-shadow: 0 1px 2px rgba(15,15,20,.05)`): hover de cartões e linhas, item ativo do menu e de
  controles segmentados (somado a um anel de 1px na cor da linha), visualização de documento.
- **Flutuante** (`box-shadow: 0 12px 32px rgba(15,15,20,.10), 0 2px 6px rgba(15,15,20,.04)`): resultados da busca,
  modais, menus suspensos e avisos rápidos.
- **Anel de foco** (`box-shadow: 0 0 0 3px` Azul Sinal a 16–18%): foco de campos e da busca, junto da borda em Azul
  Sinal.

### Named Rules
**The Flat-At-Rest Rule.** Nada tem sombra em repouso, exceto o que flutua. Se um cartão precisa se destacar, use a
linha firme ou o conteúdo, não uma sombra.

## Shapes

Cantos suaves e consistentes, em quatro tamanhos: 7px para controles (botões, campos, itens do menu, abas), 10px para
cartões, tabelas e painéis, 14px para modais e 16px para a visualização de documento. Chips, status e contadores são
pílulas (999px); códigos inline e teclas usam 5px. Bordas são sempre de 1px (cartões "adicionar" usam borda tracejada);
avisos usam uma barra de 3px à esquerda na cor do seu significado, com canto reto desse lado.

## Components

### Buttons
Firmes e diretos: a ação principal é o elemento de maior contraste da tela.
- **Shape:** cantos suaves (7px), borda de 1px, ícone opcional à esquerda com 7px de espaço.
- **Primary:** fundo Grafite, texto Papel, 13.5px peso 500, 7×14px de respiro. No tema escuro, invertido.
- **Hover / Focus:** transição de 0.12s em fundo, borda e cor; o primário escurece para `graphite-hover`. Desabilitado
  em 45% de opacidade.
- **Ghost:** fundo Papel com linha firme; hover em Lavagem de Hover. Ação secundária padrão.
- **Soft:** Superfície Rebaixada sem borda; ações terciárias e de barra de ferramentas.
- **Danger:** texto em Perigo com borda tingida; no hover vira fundo Perigo com texto branco. Só para ações
  destrutivas.
- **Tamanhos:** `sm` (6×11px, 13px) e `xs` (3×9px, 12.5px, 6px de canto) para tabelas e barras compactas.

### Chips
- **Style:** pílula em Superfície Rebaixada com linha fina, 12px peso 500; chips de time usam a cor da raia do modelo
  com texto branco.
- **State:** como filtro, o ativo ganha Superfície Rebaixada e linha fina; o inativo é só texto apagado.

### Status do ciclo de vida
O sinal mais importante da biblioteca: um ponto de 7px na cor do status e o nome, numa pílula tingida a 10%.
Desenvolvimento em neutro apagado (aparece como Rascunho nos documentos), Homologação em Âmbar (Em revisão) e Produção
em Verde (Publicado).

### Cards / Containers
- **Corner Style:** 10px.
- **Background:** Papel (Noite no escuro).
- **Shadow Strategy:** plano em repouso; no hover a borda vai para a linha firme e ganha a sombra de contorno.
- **Border:** 1px de linha fina; cartão "novo" com borda tracejada e fundo transparente.
- **Internal Padding:** 16×18px; ID em rótulo apagado com números tabulares, título em 16px, descrição em 13px apagado.

### Inputs / Fields
- **Style:** fundo Papel, linha firme, 7px de canto, 13.5px, 7×10px de respiro; rótulo acima em 12.5px peso 500.
- **Focus:** borda em Azul Sinal e anel de 3px do Azul Sinal a 16%, sem contorno do navegador.
- **Error / Disabled:** mensagem em `danger-ink` sobre `danger-soft`, com `role="alert"` e o campo marcado com
  `aria-invalid` (borda em Perigo); campos travados em Superfície Rebaixada com texto apagado.
- **Login:** os campos são a interface inteira, então usam a borda `field-line` (#8E8E96 no claro, #6E6E78 no escuro,
  3:1 ou mais sobre a superfície). Em toque e telas até 640px, campos e botão têm 16px e 44px de altura (sem zoom do
  iOS no foco). O nome do workspace é o título da página; abaixo do formulário fica o contato para acesso definido
  em Aparência.
- **Busca:** campo de 34px com ícone à esquerda e a tecla `/` indicada à direita, que some no foco.

### Navigation
- **Menu lateral:** itens de 7×10px com ícone de 17px, texto apagado peso 500 e contagem tabular discreta à direita;
  hover em Lavagem de Hover; ativo em Papel com sombra de contorno e anel de 1px (o item "levanta" do plano da lateral).
- **Abas do navegador interno:** abas de 34px com canto superior de 7px; a ativa em Papel com borda e sem linha
  inferior, unida ao conteúdo; fechar com X ou botão do meio.
- **Abas da página** (Fluxograma, Documentação, Versões): texto apagado com sublinhado de 2px em Grafite na ativa.
- **Mobile:** abaixo de 900px a lateral vira gaveta sobre o conteúdo.

### Modais
Fundo Papel, 14px de canto, borda de 1px e sombra flutuante, 520px (760px na versão larga), sobre um véu escuro a 45%
que entra em 0.15s. Cabeçalho com título de 15px e linha divisória.

### Avisos rápidos (toast)
Grafite com texto Papel, 7px de canto, centralizados no rodapé; aviso em Âmbar ganha barra de 3px; erro vira fundo
Perigo.

### Visualização de documento
O componente de leitura longa: índice fixo à esquerda com marcador de 1px, seções em cartões de 10px com h2 de 18px e
h3 de 15px, tabelas com cabeçalho rebaixado e citações com barra à esquerda.

## Do's and Don'ts

### Do:
- **Do** use Grafite (`graphite`) na ação principal de cada tela e só nela.
- **Do** reserve o Azul Sinal para foco, seleção, links e escolha marcada.
- **Do** separe superfícies com linhas de 1px (`hairline`, `hairline-strong`) e deixe a sombra para hover e para o
  que flutua.
- **Do** mostre o status do ciclo de vida sempre com ponto e texto, nas três cores semânticas.
- **Do** use números tabulares em IDs, contagens e versões.
- **Do** desenhe cada tela nos dois temas, com os mesmos papéis de cor.
- **Do** deixe a moldura funcionar com qualquer nome e logo de workspace, inclusive sem logo.

### Don't:
- **Don't** pareça um painel "hacker" neon: nada de fundo preto com verde ou ciano, fontes de terminal na interface
  ou brilhos.
- **Don't** pareça um SaaS colorido: sem gradientes, ilustrações, vários acentos ou cartões com sombra forte.
- **Don't** pareça uma intranet corporativa antiga: sem bordas pesadas, tabelas apertadas ou ícones datados.
- **Don't** introduza uma segunda família tipográfica além da mono para código.
- **Don't** altere as cores das raias, formas e setas do fluxograma: elas pertencem ao modelo do playbook.
- **Don't** use o Azul Sinal como fundo de botão primário ou como decoração.
