---
target: main page de playbooks, documentações e runbooks
total_score: 25
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:/Users/gabrielflauzino/Documents/Playbooks/modelo2/playbook-app/app.js#biblioteca"
timestamp: 2026-11-02T13-43-18Z
slug: app-js-biblioteca
---
# Crítica: páginas principais (Playbooks, Runbooks, Documentos)
Method: dual-agent (A: design review · B: detector + navegador)
Total: 25/40 (Aceitável)

| # | Heurística | Nota | Problema-chave |
|---|---|---|---|
| 1 | Status do sistema | 3 | Trocar visualização/filtro refaz a página inteira sem indicação de carregamento |
| 2 | Linguagem do mundo real | 3 | Aba "Início" vs título "Playbooks" |
| 3 | Controle e liberdade | 3 | Filtros fora da URL; cada clique na barra lateral abre aba nova |
| 4 | Consistência | 1 | As três bibliotecas têm barras, visualizações, estados vazios e ações diferentes |
| 5 | Prevenção de erros | 3 | Pouca ação arriscada nessas páginas |
| 6 | Reconhecimento | 2 | Cartões sem time/raia ou tática; estado dos filtros escondido e perdido no reload |
| 7 | Flexibilidade | 3 | `/`, `[`, árvore por teclado; faltam recentes/favoritos |
| 8 | Estética minimalista | 3 | Subtítulo repetido, "Sem revisão registrada" e "Estrutura do template…" sempre visível |
| 9 | Recuperação de erros | 2 | `.err` cru sem tentar de novo; filtro Produção vazio oferece "Criar playbook" |
| 10 | Ajuda | 2 | Ajuda só no menu do usuário |

## Prioridades
- [P0] Lista de Runbooks/Documentos perde a coluna Nome no celular (style.css:1062 vence as media queries de style.css:747-748).
- [P1] As três páginas se comportam diferente (app.js:716-723 vs 1452-1460).
- [P1] Estados vazios e de zero resultado enganam ou ficam em branco (app.js:699-700, 1419).
- [P2] Cartões sem pista para o incidente: subtítulo idêntico, sem time/raia/MITRE (app.js:676-683).
- [P2] Visão padrão não serve a operação: "Todos" com rascunhos, filtro não lembrado nem na URL.

## Detector
17 achados (1 aviso overused-font Inter; 16 avisos de design-system em app.js:924,1869,1955-1975 = cores do fluxograma e CSS do exportador, falsos positivos; repeating-stripes-gradient style.css:562 = xadrez de transparência, falso positivo). Overlay bloqueado pelo CSP `script-src 'self'`.
