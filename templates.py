"""Templates de playbook: documento modelo, fluxograma modelo e times/tags.

Cada template é um arquivo templates/<chave>.medusa-template.md, no mesmo formato da exportação de
playbooks (front matter + Markdown + bloco de times + fluxo em Mermaid). Por isso é exportável e
importável entre instalações.

Variáveis (preenchidas na criação do playbook)
  {{id}} {{nome}} {{autor}} {{data}} {{owner}} {{nist}} {{mitre}} {{objetivo}} {{pergunta}}
  {{ramos.total}} {{ramos.lista}} {{arquivo_drawio}}
Repetição por ramo: o que contém {{ramo.n}}, {{ramo.id}}, {{ramo.nome}} ou {{ramo.pergunta}} é repetido
uma vez para cada ramo informado:
  • subseção (### R{{ramo.n}} · {{ramo.nome}}), linha de tabela, item de lista ou parágrafo;
  • caixa do fluxograma (com as setas ligadas a ela e o vínculo "ao clicar"), lado a lado.
"""
import copy, hashlib, json, os, re
from datetime import datetime
from pathlib import Path

import bundle
import flowdsl
import pbcore as core
import ramos

TPL_DIR = Path(os.environ.get("PB_TEMPLATES") or core.HOME / "templates")
KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
SUFFIX = ".medusa-template.md"
VAR_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")
RAMO_RE = re.compile(r"\{\{\s*ramo\.")
REPEAT_GAP = 10

VARIABLES = [
    ("id", "ID do playbook (PB-00)"), ("nome", "Nome do playbook"), ("autor", "Autor escolhido na criação"),
    ("data", "Data da criação"), ("owner", "Owner do documento"), ("nist", "Fase NIST"),
    ("mitre", "Táticas MITRE escolhidas"), ("objetivo", "Texto de objetivo e escopo"), ("pergunta", "Pergunta central da triagem"),
    ("ramos.total", "Quantidade de ramos"), ("ramos.lista", "Lista dos ramos (R1 Nome, R2 Nome…)"),
    ("arquivo_drawio", "Nome do arquivo .drawio"),
    ("ramo.n", "Número do ramo (repete o trecho por ramo)"), ("ramo.id", "R1, R2… (repete)"),
    ("ramo.nome", "Nome do ramo (repete)"), ("ramo.pergunta", "Indicador de sucesso do ramo (repete)"),
]


class TemplateError(ValueError):
    pass

# ───────────────────────── arquivos ─────────────────────────

def path_of(key):
    if not KEY_RE.fullmatch(key or ""): raise TemplateError("template não encontrado")
    return TPL_DIR / f"{key}{SUFFIX}"

def key_for(name):
    base = core.slug(name)[:40] or "template"
    key, i = base, 2
    while (TPL_DIR / f"{key}{SUFFIX}").exists(): key = f"{base[:36]}-{i}"; i += 1
    return key

def to_text(t):
    fm = {"format": "medusa-template", "version": 1, "name": t["name"], "description": t.get("description", ""),
          "owner": t.get("owner", ""), "nist": t.get("nist", ""),
          "updated_at": t.get("updated_at") or datetime.now().isoformat(timespec="seconds"), "updated_by": t.get("updated_by", "")}
    front = "---\n" + "".join(f"{k}: {str(v).replace(chr(10), ' ')}\n" for k, v in fm.items()) + "---\n\n"
    teams = json.dumps(t.get("teams", {}), ensure_ascii=False, indent=2).replace("-->", "-- >")
    return (f"{front}{core.doc_to_md(t['doc'])}\n<!-- medusa:teams\n{teams}\n-->\n\n<!-- medusa:flow -->\n"
            f"```mermaid\n{flowdsl.render(t['flow'], t.get('refs', {}))}```\n")

def from_text(text, catalog):
    p = bundle.parse(text, catalog)
    m = p["meta"]
    if m.get("format") not in (None, "medusa-template", bundle.FORMAT):
        raise TemplateError("Arquivo não é um template do Medusa Docs")
    teams = {k: v for k, v in p["teamDefs"].items()}
    return {"name": (m.get("name") or p["name"] or "Template")[:60], "description": m.get("description", "")[:300],
            "owner": m.get("owner", "")[:60], "nist": m.get("nist", "")[:200], "doc": p["doc"], "flow": p["flow"],
            "refs": p["refs"], "teams": teams, "updated_at": m.get("updated_at", ""), "updated_by": m.get("updated_by", ""),
            "warnings": p["warnings"]}

def load(key, catalog=None):
    f = path_of(key)
    if not f.exists(): raise TemplateError("template não encontrado")
    text = f.read_text("utf-8")
    t = from_text(text, catalog if catalog is not None else core.load_teams())
    t.pop("warnings", None)
    t["key"] = key
    t["rev"] = hashlib.sha1(text.encode()).hexdigest()[:16]
    return t

