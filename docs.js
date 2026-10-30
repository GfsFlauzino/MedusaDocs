"use strict";
/* Documentação da plataforma (aba DOCs). Cada seção indica o perfil mínimo que a enxerga:
   o visualizador lê o guia de leitura; editores veem edição, templates e ramos; administradores, tudo. */
const Docs = (() => {
  const K = s => `<kbd>${s}</kbd>`;
  const SECTIONS = [
    { id: "visao-geral", role: "viewer", title: "Visão geral", html: `
      <p>O Medusa Docs é a base interativa dos playbooks de resposta a incidentes. Cada playbook tem um <b>documento</b> (as regras, fases, ramos e critérios) e um <b>fluxograma</b> (o mapa de operação por time).</p>
      <ul><li><b>Fonte da verdade:</b> cada playbook é um par de arquivos <code>.md</code> + <code>.drawio</code> na pasta <code>playbooks/PB-xx-…/</code>, que podem ir para o Confluence, Git ou draw.io. A ferramenta lê e grava esses arquivos.</li>
        <li><b>Abas:</b> cada playbook ou página aberta vira uma aba no topo, como num navegador. ${K(ic("close"))} fecha; clique do meio também. As abas ficam guardadas no seu navegador. Se você sair de uma aba de edição sem salvar, nada se perde: a aba ganha um ponto e as alterações voltam quando você retorna a ela (só fechar a aba ou descartar apagam o rascunho).</li>
        <li><b>Busca:</b> ${K("/")} foca a busca; encontra playbooks, passos (T0, A3…), ramos, seções e times em todos os playbooks que você pode ver, sem precisar de acento. ${K("↑")} ${K("↓")} escolhem o resultado e ${K("Enter")} abre.</li>
        <li><b>Menu lateral:</b> logo e nome do workspace, busca, <b>Playbooks</b>, <b>Templates</b> (editores) e <b>Administração</b> (administradores). O ${ic("menu")} no canto da barra de abas (ou a tecla ${K("[")}) recolhe e expande o menu; a escolha fica guardada no navegador. Em telas estreitas o menu vira uma gaveta: ${K("Esc")} ou o ${ic("close")} fecham.</li>
        <li><b>Menu do perfil</b> (seu nome, no rodapé da barra lateral): documentação, troca de senha e sair.</li>
        <li><b>Tema:</b> o botão ${ic("sun")}/${ic("moon")}, ao lado do perfil, alterna claro e escuro (vale para você, neste navegador). As cores do fluxograma seguem o modelo e não mudam com o tema.</li>
        <li><b>Página inicial:</b> os botões ao lado de "Novo playbook" alternam a lista entre <b>cartões</b>, <b>lista grande</b> (com template, revisão, ramos e passos) e <b>lista pequena</b> (uma linha por playbook, boa para muitos playbooks). A escolha fica guardada no seu navegador.</li></ul>` },
    { id: "perfis", role: "viewer", title: "Papéis e permissões", html: `
      <p>Cada usuário tem um <b>papel</b>, e cada papel uma lista de permissões. Os três papéis do sistema:</p>
      <table><thead><tr><th>Papel</th><th>Vê</th><th>Pode</th></tr></thead><tbody>
        <tr><td>Visualizador</td><td>Playbooks em <b>Homologação</b> e <b>Produção</b></td><td>Ler, buscar, exportar e trocar a própria senha</td></tr>
        <tr><td>Editor</td><td>Todos, inclusive <b>Desenvolvimento</b></td><td>Criar, editar e importar playbooks, mudar status, aprovar, restaurar versões, editar templates, times e tags</td></tr>
        <tr><td>Administrador</td><td>Todos</td><td>Tudo, inclusive usuários, papéis, aparência, auditoria, logs, SSO e exclusões. Não pode ser alterado</td></tr></tbody></table>
      <p>O administrador cria outros papéis em <b>Administração → Papéis</b>, marcando por tipo de documento e por ação o que cada um pode fazer (ver, ver rascunhos, criar, editar, alterar status, aprovar, restaurar, importar, exportar, excluir) e as permissões da plataforma (templates, usuários, papéis, auditoria, logs, SSO, aparência, reset).
        O seu papel aparece no menu do perfil. As permissões são verificadas no servidor: quem não pode ver rascunhos nem recebe os playbooks em Desenvolvimento.</p>` },
    { id: "papeis", role: "admin", title: "Gerenciar papéis", html: `
      <p><b>${ic("settings")}Administração → Papéis</b>: à esquerda a lista (com quantos usuários usam cada um); à direita o editor.</p>
      <ul><li><b>Matriz:</b> linhas são as ações, colunas os tipos de documento. Clique no nome da linha ou da coluna para marcar ou desmarcar tudo. Abaixo, as permissões da plataforma.</li>
        <li><b>Novo papel</b> ou <b>Duplicar</b> um existente. A <b>prioridade</b> decide qual papel vence quando o usuário do SSO está em mais de um grupo mapeado.</li>
        <li><b>Editor</b> e <b>Visualizador</b> podem ser ajustados e têm <b>Restaurar padrão</b>; <b>Administrador</b> não muda. Papéis do sistema não podem ser excluídos.</li>
        <li>Excluir um papel em uso pede para qual papel os usuários vão.</li>
        <li>Ninguém concede o que não tem: quem gerencia papéis sem ser administrador vê desabilitadas as permissões que não possui e não mexe em papéis mais fortes que o seu.</li>
        <li>As mudanças valem na hora (na próxima ação de cada usuário) e vão para a auditoria (<code>papel_criado</code>, <code>papel_alterado</code> com o que entrou e saiu, <code>papel_excluido</code>).</li></ul>` },
    { id: "leitura", role: "viewer", title: "Lendo um playbook", html: `
      <ul><li><b>Fluxograma:</b> clique em uma caixa para ler o trecho da documentação vinculado a ela (passos, ramo, seção). Clique no nome de um time (raia ou caixa de apoio) para ver as responsabilidades e o que ele não faz. A etiqueta no canto da caixa mostra o ID do passo.</li>
        <li><b>Documentação:</b> o documento completo, com índice lateral por seção e subseção: fases e passos (ID, ação, critério de saída), ramos R1, R2…, critérios e o restante. Clique numa imagem para ampliar (${K("Esc")} fecha).</li>
        <li>A busca (${K("/")}) leva direto ao passo ou ramo dentro da documentação, com destaque.</li>
        <li>No texto, IDs como <b>T3</b>, <b>R2</b> ou <b>E4</b> e nomes de times são clicáveis.</li></ul>` },
    { id: "versoes", role: "viewer", title: "Versões e histórico", html: `
      <p>Cada playbook tem número de versão automático, no cabeçalho e na tabela de propriedades:</p>
      <table><thead><tr><th>Situação</th><th>Versão</th><th>Exemplo</th></tr></thead><tbody>
        <tr><td>Gravação em Desenvolvimento ou Homologação</td><td>soma 1 depois do ponto</td><td>0.1 → 0.2 · 2.3 → 2.4</td></tr>
        <tr><td>Publicação em Produção</td><td>próxima versão cheia</td><td>0.4 → 1.0 · 2.4 → 3.0</td></tr>
        <tr><td>Alteração em Produção do tipo <b>Minor</b></td><td>soma 1 depois do ponto</td><td>1.0 → 1.1 · 2.3 → 2.4</td></tr>
        <tr><td>Alteração em Produção do tipo <b>Major</b></td><td>soma 1 antes do ponto</td><td>1.4 → 2.0</td></tr>
        <tr><td>Republicar sem nenhuma alteração</td><td>mantém</td><td>1.0 → 1.0</td></tr></tbody></table>
      <p>Em Produção, toda gravação (documento, fluxograma ou restauração de versão) pede o <b>tipo da atualização</b> e uma <b>descrição das alterações</b>. A descrição aparece no histórico e na auditoria.</p>
      <p>A aba <b>Versões</b> lista o histórico (quem, quando, o que mudou). Em cada versão:</p>
      <ul><li><b>Ler</b>: abre a versão como documentação completa, com o fluxograma clicável, como era naquele momento. Dá para baixar em HTML ou imprimir.</li>
        <li><b>Comparar</b>: mostra linhas do documento e caixas/setas do fluxograma acrescentadas (+) e removidas (−) entre duas versões, ou contra a atual.</li>
        <li><b>Restaurar</b> (editores): volta o conteúdo daquela versão. O status atual e o histórico são mantidos; a restauração vira uma versão nova.</li></ul>
      <p>Visualizadores veem as versões que estiveram em Homologação ou Produção.</p>` },
    { id: "exportar", role: "viewer", title: "Exportar", html: `
      <p>O botão <b>${ic("download")}Exportar</b> do playbook está disponível para todos os perfis:</p>
      <table><thead><tr><th>Formato</th><th>Uso</th></tr></thead><tbody>
        <tr><td>Markdown <code>.md</code></td><td>documento para Confluence, Git ou qualquer editor. Com imagens, vem um <code>.zip</code> com o <code>.md</code> e a pasta <code>imagens/</code></td></tr>
        <tr><td>HTML com fluxograma</td><td>abre em qualquer navegador ou no Word; as imagens vão dentro do arquivo</td></tr>
        <tr><td>Imprimir / PDF</td><td>documento completo com o fluxograma</td></tr>
        <tr><td>draw.io <code>.drawio</code></td><td>fluxograma editável no draw.io e no Confluence</td></tr>
        <tr><td>Mermaid <code>.mmd</code></td><td>fluxograma em texto (GitHub, GitLab, mermaid.live)</td></tr>
        <tr><td>SVG</td><td>imagem vetorial do fluxograma</td></tr>
        <tr><td>JPEG</td><td>imagem do fluxograma em alta resolução (2x), para apresentações, e-mail e tickets</td></tr>
        <tr><td>Medusa <code>.medusa.md</code></td><td>pacote completo (documento + imagens + times + fluxo), reimportável em outra instalação</td></tr></tbody></table>
      <p>Na página inicial, <b>Exportar todos</b> baixa um <code>.zip</code> com os playbooks que você pode ver. Toda exportação fica na auditoria.</p>` },
    { id: "ciclo", role: "editor", title: "Ciclo de vida e revisão", html: `
      <p><b>Desenvolvimento → Homologação → Produção</b>, pelo botão <b>${ic("swap")}Alterar status</b> do playbook.</p>
      <ul><li>Playbook criado ou importado começa em Desenvolvimento (visível só para editores).</li>
        <li>Homologação: validação com o time; visualizadores já leem.</li>
        <li>Produção exige um <b>aprovador</b>: usuário ativo cujo papel pode aprovar e que seja <b>outra pessoa</b>, diferente de quem está publicando e de quem fez a última alteração do conteúdo. A lista do diálogo já mostra só quem vale, e diz quem ficou de fora. A regra fica em <b>Administração → Aparência → Governança</b> (ligada por padrão). Playbooks que já estavam em Produção não mudam.</li>
        <li><b>Último revisor</b> e <b>data de revisão</b> são preenchidos a cada gravação. Os quatro campos ficam na tabela "Propriedades do playbook" e aparecem bloqueados (${ic("lock")}) no editor.</li>
        <li>Editar algo em Produção mostra um aviso: a alteração fica visível para todos na hora. Ao salvar, escolha <b>Minor</b> (ajuste: 2.3 → 2.4) ou <b>Major</b> (mudança de operação: 2.3 → 3.0) e descreva o que mudou. Para revisões maiores, volte antes para Homologação.</li></ul>` },
    { id: "criar", role: "editor", title: "Criar playbook", html: `
      <ol><li><b>${ic("plus")}Novo playbook</b> na página inicial.</li>
        <li>Escolha o <b>template</b> (documento, fluxograma, ramos e times iniciais).</li>
        <li>Preencha ID, nome, autor (usuários ativos), owner, fase NIST, táticas <b>MITRE ATT&amp;CK</b> (lista da versão mais recente) e escopo.</li>
        <li>Informe os <b>ramos</b>: cada um vira uma subseção no documento e uma caixa R no fluxograma.</li></ol>
      <p>O playbook fica ligado ao template escolhido: os times e tags dele são os do template (o cabeçalho do playbook mostra qual). O playbook abre direto no editor.</p>` },
    { id: "editar-documento", role: "editor", title: "Editar o documento", html: `
      <ul><li>Seções, subseções, parágrafos, listas, checklists, destaques e tabelas, sem código. ${K("Ctrl+S")} salva, ${K("Ctrl+B")} aplica negrito.</li>
        <li>Na tabela de propriedades, o botão ${ic("mitre")} da linha "Tática MITRE" abre a lista de táticas.</li>
        <li><b>Imagens</b> (prints de alerta, telas, evidências): <b>${ic("image")}Imagem</b> na barra "Adicionar" da seção, ou cole (${K("Ctrl+V")}) uma imagem copiada, ou arraste o arquivo para a seção. Entra logo depois do bloco em que o cursor está. PNG, JPG, WEBP ou GIF até 3 MB; a legenda é opcional. O arquivo vai para <code>imagens/</code> na pasta do playbook e o documento recebe <code>![legenda](imagens/img-….png)</code>, Markdown comum. Imagens nunca são sobrescritas, então versões antigas continuam mostrando as delas. Templates não recebem imagens.</li>
        <li><b>${ic("plus")}Novo ramo</b> (na seção de ramos) ou <b>${ic("plus")}Seção de ramos</b> (no índice, se ainda não houver) criam ramos; ver <a href="#/docs/ramos">Ramos</a>.</li>
        <li><b>Modo Markdown</b> (botão <b>${ic("code")}Markdown</b> na barra do editor): o documento inteiro como texto Markdown, com barra de formatação (negrito, itálico, seção, subseção, lista, checklist, destaque, tabela, código e imagem), prévia ao lado atualizada enquanto você digita e ${K("Ctrl+B")}/${K("Ctrl+I")}. Dá para alternar entre Visual e Markdown a qualquer momento; salvar funciona nos dois modos. Imagens também podem ser coladas ou arrastadas no texto.</li>
        <li><b>Descartar</b> recarrega a versão salva. Cada gravação guarda backup da versão anterior.</li>
        <li>Se outra pessoa salvou depois que você abriu, a gravação é recusada e a tela oferece recarregar (suas alterações continuam na tela para copiar).</li>
        <li>A linha <b>Versão</b> das propriedades é automática (${ic("lock")}): cada gravação gera uma versão nova, ver <a href="#/docs/versoes">Versões</a>.</li></ul>` },
    { id: "editar-fluxograma", role: "editor", title: "Editar o fluxograma", html: `
      <p>Só as formas, cores e setas do modelo estão disponíveis; cada caixa fica na raia do time responsável.</p>
      <table><thead><tr><th>Ação</th><th>Como</th></tr></thead><tbody>
        <tr><td>Criar caixa</td><td>clique numa forma da paleta e depois na raia, ou arraste a forma até a raia</td></tr>
        <tr><td>Trocar o time</td><td>arraste a caixa para outra raia (ou mude "Time responsável")</td></tr>
        <tr><td>Criar seta</td><td>selecione a caixa e arraste o círculo ao lado dela até o destino; o tipo (handoff, escalonamento, apoio) é sugerido pelas raias</td></tr>
        <tr><td>Lados da seta</td><td>selecione a seta e escolha "Sai pela" e "Chega pela" (topo, direita, base, esquerda)</td></tr>
        <tr><td>Pontos de dobra</td><td>na seta selecionada, clique no <b>+</b> no meio de um trecho (ou em <b>${ic("pointAdd")}Adicionar ponto</b>) para criar; arraste para ajustar; dois cliques no ponto (ou o ${ic("close")} na lista do painel) removem</td></tr>
        <tr><td>Rota fixa</td><td>com <b>${ic("lock")}Rota fixa</b> ligada, lados e pontos de dobra não mudam quando você move as caixas. Liga sozinha ao escolher um lado ou mexer num ponto; <b>Voltar à rota automática</b> desfaz tudo. Fica gravada no <code>.drawio</code> e no Mermaid</td></tr>
        <tr><td>Mover o texto da seta</td><td>arraste o rótulo (sim, não, handoff…); "Texto na posição automática" desfaz. A posição vai para o <code>.drawio</code></td></tr>
        <tr><td>Selecionar várias</td><td>${K("Shift")}/${K("Ctrl")}+clique, arrastar no fundo (laço) ou ${K("Ctrl+A")} / <b>${ic("selectAll")}Tudo</b></td></tr>
        <tr><td>Mover várias</td><td>arraste qualquer caixa selecionada ou use as setas do teclado; cada caixa mantém a raia</td></tr>
        <tr><td>Redimensionar proporcionalmente</td><td>arraste o quadrado no canto da seleção, ou use -10% / +10% / percentual no painel. Posições, tamanhos e dobras escalam juntos</td></tr>
        <tr><td>Alinhar e distribuir</td><td>no painel da seleção múltipla: esquerda, centro, direita, topo, meio, base, distribuir, mesma largura/altura</td></tr>
        <tr><td>Texto da caixa</td><td>linhas normal, <b>negrito</b> ou cinza (detalhe); ${ic("up")} reordena</td></tr>
        <tr><td>"Ao clicar"</td><td>vincule a caixa a passos, ramos, estados ou seções: é o que o analista lê</td></tr>
        <tr><td>Raias</td><td>sem seleção, o painel lista as raias: adicionar time central, reordenar, remover (vazia) ou criar novo time</td></tr></tbody></table>
      <p>Atalhos: ${K("Ctrl+Z")} desfaz, ${K("Ctrl+Shift+Z")} refaz, ${K("Del")} exclui, ${K("Ctrl+D")} duplica, ${K("Esc")} limpa a seleção, ${K("Ctrl+S")} salva.</p>
      <p>O modo <b>${ic("code")}Código</b> mostra o fluxo em Mermaid (ver <a href="#/docs/mermaid">Linguagem de fluxo</a>). A página 2 do <code>.drawio</code> é preservada ao salvar.</p>` },
    { id: "ramos", role: "editor", title: "Ramos (R1, R2…)", html: `
      <p>Ramo é um cenário do playbook (ex.: R1 Varredura, R2 Credenciais). Ele existe nos dois lados e fica <b>sincronizado</b>:</p>
      <table><thead><tr><th>Onde</th><th>Forma</th></tr></thead><tbody>
        <tr><td>Documento</td><td>subseção <code>R3 · Nome</code> (em "Ramos em detalhe"), com a tabela de detalhe; o item "É sucesso quando" é o indicador</td></tr>
        <tr><td>Fluxograma</td><td>caixa cujo texto começa com <code>R3</code> e que está vinculada a R3; a linha cinza é o indicador</td></tr></tbody></table>
      <p><b>Criar:</b> forma <b>Ramo</b> na paleta do fluxograma ou <b>${ic("plus")}Novo ramo</b> no editor de documento. Ao salvar, o outro lado recebe o ramo. No fluxograma, o ramo novo fica ao lado do último e copia as ligações dele; se não houver ramo ainda, liga-se à decisão "Ramo".</p>
      <p><b>Renomear / indicador:</b> altere de um lado e salve; o outro acompanha. <b>Excluir:</b> excluir a caixa ou a subseção remove o ramo do outro lado ao salvar (a tela confirma antes).</p>
      <p>O texto "R1 a Rn" (decisão de ramo, passo T2) é atualizado sozinho. A notificação depois de salvar lista o que foi sincronizado.</p>
      <p>Em <b>templates</b>, o ramo é o modelo <code>R{{ramo.n}} · {{ramo.nome}}</code>: na criação do playbook ele é repetido para cada ramo informado.</p>` },
    { id: "templates", role: "editor", title: "Templates", html: `
      <p>Barra lateral → <b>${ic("templates")}Templates</b>. O template define o documento modelo, o fluxograma modelo, os ramos e os times e tags que um playbook novo recebe.</p>
      <ul><li><b>Padrão</b>: o template inicial da instalação (não pode ser excluído). Raias SOC N1, SOC N2 e CSIRT, times de apoio de segurança (DFIR, Threat Intel, IAM, Vulnerabilidades, AppSec, Cloud Security, Infraestrutura, Privacidade), ramos e um ciclo completo: triagem, análise, investigação, contenção e pós-incidente.</li>
        <li><b>Novo em branco</b>: entrada <i>Alerta</i>, decisão de ramo com o ramo-modelo, seções mínimas e somente os times SOC N1, SOC N2 e CSIRT.</li>
        <li><b>Duplicar</b> parte de um template existente; <b>Exportar/Importar</b> usa o arquivo <code>.medusa-template.md</code>.</li>
        <li>Template sem ramos mostra <b>${ic("plus")}Adicionar ramos</b> na aba Geral.</li></ul>
      <p><b>Variáveis</b> (substituídas na criação): <code>{{id}}</code> <code>{{nome}}</code> <code>{{autor}}</code> <code>{{data}}</code> <code>{{owner}}</code> <code>{{nist}}</code> <code>{{mitre}}</code> <code>{{objetivo}}</code> <code>{{pergunta}}</code> <code>{{ramos.total}}</code> <code>{{ramos.lista}}</code> <code>{{arquivo_drawio}}</code>.
        O que contém <code>{{ramo.n}}</code>, <code>{{ramo.nome}}</code> ou <code>{{ramo.pergunta}}</code> (subseção, linha de tabela, item, parágrafo ou caixa) é repetido por ramo.</p>
      <p>Excluir template é exclusivo do administrador (vai para a lixeira). Os playbooks criados com ele passam para o template Padrão, que recebe os times que eles usam.</p>` },
    { id: "times", role: "editor", title: "Times e tags", html: `
      <p>Times e tags pertencem aos <b>templates</b>: cada template tem os seus, gerenciados na aba <b>Times e tags</b> do template (menu do perfil → Templates, times e tags).</p>
      <ul><li><i>Central</i> pode virar raia; <i>apoio/tag</i> vira caixa de apoio e tag clicável nos textos. Cada time tem cor, resumo, responsabilidades e o que não faz.</li>
        <li>Um playbook usa os times do template com que foi criado (ou importado). Em <b>${ic("edit")}Editar time</b> (ao clicar num time dentro do playbook), a alteração vale para o template e todos os playbooks dele.</li>
        <li>Template novo começa com SOC N1, SOC N2 e CSIRT. Dá para criar times, copiar de outro template ou tirar os que não usa.</li>
        <li>Um time usado no fluxograma do template ou em algum playbook dele não pode ser retirado.</li>
        <li>Usar no fluxograma um time de outro template o acrescenta ao template ao salvar.</li></ul>` },
    { id: "importar", role: "editor", title: "Importar", html: `
      <p><b>${ic("upload")}Importar</b> na página inicial aceita <code>.medusa.md</code> de qualquer instalação ou um <code>.md</code> comum (título <code># PB-00 — Nome</code> e seções <code>##</code>). A tela mostra uma prévia (seções, caixas, raias, times novos e avisos) antes de gravar.</p>
      <ul><li>Se o ID já existir: importar com outro ID ou, só administradores, substituir (o atual vai para a lixeira). Substituir equivale a excluir, por isso editores não podem.</li>
        <li>Escolha o <b>template</b> do playbook importado; times citados no arquivo que faltarem nele são acrescentados ao template, com a cor e a descrição do arquivo.</li>
        <li>O playbook importado entra em Desenvolvimento.</li></ul>` },
    { id: "mermaid", role: "editor", title: "Linguagem de fluxo (Mermaid)", html: `
      <p>O fluxograma pode ser escrito em texto no modo <b>&lt;/&gt; Código</b>. É Mermaid padrão (GitHub, GitLab, Confluence e mermaid.live desenham); as linhas <code>%% @…</code> guardam o que o Mermaid não tem.</p>
      <table><tbody>
        <tr><td><code>subgraph n1["SOC N1"]</code> … <code>end</code></td><td>raia</td></tr>
        <tr><td><code>a(["Alerta"])</code> · <code>a["Ação"]</code> · <code>a{"Pergunta?"}</code></td><td>início · ação · decisão</td></tr>
        <tr><td><code>:::close</code> <code>:::neutral</code> <code>:::attention</code> <code>:::crossref</code> <code>:::support</code></td><td>tipos do modelo</td></tr>
        <tr><td><code>a --&gt; b</code> · <code>a --&gt;|sim| b</code> · <code>a -.-&gt; b</code> · <code>a ==&gt; b</code></td><td>fluxo · com rótulo · tracejada · escalonamento</td></tr>
        <tr><td><code>%% @refs a T0, R1</code></td><td>o que o analista lê ao clicar</td></tr>
        <tr><td><code>%% @pos a x y l a</code> · <code>%% @route a&gt;b …</code> · <code>%% @label a&gt;b dx,dy</code></td><td>posição, dobras e texto da seta (opcionais)</td></tr></tbody></table>
      <p>Sem <code>@pos</code>, as caixas são posicionadas automaticamente ("Reorganizar automaticamente").</p>` },
    { id: "usuarios", role: "admin", title: "Usuários", html: `
      <p><b>${ic("settings")}Administração → Usuários</b>:</p>
      <ul><li><b>Criar:</b> login (3 a 80 caracteres: minúsculas, números, <code>. _ - @</code>), nome e papel. A senha temporária aparece uma única vez; o usuário é obrigado a trocá-la no primeiro acesso (mínimo 10 caracteres).</li>
        <li><b>Autenticação:</b> cada usuário entra por <b>senha local</b> ou pelo <b>SSO</b> (coluna de autenticação). Usuário SSO não tem senha na ferramenta; o login pode ser um e-mail (até 80 caracteres, com <code>@</code>).</li>
        <li><b>Redefinir senha</b> gera outra temporária e encerra as sessões. <b>Encerrar</b> derruba as sessões abertas.</li>
        <li><b>Desativar</b> bloqueia o acesso sem perder o histórico; <b>excluir</b> remove o usuário.</li>
        <li>Sempre há pelo menos um administrador ativo: a ferramenta não deixa rebaixar, desativar ou excluir o último.</li>
        <li>5 senhas erradas seguidas bloqueiam o login por 5 minutos. Sessões expiram após 8 h sem uso e, mesmo em uso, 24 h depois do login (ajustável em <code>MEDUSA_SESSION_IDLE_HOURS</code> e <code>MEDUSA_SESSION_MAX_HOURS</code>).</li></ul>` },
    { id: "logs", role: "admin", title: "Logs, encaminhamento e retenção", html: `
      <p><b>${ic("settings")}Administração → Logs e retenção</b>.</p>
      <ul><li><b>Retenção:</b> a auditoria é guardada por 30 dias (padrão, ajustável de 1 a 3650). O que for mais antigo é apagado automaticamente, assim como os arquivos de log do mesmo período. O histórico de versões dos playbooks não é afetado.</li>
        <li><b>Formato:</b> cada evento vira um documento JSON no padrão Elastic Common Schema (<code>@timestamp</code>, <code>event.action</code>, <code>event.outcome</code>, <code>user.name</code>, <code>source.ip</code>, <code>medusa.target</code>, <code>medusa.detail</code>…), aceito por Elastic, OpenSearch, Splunk, Sentinel, Graylog e Wazuh.</li></ul>
      <table><thead><tr><th>Destino</th><th>Como funciona</th></tr></thead><tbody>
        <tr><td>HTTP / HTTPS</td><td>POST de um array JSON por lote (até 200 eventos), com cabeçalho de autenticação opcional (ex.: <code>Authorization: Bearer …</code>). Até 3 tentativas</td></tr>
        <tr><td>Syslog</td><td>RFC 5424 por UDP ou TCP, com o JSON na mensagem</td></tr>
        <tr><td>Arquivo JSON Lines</td><td><code>data/logs/audit-AAAA-MM-DD.jsonl</code>, para Filebeat, Fluent Bit e outros agentes</td></tr></tbody></table>
      <p>O envio é em segundo plano e não atrasa a aplicação. Cada destino tem <b>Enviar evento de teste</b> e mostra enviados, falhas e o último erro. <b>Baixar auditoria</b> exporta o período em JSON Lines. Segredos (valor do cabeçalho) nunca voltam para a tela.</p>
      <p>Atrás de proxy reverso, defina <code>MEDUSA_TRUST_PROXY=1</code> para registrar o IP real do usuário (do cabeçalho <code>X-Forwarded-For</code>).</p>` },
    { id: "sso", role: "admin", title: "Login único (SSO)", html: `
      <p><b>${ic("settings")}Administração → SSO</b>, opcional, por <b>OpenID Connect</b> (Microsoft Entra ID, Okta, Keycloak, Google, Auth0, Authentik, ADFS…).</p>
      <ol><li>No provedor, crie um aplicativo web (cliente confidencial) com a <b>URL de redirecionamento</b> mostrada na tela: <code>https://SEU-ENDERECO/api/sso/callback</code>.</li>
        <li>Na ferramenta, informe o <b>emissor</b> (issuer), clique em <b>Testar</b>, preencha client ID, client secret e a <b>URL pública</b>, e ative.</li>
        <li>Opcional: indique a claim de grupos (<code>groups</code>, <code>roles</code>, <code>realm_access.roles</code>) e quais grupos viram cada papel (inclusive os criados). Se o usuário estiver em grupos de mais de um papel, vale o de maior prioridade. O papel é reaplicado a cada login.</li></ol>
      <ul><li><b>Usuário novo:</b> criado no primeiro login, ou só pré-cadastrados (Usuários → Autenticação: SSO, com o login igual ao enviado pelo provedor).</li>
        <li><b>Contas locais</b> não são vinculadas automaticamente a uma identidade do SSO (evita tomada de conta): converta em <b>Usuários</b>.</li>
        <li><b>Login por senha</b> pode continuar para todos ou ficar só para administradores (acesso de emergência).</li>
        <li><b>Segurança:</b> authorization code + PKCE, state amarrado ao navegador, nonce, e o ID token validado pela assinatura RS256 (chaves do provedor), emissor, audiência e validade. Falhas ficam na auditoria (<code>sso_falhou</code>).</li></ul>` },
    { id: "aparencia", role: "admin", title: "Aparência", html: `
      <p><b>${ic("settings")}Administração → Aparência</b>: o <b>nome do workspace</b> (barra lateral, login e aba do navegador) e a <b>logo</b> (PNG, SVG sem script, JPG ou WEBP até 512 KB; prefira fundo transparente: a prévia mostra os temas claro e escuro). O restante do visual é fixo; cada usuário escolhe o tema claro ou escuro. As cores do fluxograma seguem o modelo dos playbooks.</p>` },
    { id: "reset", role: "admin", title: "Resetar a aplicação", html: `
      <p><b>${ic("settings")}Administração → Resetar aplicação</b> (botão no topo da página) volta a instalação ao estado de recém-configurada: saem todos os playbooks, templates e o histórico de versões, e o template <b>Padrão</b> é recriado. Opcionalmente também:</p>
      <ul><li><b>Configurações:</b> aparência, logs e SSO voltam ao padrão (indisponível para quem entrou pelo SSO, que seria desligado);</li>
        <li><b>Usuários:</b> exclui todos os outros usuários; fica só quem fez o reset;</li>
        <li><b>Auditoria:</b> apaga os eventos e os arquivos de log (o próprio reset fica registrado).</li></ul>
      <p>A confirmação é igual à da exclusão de playbook: digite <b>RESETAR</b>. Nada é apagado de vez: playbooks, templates, vínculos, backups e uma <b>cópia do banco</b> vão para <code>data/lixeira/reset__&lt;data-hora&gt;/</code>, com um <code>LEIA-ME.txt</code> explicando como voltar (pare o servidor, copie os itens de volta, <code>playbooks.db</code> em <code>data/</code>, e inicie).</p>` },
    { id: "auditoria", role: "admin", title: "Auditoria", html: `
      <p><b>${ic("settings")}Administração → Auditoria</b> lista quem fez o quê e quando: login e falhas, gravações (com os ramos sincronizados), mudanças de status, criação, importação, exportação, exclusão, templates, times, usuários e aparência. Fica na tabela <code>audit</code> do banco.</p>` },
    { id: "servidor", role: "admin", title: "Servidor e operação", html: `
      <p>Python 3, sem dependências externas.</p>
      <pre>python3 server.py adduser &lt;login&gt; --role admin --name "Nome"   # cria/atualiza usuário pelo terminal
python3 server.py --port 8765                                      # só esta máquina
python3 server.py --host 0.0.0.0 --port 8765 --secure-cookies      # rede, atrás de proxy HTTPS</pre>
      <p>Sem administrador o servidor não sobe e mostra o comando acima, a menos que <code>MEDUSA_ADMIN_LOGIN</code> esteja definida: nesse caso ele cria o administrador com senha temporária (mostrada uma vez no log) e exige a troca no primeiro acesso. Para expor ao time, use um proxy reverso com HTTPS e <code>--secure-cookies</code>.</p>
      <p><b>Docker:</b> veja <code>INSTALACAO-DOCKER.md</code>. Imagem sem dependências além do Python, dados no volume <code>/data</code>.</p>
      <table><thead><tr><th>Variável</th><th>Uso</th></tr></thead><tbody>
        <tr><td><code>MEDUSA_HOME</code></td><td>pasta de dados (padrão: a pasta da aplicação; no Docker, <code>/data</code>)</td></tr>
        <tr><td><code>MEDUSA_HOST</code> · <code>MEDUSA_PORT</code></td><td>endereço e porta</td></tr>
        <tr><td><code>MEDUSA_SECURE_COOKIES</code></td><td><code>1</code> atrás de HTTPS</td></tr>
        <tr><td><code>MEDUSA_TRUST_PROXY</code></td><td><code>1</code> atrás de proxy reverso: usa o IP real do <code>X-Forwarded-For</code></td></tr>
        <tr><td><code>MEDUSA_ADMIN_LOGIN</code> · <code>MEDUSA_ADMIN_NAME</code> · <code>MEDUSA_ADMIN_PASSWORD</code></td><td>administrador inicial (só quando não há nenhum)</td></tr>
        <tr><td><code>MEDUSA_SESSION_IDLE_HOURS</code> · <code>MEDUSA_SESSION_MAX_HOURS</code></td><td>sessão: horas sem uso (padrão 8) e duração máxima (padrão 24)</td></tr></tbody></table>
      <p>Dentro de <code>MEDUSA_HOME</code>:</p>
      <table><thead><tr><th>Caminho</th><th>Conteúdo</th></tr></thead><tbody>
        <tr><td><code>playbooks/PB-xx-*/</code></td><td><code>.md</code> e <code>.drawio</code> de cada playbook, e as imagens do documento em <code>imagens/</code></td></tr>
        <tr><td><code>mappings.json</code></td><td>caixa do fluxograma → passos, ramos ou seções</td></tr>
        <tr><td><code>templates/*.medusa-template.md</code></td><td>templates, com os times e tags de cada um</td></tr>
        <tr><td><code>data/playbooks.db</code></td><td>SQLite: usuários, sessões, auditoria, configurações (aparência, logs, SSO), template e <b>histórico de versões</b> de cada playbook</td></tr>
        <tr><td><code>data/logs/</code></td><td>auditoria em JSON Lines (se o destino "arquivo" estiver ligado)</td></tr>
        <tr><td><code>data/lixeira/</code></td><td>playbooks e templates excluídos e o conteúdo de cada reset (<code>reset__…</code>); para restaurar, mova de volta e reinicie</td></tr>
        <tr><td><code>data/cache/biblioteca.json</code></td><td>resumos e índice de busca, para o servidor subir rápido (pode ser apagado: é refeito)</td></tr>
        <tr><td><code>.backups/&lt;PB&gt;/&lt;data-hora&gt;/</code></td><td>versão anterior de cada arquivo, a cada gravação</td></tr></tbody></table>
      <p><b>Backup do banco:</b> o banco usa WAL (gravações recentes ficam em <code>playbooks.db-wal</code>). Com o servidor parado, copie a pasta <code>data/</code> inteira; com ele rodando, use <code>sqlite3 data/playbooks.db ".backup copia.db"</code>. Copiar só o <code>.db</code> com o servidor no ar pode perder as últimas alterações. Novas versões do esquema são aplicadas sozinhas ao iniciar.</p>
      <p><b>Ambiente de teste:</b> aponte <code>MEDUSA_HOME</code> para uma cópia da pasta de dados.</p>` },
    { id: "seguranca", role: "admin", title: "Segurança", html: `
      <table><tbody>
        <tr><td>Senhas</td><td>PBKDF2-SHA256 com 310 mil iterações; nunca em texto</td></tr>
        <tr><td>Sessão</td><td>cookie HttpOnly + SameSite=Strict; no banco só o SHA-256 do token; expira após 8 h sem uso ou 24 h depois do login</td></tr>
        <tr><td>Requisições</td><td>alterações exigem o cabeçalho <code>X-Requested-With</code> (anti-CSRF)</td></tr>
        <tr><td>Navegador</td><td>CSP sem script inline, X-Frame-Options, nosniff; logo servida em sandbox</td></tr>
        <tr><td>Arquivos</td><td>só o front-end é servido; <code>.md</code>, <code>.drawio</code>, banco e backups não ficam acessíveis pela web</td></tr>
        <tr><td>Concorrência</td><td>toda gravação informa a revisão que estava aberta; sobre versão desatualizada é recusada (409)</td></tr>
        <tr><td>Arquivos gravados</td><td>escrita atômica (arquivo temporário + troca): uma queda no meio da gravação não corrompe o playbook</td></tr>
        <tr><td>Servidor</td><td>conexões paradas são encerradas após 30 s; até 32 requisições processadas ao mesmo tempo, as demais aguardam</td></tr></tbody></table>` },
    { id: "problemas", role: "editor", title: "Solução de problemas", html: `
      <table><thead><tr><th>Sintoma</th><th>O que fazer</th></tr></thead><tbody>
        <tr><td>"Foi salvo por outra pessoa"</td><td>copie o que precisar, clique em Recarregar e reaplique</td></tr>
        <tr><td>Ramo não aparece na aba Ramos</td><td>salve o fluxograma: a subseção é criada no documento ao salvar. A caixa precisa começar com R# e estar vinculada a R#</td></tr>
        <tr><td>Time não aparece para virar raia</td><td>ele precisa ser <i>central</i> e estar nos times do template do playbook (aba Times e tags do template)</td></tr>
        <tr><td>Login pelo SSO volta com erro</td><td>a mensagem aparece na tela de login e o detalhe na auditoria (<code>sso_falhou</code>). Confira URL de redirecionamento, URL pública, client secret e a claim de login</td></tr>
        <tr><td>Destino de log com falhas</td><td>Administração → Logs: veja o último erro e use "Enviar evento de teste"</td></tr>
        <tr><td>Conta bloqueada</td><td>aguarde 5 minutos ou peça ao administrador para redefinir a senha</td></tr>
        <tr><td>Perdeu o acesso de administrador</td><td>no servidor: <code>python3 server.py adduser &lt;login&gt; --role admin</code></td></tr>
        <tr><td>Restaurar uma versão</td><td>copie o arquivo de <code>.backups/&lt;PB&gt;/&lt;data-hora&gt;/</code> para a pasta do playbook</td></tr></tbody></table>` },
  ];
  const ROLE_LBL = { viewer: "todos", editor: "editores", admin: "administradores" };
  /* quem vê cada tópico: pelo público (role) e, nos de administração, pela permissão específica */
  const AUD = { viewer: () => true, editor: () => canAny("playbook.edit", "playbook.create", "templates.view"), admin: () => canAdmin() };
  const VIS = { papeis: () => can("roles.manage"), usuarios: () => can("users.manage"), logs: () => can("logs.manage"), sso: () => can("sso.manage"),
    aparencia: () => can("branding.edit"), reset: () => can("app.reset"), auditoria: () => can("audit.view"), templates: () => can("templates.view"),
    times: () => can("templates.view"), importar: () => can("playbook.import"), criar: () => can("playbook.create"), ciclo: () => can("playbook.status") };
  const visible = s => (VIS[s.id] || AUD[s.role])();

  function render(root, focus) {
    const secs = SECTIONS.filter(visible);
    root.innerHTML = `<div class="pbbar"><div class="wrap"><div class="pbhead"><span class="pbid">${ic("docs")}</span><h1>Documentação</h1>
        <div class="pbactions"><input class="in sm" id="docQ" type="search" placeholder="Filtrar tópicos…" style="width:220px"></div></div>
        <p class="muted" style="margin:6px 0 16px">Como usar e administrar o ${esc(Brand.get().name)}${Brand.get().appVersion ? ` (Medusa Docs ${esc(Brand.get().appVersion)})` : ""}. Você vê os tópicos do seu papel (${esc(App.user.roleName)}).</p></div></div>
      <div class="wrap"><div class="docgrid"><nav class="toc" id="docToc">${secs.map(s => `<a href="#/docs/${s.id}" data-go="${s.id}">${esc(s.title)}</a>`).join("")}</nav>
        <div class="doc docs-page">${secs.map(s => `<section id="doc-${s.id}" class="md" data-txt="${esc((s.title + " " + s.html.replace(/<[^>]+>/g, " ")).toLowerCase())}">
          <h2>${esc(s.title)} ${s.role !== "viewer" ? `<span class="aud ${s.role}">${ROLE_LBL[s.role]}</span>` : ""}</h2>${s.html}</section>`).join("")}</div></div></div>`;
    const go = id => { const el = document.getElementById("doc-" + id); if (el) el.scrollIntoView({ block: "start" }); };
    $("#docToc").onclick = e => { const a = e.target.closest("[data-go]"); if (!a) return; e.preventDefault(); history.replaceState(null, "", "#/docs/" + a.dataset.go); Tabs.sync(); go(a.dataset.go); };
    $("#docQ").oninput = e => {
      const q = e.target.value.trim().toLowerCase();
      root.querySelectorAll(".docs-page section").forEach(s => { s.hidden = !!q && !s.dataset.txt.includes(q); });
      root.querySelectorAll("#docToc a").forEach(a => { a.hidden = !!q && document.getElementById("doc-" + a.dataset.go).hidden; });
    };
    if (focus) setTimeout(() => go(focus), 30);
  }
  return { render };
})();
