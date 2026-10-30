# RB-01 — Isolar host no EDR

Versão 0.1 · 30/10/2026 · Equipe de Plataforma

Este runbook descreve como isolar um host pela console do EDR.
O texto entre o título e a primeira seção também faz parte do documento.

## Propriedades do runbook

| Campo | Valor |
| --- | --- |
| ID | RB-01 |
| Nome | Isolar host no EDR |
| Versão | 0.1 |

## Procedimento

1. Abrir a console do EDR com a conta de serviço.
2. Localizar o host pelo hostname ou pelo IP.
3. Executar o isolamento:

```bash
edrctl isolate --host "$HOST" --reason "IR-2026-001"
edrctl status --host "$HOST"
```

4. Registrar o horário no caso.

## Pré-requisitos

* Acesso de operador no EDR
* Número do caso aberto
+ Janela aprovada quando o ativo for crítico

## Validação

- O host aparece como **isolado** na console
  e não responde a ping a partir da rede de usuários.
- O agente continua se comunicando com a console.
