---
target: "administração: roles, auditoria e sso"
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
target_identity: "file:/Users/gabrielflauzino/Documents/Playbooks/modelo2/playbook-app/app.js#admin-roles-auditoria-sso"
timestamp: 2026-11-02T19-08-21Z
slug: app-js-admin-roles-auditoria-sso
---
# Crítica: Administração → Roles, Auditoria, SSO
Method: dual-agent (A: design review · B: detector + navegador)
Total: 21/40 (Aceitável)

| # | Heurística | Nota | Problema-chave |
|---|---|---|---|
| 1 | Status do sistema | 2 | Switch do SSO continua "Desativado" depois de marcado; contador da auditoria não muda com o filtro |
| 2 | Linguagem | 2 | Auditoria mostra chaves cruas (retencao_dias, http: false) e 13 ações sem tradução (papel_alterado…) |
| 3 | Controle e liberdade | 1 | Roles e SSO perdem edições ao sair; Nova role sem Cancelar; Restaurar padrão sem destaque de perigo |
| 4 | Consistência | 2 | Padrão antigo: sem h2, sem Unsaved, sem role=alert; "papel" na auditoria |
| 5 | Prevenção de erros | 2 | Ativar SSO ou restringir login por senha sem confirmação nem resumo de efeito |
| 6 | Reconhecimento | 2 | 45 caixas + 10 permissões de plataforma sem resumo nem agrupamento por risco |
| 7 | Flexibilidade | 2 | Auditoria sem período, sem busca no servidor (q existe), sem exportar dali |
| 8 | Estética | 3 | Calmo; jargão de protocolo no SSO; tag.warn clara no escuro |
| 9 | Recuperação de erros | 2 | Erros sem role=alert, longe do campo; filtro vazio sem mensagem |
| 10 | Ajuda | 3 | Boa ajuda por ação; prioridade só em tooltip |

## Prioridades
- [P1] Roles e SSO sem guarda de alterações não salvas (roles app.js:1316, ssoAdmin app.js:1514 não usam Unsaved); verificado: marcar uma permissão e trocar de sub-aba perde tudo.
- [P1] SSO: rótulo do switch congelado (app.js:1520); ativar/restringir login sem confirmação; "Testar" só verifica o emissor.
- [P1] Auditoria não serve a uma investigação: 500 linhas filtradas no cliente, filtro não olha detalhes/IP, sem período, hora sem segundos nem fuso, sem estado vazio, sem exportar.
- [P1] Vocabulário da auditoria: 13 ações cruas (papel_*, sugestao_*, pasta_*, documento_movido, pastas_do_template) e chaves de detalhe cruas.
- [P2] Permissões de plataforma planas, sem risco; sem "afeta N usuários"; contraste de "1 usuário" (2.33–3.42), "—" da matriz (2.56) e placeholders (3.6).

## Persona
- Alex: Duplicar cria a role na hora; Nova role começa vazia; sem link para recorte da auditoria.
- Sam: erros mudos; filtro da auditoria sem rótulo; matriz sem caption/scope; cartões da auditoria no celular sem rótulos de coluna; role ativa sem aria-current.
- Investigador SOC: sem período, sem IP, sem segundos/fuso; "papel_alterado" com chaves cruas.

## Menores
- tag.warn sem tema escuro; Administrador mostra 45 caixas desabilitadas; matriz com 98px escondidos no celular e caixas de 16px; comentário duplicado em app.js:1563.
- Detector: nenhum achado no escopo; overlay bloqueado pela CSP.