def save(key, t):
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    t = {k: v for k, v in t.items() if k not in ("key", "rev", "warnings")}
    t["updated_at"] = datetime.now().isoformat(timespec="seconds")
    path_of(key).write_text(to_text(t), "utf-8")

def list_all(catalog=None):
    out = []
    for f in sorted(TPL_DIR.glob(f"*{SUFFIX}")):
        key = f.name[:-len(SUFFIX)]
        try:
            t = load(key, catalog)
        except Exception as e:  # arquivo corrompido não derruba a lista
            out.append({"key": key, "name": key, "error": str(e)}); continue
        out.append(summary(t))
    return out

def uses_ramos(t):
    blob = json.dumps(t["doc"], ensure_ascii=False) + json.dumps(t["flow"], ensure_ascii=False)
    return bool(RAMO_RE.search(blob))

def summary(t):
    return {"key": t["key"], "name": t["name"], "description": t.get("description", ""), "owner": t.get("owner", ""),
            "nist": t.get("nist", ""), "sections": len(t["doc"]["sections"]), "nodes": len(t["flow"]["nodes"]),
            "lanes": [l["label"] for l in t["flow"]["lanes"]], "teams": sorted(t.get("teams", {})), "usesRamos": uses_ramos(t),
            "updated_at": t.get("updated_at", ""), "updated_by": t.get("updated_by", "")}

def view(t, catalog):
    """Visão no mesmo formato de um playbook, para os editores de documento e de fluxograma."""
    v = core.build_view("TPL", t["key"], t["doc"], t["flow"], t.get("refs", {}), t.get("teams") or {})
    sm = summary(t)
    v.update({k: sm[k] for k in ("key", "name", "description", "owner", "nist", "usesRamos", "updated_at", "updated_by")})
    v.update(id=t["key"], slug=t["key"], rev=t["rev"], template=True, teamDefs=t.get("teams", {}), hasRamos=has_ramos(t))
    d = ramos.doc_ramos(t["doc"])
    if ramos.PROTO in d:   # a aba Ramos e o "ao clicar" do editor enxergam o protótipo
        v["ramos"] = [{"id": "R" + ramos.PROTO, "title": f"R{ramos.PROTO} · {d[ramos.PROTO]['name']} (repete por ramo)", "html": "",
                       "short": d[ramos.PROTO]["name"]}] + v["ramos"]
    return v

# ───────────────────────── template padrão ─────────────────────────
# Toda instalação tem o template "Padrão" (chave fixa, não pode ser excluído): raias SOC N1, SOC N2 e CSIRT,
# times de apoio de segurança genéricos, ramos e um ciclo de resposta completo. Serve de ponto de partida.

DEFAULT_KEY = "padrao"
BASIC_TEAMS = ("SOC N1", "SOC N2", "CSIRT")
SUPPORT_COLOR = "#5B6673"

def _team(color, kind, summary, does, never=(), category="apoio"):
    return {"color": color, "kind": kind, "summary": summary, "does": list(does), "never": list(never), "category": category}

