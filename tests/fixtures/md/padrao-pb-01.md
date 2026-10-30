# PB-01 — Phishing

Versão 0.1 · 01/10/2026 · Ana

## Propriedades do playbook

| Campo | Valor |
| --- | --- |
| ID | PB-01 |
| Nome | Phishing |
| Versão | 0.1 (rascunho) |
| Owner do documento | CSIRT |
| Fase NIST | Detecção e Análise → Pós-Incidente (ciclo completo) |
| Tática MITRE principal |  |
| Ramos | R1 Credencial, R2 Anexo |
| Times envolvidos | SOC N1, SOC N2, CSIRT e times de apoio conforme o caso |
| Documentos de referência | Plano de resposta a incidentes da organização |

## Fluxograma-mapa

O fluxograma é o mapa de operação: cada caixa corresponde a um passo deste documento. A fonte editável é o arquivo **pb-01-phishing.drawio**.

Setas tracejadas: âmbar = handoff ao SOC N2 · vermelha = escalonamento ao CSIRT · roxa = outro playbook · cinza = acionamento de time de apoio.

## Objetivo e escopo

Descrever o tipo de alerta que este playbook trata.

Pergunta central da triagem: **(definir)**

**Fora do escopo** (redirecionar para o playbook indicado):

| Caso | Vai para |
| --- | --- |
|  |  |

## Regras do playbook

- **Todo caso sobe por níveis:** SOC N1 → SOC N2 → CSIRT.
- **Nenhum caso volta de nível.** O CSIRT não devolve ao SOC e o SOC N2 não devolve ao SOC N1.
- **Times de apoio são acionados pelo CSIRT**, com o motivo registrado no caso.
- **Evidências são preservadas antes de qualquer contenção.**
- **Contenção que pode afetar a disponibilidade** é validada com o responsável pelo ativo antes de executar.

## Tabela de decisão da triagem

O SOC N1 classifica o alerta em um dos estados abaixo. O estado decide o destino.

| Estado | Definição | Destino | Prioridade |
| --- | --- | --- | --- |
| E1 Falso positivo | Atividade legítima ou regra imprecisa | Encerrar no N1 | Original |
| E2 Tentativa sem sucesso | Bloqueada, sem indício de impacto | Encerrar no N1 (se não recorrente) | Original |
| E3 Inconclusivo | Não foi possível determinar o resultado | SOC N2 | Elevada |
| E4 Sucesso ou impacto | Há indício de comprometimento | SOC N2, que escala ao CSIRT | Alta |

## Fluxo de resposta por fase

Cada passo segue o formato **verbo + o quê → critério de saída**. O ID do passo é o que se registra no caso.

### Fase 1 · Triagem — SOC N1

| ID | Ação | Critério de saída |
| --- | --- | --- |
| T0 | Verificar se há caso aberto com a mesma origem ou o mesmo alvo | Duplicado: vincular e encerrar. Senão, seguir para T1 |
| T1 | Confirmar aderência ao playbook | Não aderente: redirecionar conforme Fora do escopo |
| T2 | Definir o ramo | Ramo R1 a R2 registrado |
| T3 | Enriquecer origem, alvo e contas envolvidas | Contexto registrado |
| T4 | Classificar o estado (E1 a E4) e ajustar a prioridade | Estado e prioridade registrados |
| T5 | E1 ou E2: encerrar com registro | Caso encerrado no N1 |
| T6 | Demais casos: montar o pacote de handoff e escalar ao SOC N2 | Pacote completo no caso |

### Fase 2 · Análise — SOC N2

| ID | Ação | Critério de saída |
| --- | --- | --- |
| A1 | Revisar o pacote do N1 e confirmar estado e ramo | Classificação mantida ou corrigida com justificativa |
| A2 | Correlacionar eventos e buscar os indicadores retroativamente | Caso isolado ou campanha |
| A3 | Validar o impacto no alvo | Impacto confirmado, descartado ou indeterminado |
| A4 | Executar contenção simples, se cabível | Contenção registrada com horário |
| A5 | Decidir: sem sucesso, encerrar; sucesso ou suspeita, escalar ao CSIRT | Destino registrado com justificativa |

### Fase 3 · Investigação — CSIRT

| ID | Ação | Critério de saída |
| --- | --- | --- |
| I1 | Validar o escopo inicial: ativos, contas e janela de tempo | Escopo registrado |
| I2 | Preservar evidências | Evidências coletadas ou inviabilidade registrada |
| I3 | Investigar o alcance | Atividades do atacante mapeadas |
| I4 | Decidir se há incidente | Descartado: encerrar. Confirmado: seguir |
| I5 | Acionar os times de apoio necessários | Times acionados com escopo definido |

### Fase 4 · Contenção, erradicação e recuperação — CSIRT

| ID | Ação | Critério de saída |
| --- | --- | --- |
| C1 | Definir as ações de contenção pelo ramo | Ações e alvos definidos |
| C2 | Validar impacto em disponibilidade e executar a contenção | Contenção concluída e verificada |
| C3 | Erradicar: remover artefatos e corrigir a causa | Ambiente sem artefatos |
| C4 | Recuperar e monitorar | Serviço restabelecido sob monitoração |

### Fase 5 · Pós-incidente — CSIRT

| ID | Ação | Critério de saída |
| --- | --- | --- |
| P1 | Compartilhar IOCs e TTPs finais | Compartilhamento registrado |
| P2 | Registrar a classificação final do incidente | Campos preenchidos no caso |
| P3 | Conduzir as lições aprendidas e propor ajustes | Ajustes registrados no histórico |

## Ramos em detalhe

Cada ramo descreve o cenário, o que conta como sucesso e a contenção de cada time.

### R1 · Credencial

| Item | Conteúdo |
| --- | --- |
| Entrada |  |
| Cenário |  |
| O N1 verifica |  |
| É sucesso quando | x |
| Desfecho típico |  |
| Contenção do SOC |  |
| Contenção do CSIRT |  |
| Saídas |  |
| MITRE |  |

### R2 · Anexo

| Item | Conteúdo |
| --- | --- |
| Entrada |  |
| Cenário |  |
| O N1 verifica |  |
| É sucesso quando | y |
| Desfecho típico |  |
| Contenção do SOC |  |
| Contenção do CSIRT |  |
| Saídas |  |
| MITRE |  |

## Critérios de encerramento

| Time | Encerra quando | Nunca encerra quando |
| --- | --- | --- |
| SOC N1 | E1 ou E2, com registro no caso | Há qualquer indício de sucesso |
| SOC N2 | Ausência de sucesso comprovada após análise | Impacto confirmado |
| CSIRT | Incidente descartado, ou recuperação concluída e lições aprendidas registradas | Classificação final não registrada |

## Itens em aberto e histórico

**Itens em aberto**

- [ ] Validar este rascunho com o time

**Histórico de versões**

| Versão | Data | Alteração |
| --- | --- | --- |
| 0.1 | 01/10/2026 | Rascunho inicial |
