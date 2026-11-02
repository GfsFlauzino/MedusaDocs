---
target: "aba de configuração: usuários, aparência e logs"
total_score: 24
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:/Users/gabrielflauzino/Documents/Playbooks/modelo2/playbook-app/app.js#configuracoes"
timestamp: 2026-11-02T17-54-05Z
slug: app-js-configuracoes
---
# Crítica: Administração → Usuários, Aparência, Logs e retenção
Method: dual-agent (A: design review · B: detector + navegador)
Total: 24/40 (Aceitável)

| # | Heurística | Nota | Problema-chave |
|---|---|---|---|
| 1 | Status do sistema | 3 | Toasts e contadores de envio bons; Aparência e Logs não mostram alterações não salvas |
| 2 | Linguagem do mundo real | 3 | Vocabulário SOC/SIEM correto; "Padrão" preenche mas não salva; reset fala em "cor e página inicial" que não existem |
| 3 | Controle e liberdade | 2 | Role, autenticação e Ativo gravam no change, sem desfazer |
| 4 | Consistência | 2 | Três modelos de salvar numa tela (instantâneo, Salvar por cartão, submit único) |
| 5 | Prevenção de erros | 2 | Virar Administrador com um select; foco no botão vermelho do confirmar; pattern do login ignorado; reduzir retenção apaga auditoria sem aviso |
| 6 | Reconhecimento | 3 | Ações da linha escondidas atrás de rolagem horizontal mesmo em 1440px |
| 7 | Flexibilidade | 1 | Sem busca, filtro, ordenação ou ação em lote em Usuários |
| 8 | Estética minimalista | 3 | Destinos desligados mostram todos os campos; JSON de exemplo domina Retenção |
| 9 | Recuperação de erros | 2 | Erro do Logs aparece longe do campo, sem aria-invalid nem role=alert |
| 10 | Ajuda | 3 | Ótimos textos de apoio; sem link para documentação |

## Prioridades
- [P1] Mudanças de privilégio sem confirmação: role (app.js:1089), Ativo (app.js:1098); ask() foca o botão de confirmar mesmo com danger (app.js:166) → Enter exclui usuário.
- [P1] Reduzir retenção apaga auditoria ao salvar sem confirmação nem contagem (app.js:1321, 1356).
- [P1] Tabela de usuários espremida pelo formulário fixo de 340px (style.css:472): Role/Situação/Redefinir/Excluir atrás de rolagem horizontal.
- [P2] Logs estoura a largura no celular: style.css:660 usa `1fr` em vez de `minmax(0,1fr)`; Host do syslog truncado.
- [P2] Acessibilidade: 12 selects por linha sem nome acessível (app.js:1064, 1069); foco volta ao body após modal/re-render; erros não anunciados; pattern inválido em app.js:1080 (flag v).
- [P2] Governança dentro de Aparência (app.js:1137) e três modelos de salvar.

## Persona
- Alex: sem busca/lote; select salva ao usar setas.
- Sam: selects sem rótulo, foco perdido, drop zone não focável, contraste "ADMIN" 4.40 e "sem logo" 2.76–3.51.
- Rita (gestora SOC): status "aguardando 1º login" só dentro do option; login inválido passa no cliente.

## Menores
- Copy do reset desatualizada (app.js:1288) e resumo sem Runbooks/Documentos (app.js:1282).
- Botão "Resetar aplicação" vermelho em toda sub-aba.
- `.fwd-st .bad` com #C0272D fora do token (style.css:656).
- Sem aviso ao sair com alterações não salvas.
- Detector: só 2 achados tocam o módulo (Inter = escolha deliberada; xadrez do preview = falso positivo). Overlay bloqueado pela CSP.