DEFAULT_TEAMS = {
    "SOC N1": _team("#1D62D1", "Operação · Triagem",
        "Primeiro nível de atendimento. Recebe os alertas, verifica duplicidade e aderência ao playbook, enriquece o contexto, "
        "classifica o estado e a prioridade. Encerra o que não tem impacto e escala o restante ao SOC N2.",
        ["Triar e classificar os alertas", "Enriquecer origem, alvo e contas envolvidas", "Encerrar falsos positivos e tentativas sem sucesso, com registro no caso",
         "Montar o pacote de handoff e escalar ao SOC N2"],
        ["Escalar direto ao CSIRT sem passar pelo SOC N2", "Acionar times de apoio", "Executar contenção em servidores ou serviços críticos"], "central"),
    "SOC N2": _team("#B25E09", "Operação · Análise",
        "Segundo nível. Aprofunda a análise do caso recebido do SOC N1: correlaciona eventos, faz busca retroativa e valida o impacto. "
        "Executa contenções simples e escala ao CSIRT quando há sucesso, suspeita ou impacto.",
        ["Revisar o pacote recebido e confirmar a classificação", "Correlacionar eventos e buscar indicadores retroativamente", "Validar o impacto no alvo",
         "Executar contenções simples (conta de usuário, IP externo, estação)", "Escalar ao CSIRT com justificativa"],
        ["Devolver o caso ao SOC N1", "Encerrar caso com impacto confirmado"], "central"),
    "CSIRT": _team("#C0272D", "Resposta a incidentes",
        "Time de resposta a incidentes. Investiga o escopo, confirma o incidente, coordena contenção, erradicação e recuperação, "
        "aciona os times de apoio e conduz o pós-incidente.",
        ["Preservar evidências antes de qualquer mudança", "Investigar o alcance e confirmar o incidente", "Acionar os times de apoio necessários",
         "Conter, erradicar e recuperar", "Conduzir as lições aprendidas"],
        ["Devolver o caso ao SOC", "Encerrar sem registrar a classificação final e as lições aprendidas"], "central"),
    "DFIR": _team(SUPPORT_COLOR, "Apoio · Forense digital",
        "Forense digital e resposta. Acionado quando há necessidade de coleta e análise técnica aprofundada ou de preservação com valor legal.",
        ["Coleta forense de disco e memória", "Análise de artefatos e linha do tempo", "Preservação de evidências com cadeia de custódia"]),
    "Threat Intel": _team(SUPPORT_COLOR, "Apoio · Inteligência de ameaças",
        "Inteligência de ameaças e hunting. Contextualiza indicadores e técnicas e procura sinais do mesmo ator em todo o ambiente.",
        ["Enriquecer IOCs e TTPs com inteligência interna e externa", "Executar buscas (hunting) em todo o ambiente", "Propor novas detecções"]),
    "IAM": _team(SUPPORT_COLOR, "Apoio · Identidades e acessos",
        "Gestão de identidades e acessos. Atua em tudo que envolve contas, credenciais, sessões e privilégios.",
        ["Bloquear contas e redefinir credenciais", "Revogar sessões, tokens e chaves", "Revisar privilégios e contas de serviço"]),
    "Vulnerabilidades": _team(SUPPORT_COLOR, "Apoio · Gestão de vulnerabilidades",
        "Gestão de vulnerabilidades. Identifica a falha explorada, prioriza a correção e verifica a exposição de outros ativos.",
        ["Identificar a vulnerabilidade explorada", "Priorizar e acompanhar a correção", "Verificar outros ativos expostos à mesma falha"]),
    "AppSec": _team(SUPPORT_COLOR, "Apoio · Segurança de aplicações",
        "Segurança de aplicações. Apoia incidentes em aplicações web, APIs e código.",
        ["Analisar a exploração em aplicações e APIs", "Orientar correções no código", "Ajustar regras de proteção (WAF, API gateway)"]),
    "Cloud Security": _team(SUPPORT_COLOR, "Apoio · Segurança em nuvem",
        "Segurança em nuvem. Investiga e contém incidentes em contas, recursos e serviços de nuvem.",
        ["Analisar logs e configurações de nuvem", "Conter recursos, chaves e identidades de nuvem", "Corrigir configurações expostas"]),
    "Infraestrutura": _team(SUPPORT_COLOR, "Apoio · Operações de TI",
        "Operações de TI. Executa e valida ações que afetam a disponibilidade de servidores, rede e serviços.",
        ["Validar contenções com impacto em disponibilidade", "Isolar ativos e segmentos de rede", "Restaurar serviços e backups"]),
    "Privacidade": _team(SUPPORT_COLOR, "Apoio · Privacidade e jurídico",
        "Privacidade e jurídico. Avalia exposição de dados pessoais e obrigações legais e regulatórias.",
        ["Avaliar se há dados pessoais ou sensíveis envolvidos", "Orientar comunicações e notificações obrigatórias", "Registrar o caso para fins legais"]),
}

