---
target: menu lateral e painel de templates
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:/Users/gabrielflauzino/Documents/Playbooks/modelo2/playbook-app/app.js#menu-templates"
timestamp: 2026-11-02T18-42-35Z
slug: app-js-menu-templates
---
# Crítica: menu lateral e painel de Templates
Method: dual-agent (A: design review · B: detector + navegador)
Total: 25/40 (Aceitável)

| # | Heurística | Nota | Problema-chave |
|---|---|---|---|
| 1 | Status do sistema | 3 | Aba do navegador fica "Templates, times e tags" dentro de um template |
| 2 | Linguagem | 3 | "Times e tags" mistura conceitos; tag = time de categoria apoio |
| 3 | Controle e liberdade | 2 | Edições em Campos/Pastas/Geral somem ao trocar de sub-aba; Esc não fecha o menu do usuário |
| 4 | Consistência | 2 | Um Salvar por sub-aba; faixa de 6px e etiqueta azul fora do DESIGN.md; 4 botões primários na lista |
| 5 | Prevenção de erros | 2 | Perda silenciosa de edição; "Fase NIST padrão" em texto livre |
| 6 | Reconhecimento | 3 | Atalhos `[` e `/` só em tooltip; Ajuda escondida no menu do avatar |
| 7 | Flexibilidade | 2 | Recolher some com tudo (sem trilho de ícones); busca não acha templates/admin |
| 8 | Estética | 3 | Parágrafo de abertura e tabela de 17 variáveis sempre visíveis |
| 9 | Recuperação de erros | 2 | `.err` cru na lista, sem tentar de novo; nada recupera edição perdida |
| 10 | Ajuda | 3 | Bons textos de apoio; Ajuda fora da navegação |

## Prioridades
- [P1] Templates: edições perdidas ao trocar de sub-aba (fieldsTab/foldersTab/general sem guarda; route() só protege Admin e Editor).
- [P1] Template aberto estoura a largura no celular: style.css:975 redefine `.appearance` em 2 colunas e anula o breakpoint de style.css:549 (scrollWidth 444–449; "Exportar template" sai pela esquerda). Afeta também Administração → Aparência.
- [P1] Menu do usuário sem aria-expanded/haspopup, sem Esc, foco não entra; busca sem padrão combobox; filtros sem aria-pressed.
- [P2] Contraste: contagens da barra lateral 2.39 (claro)/3.51 (escuro), placeholder "Buscar" 2.56/3.42, contagens dos filtros de templates 2.33–3.63.
- [P2] IA "Templates, times e tags": times e tags vivem três níveis abaixo; sem breadcrumb; voltar é um ícone de 38×26.
- [P2] Fora do sistema: `.team-card` com border-left 6px (style.css:571), `.cat.central` azul (style.css:576), "Abrir" primário em cada cartão.

## Persona
- Alex: sem trilho de ícones; busca não chega em templates/admin; Salvar por sub-aba.
- Sam: sem skip link; menu do usuário mudo; "Editar"/"Abrir"/"Fechar aba" repetidos sem contexto; botão dentro de link na aba; h1→h3/h4.
- Jordan: Ajuda escondida; chips "padrão", "usa ramos" sem explicação.

## Menores
- Botões fechar aba 20×20; menu sem role=dialog na gaveta; foco ao abrir gaveta frágil (setTimeout durante transição).
- Marca truncada sem title; `/` aparece no celular; ordem dos cartões Documento/Playbook/Runbook; nomes "Padrão" vs "Documento padrão".
- Detector: nenhum dos 17 achados está no escopo (Inter deliberada; xadrez falso positivo; #5B6673 padrão de time adjacente). Overlay bloqueado pela CSP.