DEFAULT_FLOW = """flowchart TB
  subgraph n1["SOC N1"]
    alerta(["Alerta"])
    dup{"Duplicado?"}
    vinc["Vincular ao<br>caso existente"]:::neutral
    ader{"Aderente ao<br>playbook?"}
    outro["Outro playbook<br><small>fora do escopo</small>"]:::crossref
    ramo{"Ramo<br>R1 a R{{ramos.total}}"}
    r["<b>R{{ramo.n}} {{ramo.nome}}</b><br><small>{{ramo.pergunta}}</small>"]
    est{"Sem sucesso<br>e sem impacto?"}
    encn1["<b>Encerrar no N1</b><br><small>registro no caso</small>"]:::close
    hand["<b>Escalar ao SOC N2</b><br><small>pacote de handoff</small>"]
  end
  subgraph n2["SOC N2"]
    anal["<b>Analisar e correlacionar</b><br><small>busca retroativa · impacto</small>"]
    susp{"Sucesso ou<br>suspeita?"}
    encn2["<b>Encerrar no N2</b><br><small>registro no caso</small>"]:::close
  end
  subgraph cs["CSIRT"]
    inv["<b>Investigar</b><br><small>escopo · evidências</small>"]
    conf{"Incidente<br>confirmado?"}
    desc["Encerrar na<br>fila do CSIRT"]:::neutral
    conter["<b>Conter, erradicar<br>e recuperar</b>"]
    pos["<b>Pós-incidente</b><br><small>IOCs · lições aprendidas</small>"]:::close
  end
  subgraph ap["Times de apoio"]
    dfir["DFIR"]:::support
    ti["Threat Intel"]:::support
    iam["IAM"]:::support
  end
  alerta --> dup
  dup -->|sim| vinc
  dup -->|não| ader
  ader -.->|não| outro
  ader -->|sim| ramo
  ramo --> r
  r --> est
  est -->|sim| encn1
  est -->|não| hand
  hand -.->|handoff| anal
  anal --> susp
  susp -->|não| encn2
  susp ==>|escala| inv
  inv --> conf
  conf -->|não| desc
  conf -->|sim| conter
  conter --> pos
  inv -.->|aciona| dfir
  inv -.-> ti
  conter -.-> iam
  %% @refs alerta T0
  %% @refs dup T0
  %% @refs vinc T0
  %% @refs ader T1
  %% @refs outro T1, sec:objetivo-e-escopo
  %% @refs ramo T2
  %% @refs r R{{ramo.n}}
  %% @refs est T3, T4
  %% @refs encn1 T5
  %% @refs hand T6
  %% @refs anal A1, A2, A3
  %% @refs susp A4, A5
  %% @refs encn2 A5
  %% @refs inv I1, I2, I3
  %% @refs conf I4
  %% @refs desc I4
  %% @refs conter C1, C2, C3, C4
  %% @refs pos P1, P2, P3
  %% @refs dfir I5
  %% @refs ti I5, P1
  %% @refs iam C2
  %% @pos alerta 44 34 96 48
  %% @pos dup 164 24 120 68
  %% @pos vinc 164 118 120 44
  %% @pos ader 316 24 128 68
  %% @pos outro 318 118 124 44
  %% @pos ramo 480 24 128 68
  %% @pos r 44 196 110 92
  %% @pos est 300 318 150 68
  %% @pos encn1 44 326 176 52
  %% @pos hand 290 420 170 56
  %% @pos anal 290 24 170 60
  %% @pos susp 305 112 140 68
  %% @pos encn2 44 122 176 48
  %% @pos inv 290 24 170 60
  %% @pos conf 305 112 140 68
  %% @pos desc 44 124 160 44
  %% @pos conter 520 118 170 56
  %% @pos pos 520 206 170 56
  %% @pos dfir 210 20 80 44
  %% @pos ti 440 20 110 44
  %% @pos iam 700 20 80 44
  %% @route ramo>r 0.5,1 0.5,0 n1:544,170 n1:99,170
  %% @route r>est 0.5,1 0.5,0 n1:99,302 n1:375,302
  %% @route est>encn1 0,0.5 1,0.5
  %% @route susp>encn2 0,0.5 1,0.5
  %% @route conf>desc 0,0.5 1,0.5
  %% @route conf>conter 1,0.5 0,0.5
  %% @route inv>dfir 0,0.5 0.5,0 cs:250,54
  %% @route inv>ti 1,0.5 0.5,0 cs:495,54
  %% @route conter>iam 1,0.5 0.5,0 cs:740,146
"""

def _tbl(head, rows): return {"t": "table", "head": head, "rows": rows}
def _p(text): return {"t": "p", "text": text}
def _ul(items): return {"t": "ul", "items": items}
STEP_HEAD = ["ID", "Ação", "Critério de saída"]

def default_doc():
    return {"title": "{{id}} — {{nome}}", "byline": "Versão 0.1 · {{data}} · {{autor}}", "sections": [
        {"title": "Propriedades do playbook", "subs": [], "blocks": [_tbl(["Campo", "Valor"], [
            ["ID", "{{id}}"], ["Nome", "{{nome}}"], ["Versão", "0.1 (rascunho)"], ["Owner do documento", "{{owner}}"],
            ["Fase NIST", "{{nist}}"], ["Tática MITRE principal", "{{mitre}}"], ["Ramos", "{{ramos.lista}}"],
            ["Times envolvidos", "SOC N1, SOC N2, CSIRT e times de apoio conforme o caso"],
            ["Documentos de referência", "Plano de resposta a incidentes da organização"]])]},
        {"title": "Fluxograma-mapa", "subs": [], "blocks": [
            _p("O fluxograma é o mapa de operação: cada caixa corresponde a um passo deste documento. A fonte editável é o arquivo **{{arquivo_drawio}}**."),
            _p("Setas tracejadas: âmbar = handoff ao SOC N2 · vermelha = escalonamento ao CSIRT · roxa = outro playbook · cinza = acionamento de time de apoio.")]},
        {"title": "Objetivo e escopo", "subs": [], "blocks": [
            _p("{{objetivo}}"), _p("Pergunta central da triagem: **{{pergunta}}**"),
            _p("**Fora do escopo** (redirecionar para o playbook indicado):"), _tbl(["Caso", "Vai para"], [["", ""]])]},
        {"title": "Regras do playbook", "subs": [], "blocks": [_ul([
            "**Todo caso sobe por níveis:** SOC N1 → SOC N2 → CSIRT.",
            "**Nenhum caso volta de nível.** O CSIRT não devolve ao SOC e o SOC N2 não devolve ao SOC N1.",
            "**Times de apoio são acionados pelo CSIRT**, com o motivo registrado no caso.",
            "**Evidências são preservadas antes de qualquer contenção.**",
            "**Contenção que pode afetar a disponibilidade** é validada com o responsável pelo ativo antes de executar."])]},
        {"title": "Tabela de decisão da triagem", "subs": [], "blocks": [
            _p("O SOC N1 classifica o alerta em um dos estados abaixo. O estado decide o destino."),
            _tbl(["Estado", "Definição", "Destino", "Prioridade"], [
                ["E1 Falso positivo", "Atividade legítima ou regra imprecisa", "Encerrar no N1", "Original"],
                ["E2 Tentativa sem sucesso", "Bloqueada, sem indício de impacto", "Encerrar no N1 (se não recorrente)", "Original"],
                ["E3 Inconclusivo", "Não foi possível determinar o resultado", "SOC N2", "Elevada"],
                ["E4 Sucesso ou impacto", "Há indício de comprometimento", "SOC N2, que escala ao CSIRT", "Alta"]])]},
        {"title": "Fluxo de resposta por fase", "blocks": [
            _p("Cada passo segue o formato **verbo + o quê → critério de saída**. O ID do passo é o que se registra no caso.")], "subs": [
            {"title": "Fase 1 · Triagem — SOC N1", "blocks": [_tbl(STEP_HEAD, [
                ["T0", "Verificar se há caso aberto com a mesma origem ou o mesmo alvo", "Duplicado: vincular e encerrar. Senão, seguir para T1"],
                ["T1", "Confirmar aderência ao playbook", "Não aderente: redirecionar conforme Fora do escopo"],
                ["T2", "Definir o ramo", "Ramo R1 a R{{ramos.total}} registrado"],
                ["T3", "Enriquecer origem, alvo e contas envolvidas", "Contexto registrado"],
                ["T4", "Classificar o estado (E1 a E4) e ajustar a prioridade", "Estado e prioridade registrados"],
                ["T5", "E1 ou E2: encerrar com registro", "Caso encerrado no N1"],
                ["T6", "Demais casos: montar o pacote de handoff e escalar ao SOC N2", "Pacote completo no caso"]])]},
            {"title": "Fase 2 · Análise — SOC N2", "blocks": [_tbl(STEP_HEAD, [
                ["A1", "Revisar o pacote do N1 e confirmar estado e ramo", "Classificação mantida ou corrigida com justificativa"],
                ["A2", "Correlacionar eventos e buscar os indicadores retroativamente", "Caso isolado ou campanha"],
                ["A3", "Validar o impacto no alvo", "Impacto confirmado, descartado ou indeterminado"],
                ["A4", "Executar contenção simples, se cabível", "Contenção registrada com horário"],
                ["A5", "Decidir: sem sucesso, encerrar; sucesso ou suspeita, escalar ao CSIRT", "Destino registrado com justificativa"]])]},
            {"title": "Fase 3 · Investigação — CSIRT", "blocks": [_tbl(STEP_HEAD, [
                ["I1", "Validar o escopo inicial: ativos, contas e janela de tempo", "Escopo registrado"],
                ["I2", "Preservar evidências", "Evidências coletadas ou inviabilidade registrada"],
                ["I3", "Investigar o alcance", "Atividades do atacante mapeadas"],
                ["I4", "Decidir se há incidente", "Descartado: encerrar. Confirmado: seguir"],
                ["I5", "Acionar os times de apoio necessários", "Times acionados com escopo definido"]])]},
            {"title": "Fase 4 · Contenção, erradicação e recuperação — CSIRT", "blocks": [_tbl(STEP_HEAD, [
                ["C1", "Definir as ações de contenção pelo ramo", "Ações e alvos definidos"],
                ["C2", "Validar impacto em disponibilidade e executar a contenção", "Contenção concluída e verificada"],
                ["C3", "Erradicar: remover artefatos e corrigir a causa", "Ambiente sem artefatos"],
                ["C4", "Recuperar e monitorar", "Serviço restabelecido sob monitoração"]])]},
            {"title": "Fase 5 · Pós-incidente — CSIRT", "blocks": [_tbl(STEP_HEAD, [
                ["P1", "Compartilhar IOCs e TTPs finais", "Compartilhamento registrado"],
                ["P2", "Registrar a classificação final do incidente", "Campos preenchidos no caso"],
                ["P3", "Conduzir as lições aprendidas e propor ajustes", "Ajustes registrados no histórico"]])]}]},
        {"title": ramos.SECTION, "blocks": [_p("Cada ramo descreve o cenário, o que conta como sucesso e a contenção de cada time.")],
         "subs": [{"title": "R{{ramo.n}} · {{ramo.nome}}", "blocks": [_tbl(["Item", "Conteúdo"],
                   [[x, "{{ramo.pergunta}}" if x == "É sucesso quando" else ""] for x in ramos.DETAIL_ROWS])]}]},
        {"title": "Critérios de encerramento", "subs": [], "blocks": [_tbl(["Time", "Encerra quando", "Nunca encerra quando"], [
            ["SOC N1", "E1 ou E2, com registro no caso", "Há qualquer indício de sucesso"],
            ["SOC N2", "Ausência de sucesso comprovada após análise", "Impacto confirmado"],
            ["CSIRT", "Incidente descartado, ou recuperação concluída e lições aprendidas registradas", "Classificação final não registrada"]])]},
        {"title": "Itens em aberto e histórico", "subs": [], "blocks": [
            _p("**Itens em aberto**"), _ul(["[ ] Validar este rascunho com o time"]),
            _p("**Histórico de versões**"), _tbl(["Versão", "Data", "Alteração"], [["0.1", "{{data}}", "Rascunho inicial"]])]},
    ]}

def seed_default():
    flow, refs, _ = flowdsl.parse(DEFAULT_FLOW, DEFAULT_TEAMS)
    for n in flow["nodes"]:
        if n["type"] == "support": n["team"] = " ".join(l["t"] for l in n["lines"])
    return {"name": "Padrão", "description": "Template inicial: triagem no SOC N1, análise no SOC N2, resposta no CSIRT, ramos e times de apoio de segurança.",
            "owner": "CSIRT", "nist": "Detecção e Análise → Pós-Incidente (ciclo completo)",
            "doc": default_doc(), "flow": flow, "refs": refs, "teams": copy.deepcopy(DEFAULT_TEAMS), "updated_by": "sistema"}

def basic_teams():
    """SOC N1, SOC N2 e CSIRT como estão no template Padrão (ou a definição de fábrica)."""
    try: own = load(DEFAULT_KEY, {}).get("teams", {})
    except TemplateError: own = {}
    return {k: copy.deepcopy(own.get(k) or DEFAULT_TEAMS[k]) for k in BASIC_TEAMS}

def blank(name, catalog=None):
    """Template em branco: estrutura mínima, só os times SOC N1, SOC N2 e CSIRT, já com ramos."""
    doc = {"title": "{{id}} — {{nome}}", "byline": "Versão 0.1 · {{data}} · {{autor}}", "sections": [
        {"title": "Propriedades do playbook", "subs": [], "blocks": [_tbl(["Campo", "Valor"], [
            ["ID", "{{id}}"], ["Nome", "{{nome}}"], ["Versão", "0.1 (rascunho)"], ["Owner do documento", "{{owner}}"],
            ["Fase NIST", "{{nist}}"], ["Tática MITRE principal", "{{mitre}}"], ["Ramos", "{{ramos.lista}}"]])]},
        {"title": "Objetivo e escopo", "subs": [], "blocks": [_p("{{objetivo}}"), _p("Pergunta central da triagem: **{{pergunta}}**")]},
        {"title": "Fluxo de resposta por fase", "blocks": [], "subs": [
            {"title": "Fase 1 · Triagem — SOC N1", "blocks": [_tbl(STEP_HEAD, [
                ["T0", "Receber o alerta e confirmar aderência ao playbook", "Alerta aderente"],
                ["T1", "Definir o ramo", "Ramo R1 a R{{ramos.total}} registrado"]])]}]},
        {"title": ramos.SECTION, "blocks": [_p("Cada ramo descreve o cenário, o que conta como sucesso e a contenção de cada time.")],
         "subs": [{"title": "R{{ramo.n}} · {{ramo.nome}}", "blocks": [_tbl(["Item", "Conteúdo"],
                   [[x, "{{ramo.pergunta}}" if x == "É sucesso quando" else ""] for x in ramos.DETAIL_ROWS])]}]},
    ]}
    lanes = [l for l in core.lanes_of({}) if l.get("team") in BASIC_TEAMS]
    flow = {"subtitle": "", "lanes": lanes, "nodes": [
        {"id": "alerta", "lane": "n1", "x": 68.0, "y": 34.0, "w": 96.0, "h": 48.0, "type": "start", "lines": [{"t": "Alerta", "s": "n"}]},
        {"id": "ramo", "lane": "n1", "x": 182.0, "y": 24.0, "w": 140.0, "h": 68.0, "type": "decision",
         "lines": [{"t": "Ramo", "s": "n"}, {"t": "R1 a R{{ramos.total}}", "s": "n"}]},
        {"id": "r", "lane": "n1", "x": 197.0, "y": 132.0, "w": 110.0, "h": 92.0, "type": "action",
         "lines": [{"t": "R{{ramo.n}} {{ramo.nome}}", "s": "b"}, {"t": "{{ramo.pergunta}}", "s": "m"}]}],
        "edges": [
            {"id": "e1", "from": "alerta", "to": "ramo", "label": "", "type": "flow", "exit": None, "entry": None, "wps": []},
            {"id": "e2", "from": "ramo", "to": "r", "label": "", "type": "flow", "exit": None, "entry": None, "wps": []}]}
    refs = {"alerta": ["T0"], "ramo": ["T1"], "r": ["R{{ramo.n}}"]}
    return {"name": name, "description": "", "owner": "", "nist": "", "doc": doc, "flow": flow, "refs": refs, "teams": basic_teams()}

def has_ramos(t):
    return ramos.PROTO in ramos.doc_ramos(t["doc"]) or ramos.PROTO in ramos.flow_ramos(t["flow"], t.get("refs", {}))

def add_ramos(t):
    """Acrescenta o ramo-protótipo (subseção + caixa) a um template que não tem."""
    t["refs"] = t.get("refs") or {}
    ramos.add(t["doc"], t["flow"], t["refs"], ramos.PROTO, "{{ramo.nome}}", "{{ramo.pergunta}}")
    return t

def used_teams(flow):
    return {l["team"] for l in core.lanes_of(flow) if l.get("team")} | {n["team"] for n in flow["nodes"] if n.get("team")}

def sync_teams(t, catalog):
    """Times usados no fluxograma (raias e caixas de apoio) que vieram de outro template entram na lista deste."""
    tm, added = t.setdefault("teams", {}), []
    for n in used_teams(t["flow"]):
        if n not in tm and n in catalog: tm[n] = copy.deepcopy(catalog[n]); added.append(n)
    return added

# ───────────────────────── times de todos os templates ─────────────────────────

TEAMS_BLOCK = re.compile(r"<!--\s*medusa:teams\s*\n(.*?)\n-->", re.S)
_cache = {"sig": None, "teams": {}}

def _files():
    fs = sorted(TPL_DIR.glob(f"*{SUFFIX}"))
    return sorted(fs, key=lambda f: f.name != f"{DEFAULT_KEY}{SUFFIX}")      # Padrão primeiro

def teams_of_file(f):
    m = TEAMS_BLOCK.search(f.read_text("utf-8"))
    try: d = json.loads(m.group(1)) if m else {}
    except ValueError: d = {}
    return {k: v for k, v in d.items() if isinstance(v, dict)} if isinstance(d, dict) else {}

def all_teams():
    """União dos times de todos os templates (o Padrão prevalece em nomes repetidos). Em cache até um template mudar."""
    fs = _files()
    sig = tuple((f.name, f.stat().st_mtime_ns, f.stat().st_size) for f in fs)
    if sig != _cache["sig"]:
        out = {}
        for f in fs:
            for k, v in teams_of_file(f).items(): out.setdefault(k, v)
        _cache.update(sig=sig, teams=out)
    return copy.deepcopy(_cache["teams"])

core.set_teams_provider(all_teams)

def ensure_seed():
    TPL_DIR.mkdir(parents=True, exist_ok=True)
    if not path_of(DEFAULT_KEY).exists():
        save(DEFAULT_KEY, seed_default())
        return True
    return False

# ───────────────────────── criação de playbook a partir do template ─────────────────────────

def _subst(s, vars_):
    return VAR_RE.sub(lambda m: str(vars_.get(m.group(1), m.group(0))), s)

def _map(obj, fn):
    if isinstance(obj, str): return fn(obj)
    if isinstance(obj, list): return [_map(x, fn) for x in obj]
    if isinstance(obj, dict): return {k: (_map(v, fn) if k not in ("id", "lane", "from", "to", "type", "key", "kind", "s") else v) for k, v in obj.items()}
    return obj

def _has_ramo(obj):
    return bool(RAMO_RE.search(json.dumps(obj, ensure_ascii=False)))

def _expand_blocks(blocks, rvars):
    out = []
    for b in blocks:
        if b["t"] == "table":
            rows = []
            for r in b["rows"]:
                rows += [[_subst(c, rv) for c in r] for rv in rvars] if _has_ramo(r) else [r]
            out.append({**b, "rows": rows})
        elif b["t"] == "ul":
            items = []
            for it in b["items"]:
                items += [_subst(it, rv) for rv in rvars] if _has_ramo(it) else [it]
            out.append({**b, "items": items})
        elif b["t"] in ("p", "quote") and _has_ramo(b):
            out += [{**b, "text": _subst(b["text"], rv)} for rv in rvars]
        else:
            out.append(b)
    return out

def _expand_doc(doc, rvars):
    doc = copy.deepcopy(doc)
    for sec in doc["sections"]:
        subs = []
        for sub in sec.get("subs", []):
            if RAMO_RE.search(sub["title"]):
                subs += [_map(copy.deepcopy(sub), lambda s, rv=rv: _subst(s, rv)) for rv in rvars]
            else:
                subs.append(sub)
        sec["subs"] = subs
        sec["blocks"] = _expand_blocks(sec["blocks"], rvars)
        for sub in sec["subs"]: sub["blocks"] = _expand_blocks(sub["blocks"], rvars)
    return doc

def _expand_flow(flow, refs, rvars):
    flow, refs = copy.deepcopy(flow), copy.deepcopy(refs)
    protos = [n for n in flow["nodes"] if any(RAMO_RE.search(l["t"]) for l in n["lines"])]
    if not protos: return flow, refs
    used = {n["id"] for n in flow["nodes"] if n not in protos} | {e["id"] for e in flow["edges"]}
    def uniq(base):
        k, i = base, 2
        while k in used: k = f"{base}_{i}"; i += 1
        used.add(k); return k
    pid = {p["id"] for p in protos}
    inst = {}                                  # (id do protótipo, i) → id da cópia
    nodes = [n for n in flow["nodes"] if n["id"] not in pid]
    for p in protos:
        for i, rv in enumerate(rvars):
            c = copy.deepcopy(p)
            c["id"] = uniq(f"{p['id']}{i + 1}")
            c["x"] = p["x"] + i * (p["w"] + REPEAT_GAP)
            c["lines"] = [{"t": _subst(l["t"], rv), "s": l["s"]} for l in p["lines"]]
            c["lines"] = [l for l in c["lines"] if l["t"].strip()] or [{"t": f"R{i + 1}", "s": "b"}]
            inst[(p["id"], i)] = c["id"]
            nodes.append(c)
            if p["id"] in refs: refs[c["id"]] = [_subst(r, rv) for r in refs[p["id"]]]
        refs.pop(p["id"], None)
    edges = []
    for e in flow["edges"]:
        if e["from"] not in pid and e["to"] not in pid:
            edges.append(e); continue
        proto = next(p for p in protos if p["id"] in (e["from"], e["to"]))
        for i, rv in enumerate(rvars):
            c = copy.deepcopy(e)
            c["id"] = uniq(f"{e['id']}{i + 1}")
            c["from"] = inst.get((e["from"], i), e["from"]); c["to"] = inst.get((e["to"], i), e["to"])
            c["label"] = _subst(e.get("label", ""), rv)
            dx = i * (proto["w"] + REPEAT_GAP)
            c["wps"] = [{**w, "x": w["x"] + dx} if w["lane"] == proto["lane"] and proto["x"] <= w["x"] <= proto["x"] + proto["w"] else w
                        for w in e.get("wps", [])]
            edges.append(c)
    flow["nodes"], flow["edges"] = nodes, edges
    return flow, refs

def instantiate(t, m):
    """m: id, name, author (nome), date, owner, nist, mitre (texto), objective, question, ramos [{name, q}]."""
    ramos = [r for r in m.get("ramos", []) if str(r.get("name", "")).strip()]
    if uses_ramos(t) and not ramos: raise TemplateError("Este template usa ramos: informe pelo menos um")
    rvars = [{"ramo.n": str(i + 1), "ramo.id": f"R{i + 1}", "ramo.nome": r["name"].strip(), "ramo.pergunta": str(r.get("q", "")).strip()}
             for i, r in enumerate(ramos)]
    g = {"id": m["id"], "nome": m["name"], "autor": m.get("author", ""), "data": m.get("date", ""),
         "owner": m.get("owner") or t.get("owner") or "", "nist": m.get("nist") or t.get("nist") or "",
         "mitre": m.get("mitre", ""), "objetivo": m.get("objective", "").strip() or "Descrever o tipo de alerta que este playbook trata.",
         "pergunta": m.get("question", "").strip() or "(definir)", "ramos.total": str(len(ramos)),
         "ramos.lista": ", ".join(f"R{i + 1} {r['name'].strip()}" for i, r in enumerate(ramos)),
         "arquivo_drawio": f"{m['id'].lower()}-{core.slug(m['name'])}.drawio"}
    doc = _map(_expand_doc(t["doc"], rvars), lambda s: _subst(s, g))
    flow, refs = _expand_flow(t["flow"], t.get("refs", {}), rvars)
    flow = _map(flow, lambda s: _subst(s, g))
    refs = {k: [_subst(r, g) for r in v] for k, v in refs.items()}
    for n in flow["nodes"]:
        n["lines"] = [l for l in n["lines"] if l["t"].strip()] or [{"t": n["id"], "s": "n"}]
    return doc, flow, refs, copy.deepcopy(t.get("teams", {}))
