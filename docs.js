"use strict";
/* Documentação da plataforma (aba DOCs). Cada seção indica o perfil mínimo que a enxerga:
   o visualizador lê o guia de leitura; editores veem edição, templates e ramos; administradores, tudo. */
const Docs = (() => {
  const K = s => `<kbd>${s}</kbd>`;
  const SECTIONS = [
    { id: "visao-geral", role: "viewer", title: "Visão geral", html: `
      <p>O Medusa Docs é a base interativa dos playbooks de resposta a incidentes. Cada playbook tem um <b>documento</b> (as regras, fases, ramos e critérios) e um <b>fluxograma</b> (o mapa de operação por time).</p>
      <ul><li><b>Fonte da verdade:</b> cada playbook é um par de arquivos <code>.md</code> + <code>.drawio</code> na pasta <code>playbooks/PB-xx-…/</code>, que podem ir para o Confluence, Git ou draw.io. A ferramenta lê e grava esses arquivos.</li>
        <li><b>Abas:</b> cada playbook ou página aberta vira uma aba no topo, como num navegador. ${K("✕")} fecha; clique do meio também. As abas ficam guardadas no seu navegador.</li>
        <li><b>Busca:</b> ${K("/")} foca a busca; encontra passos (T0, A3…), ramos, seções e times em todos os playbooks que você pode ver.</li>
        <li><b>Tema:</b> o botão ☀/☾ alterna claro e escuro. As cores do fluxograma seguem o modelo e não mudam com o tema.</li></ul>` },
    { id: "perfis", role: "viewer", title: "Perfis e permissões", html: `
      <table><thead><tr><th>Perfil</th><th>Vê</th><th>Pode</th></tr></thead><tbody>
        <tr><td>Visualizador</td><td>Playbooks em <b>Homologação</b> e <b>Produção</b></td><td>Ler, buscar, exportar e trocar a própria senha</td></tr>
        <tr><td>Editor</td><td>Todos, inclusive <b>Desenvolvimento</b></td><td>Criar, editar e importar playbooks, mudar status, editar templates, times e tags</td></tr>
        <tr><td>Administrador</td><td>Todos</td><td>Tudo do editor + usuários, aparência, auditoria, exclusão de playbooks e de templates</td></tr></tbody></table>
      <p>As permissões são verificadas no servidor: o visualizador nem recebe os playbooks em Desenvolvimento.</p>` },
    { id: "leitura", role: "viewer", title: "Lendo um playbook", html: `
      <ul><li><b>Fluxograma:</b> clique em uma caixa para ler o trecho da documentação vinculado a ela (passos, ramo, seção). Clique no nome de um time (raia ou caixa de apoio) para ver as responsabilidades e o que ele não faz. A etiqueta no canto da caixa mostra o ID do passo.</li>
        <li><b>Passo a passo:</b> as fases com os passos (ID, ação, critério de saída), filtráveis por time.</li>
        <li><b>Ramos:</b> os cenários R1, R2… do playbook. Clique para abrir o detalhamento.</li>
        <li><b>Documento:</b> o documento completo com índice lateral.</li>
        <li>No texto, IDs como <b>T3</b>, <b>R2</b> ou <b>E4</b> e nomes de times são clicáveis.</li></ul>` },
    { id: "exportar", role: "viewer", title: "Exportar", html: `
      <p>O botão <b>⤓ Exportar</b> do playbook está disponível para todos os perfis:</p>
      <table><thead><tr><th>Formato</th><th>Uso</th></tr></thead><tbody>
        <tr><td>Markdown <code>.md</code></td><td>documento para Confluence, Git ou qualquer editor</td></tr>
        <tr><td>HTML com fluxograma</td><td>abre em qualquer navegador ou no Word</td></tr>
        <tr><td>Imprimir / PDF</td><td>documento completo com o fluxograma</td></tr>
        <tr><td>draw.io <code>.drawio</code></td><td>fluxograma editável no draw.io e no Confluence</td></tr>
        <tr><td>Mermaid <code>.mmd</code></td><td>fluxograma em texto (GitHub, GitLab, mermaid.live)</td></tr>
        <tr><td>SVG</td><td>imagem do fluxograma</td></tr>
        <tr><td>Medusa <code>.medusa.md</code></td><td>pacote completo (documento + times + fluxo), reimportável em outra instalação</td></tr></tbody></table>
      <p>Na página inicial, <b>Exportar todos</b> baixa um <code>.zip</code> com os playbooks que você pode ver. Toda exportação fica na auditoria.</p>` },
    { id: "ciclo", role: "editor", title: "Ciclo de vida e revisão", html: `
      <p><b>Desenvolvimento → Homologação → Produção</b>, pelo botão <b>⇄ Alterar status</b> do playbook.</p>
      <ul><li>Playbook criado ou importado começa em Desenvolvimento (visível só para editores).</li>
        <li>Homologação: validação com o time; visualizadores já leem.</li>
        <li>Produção exige um <b>aprovador</b> (editor ou administrador ativo).</li>
        <li><b>Último revisor</b> e <b>data de revisão</b> são preenchidos a cada gravação. Os quatro campos ficam na tabela "Propriedades do playbook" e aparecem bloqueados 🔒 no editor.</li>
        <li>Editar algo em Produção mostra um aviso: a alteração fica visível para todos na hora. Para revisões maiores, volte antes para Homologação.</li></ul>` },
    { id: "criar", role: "editor", title: "Criar playbook", html: `
      <ol><li><b>＋ Novo playbook</b> na página inicial.</li>
        <li>Escolha o <b>template</b> (documento, fluxograma, ramos e times iniciais).</li>
        <li>Preencha ID, nome, autor (usuários ativos), owner, fase NIST, táticas <b>MITRE ATT&amp;CK</b> (lista da versão mais recente) e escopo.</li>
        <li>Informe os <b>ramos</b>: cada um vira uma subseção no documento e uma caixa R no fluxograma.</li></ol>
      <p>O playbook fica ligado ao template escolhido: os times e tags dele são os do template (o cabeçalho do playbook mostra qual). O playbook abre direto no editor.</p>` },
    { id: "editar-documento", role: "editor", title: "Editar o documento", html: `
      <ul><li>Seções, subseções, parágrafos, listas, checklists, destaques e tabelas, sem código. ${K("Ctrl+S")} salva, ${K("Ctrl+B")} aplica negrito.</li>
        <li>Na tabela de propriedades, o botão 🎯 da linha "Tática MITRE" abre a lista de táticas.</li>
        <li><b>＋ Novo ramo</b> (na seção de ramos) ou <b>＋ Seção de ramos</b> (no índice, se ainda não houver) criam ramos; ver <a href="#/docs/ramos">Ramos</a>.</li>
        <li><b>Descartar</b> recarrega a versão salva. Cada gravação guarda backup da versão anterior.</li>
        <li>Se outra pessoa salvou depois que você abriu, a gravação é recusada e a tela oferece recarregar (suas alterações continuam na tela para copiar).</li></ul>` },
    { id: "editar-fluxograma", role: "editor", title: "Editar o fluxograma", html: `
      <p>Só as formas, cores e setas do modelo estão disponíveis; cada caixa fica na raia do time responsável.</p>
      <table><thead><tr><th>Ação</th><th>Como</th></tr></thead><tbody>
        <tr><td>Criar caixa</td><td>clique numa forma da paleta e depois na raia, ou arraste a forma até a raia</td></tr>
        <tr><td>Trocar o time</td><td>arraste a caixa para outra raia (ou mude "Time responsável")</td></tr>
        <tr><td>Criar seta</td><td>selecione a caixa e arraste o círculo <b>→</b> até o destino; o tipo (handoff, escalonamento, apoio) é sugerido pelas raias</td></tr>
        <tr><td>Dobrar a seta</td><td>arraste os círculos da seta selecionada; "Remover dobras" volta à rota automática</td></tr>
        <tr><td>Mover o texto da seta</td><td>arraste o rótulo (sim, não, handoff…); "↺ Texto na posição automática" desfaz. A posição vai para o <code>.drawio</code></td></tr>
        <tr><td>Selecionar várias</td><td>${K("Shift")}/${K("Ctrl")}+clique, arrastar no fundo (laço) ou ${K("Ctrl+A")} / <b>⬚ Tudo</b></td></tr>
        <tr><td>Mover várias</td><td>arraste qualquer caixa selecionada ou use as setas do teclado; cada caixa mantém a raia</td></tr>
        <tr><td>Redimensionar proporcionalmente</td><td>arraste o quadrado no canto da seleção, ou use −10% / +10% / percentual no painel. Posições, tamanhos e dobras escalam juntos</td></tr>
        <tr><td>Alinhar e distribuir</td><td>no painel da seleção múltipla: esquerda, centro, direita, topo, meio, base, distribuir, mesma largura/altura</td></tr>
        <tr><td>Texto da caixa</td><td>linhas normal, <b>negrito</b> ou cinza (detalhe); ↑ reordena</td></tr>
        <tr><td>"Ao clicar"</td><td>vincule a caixa a passos, ramos, estados ou seções: é o que o analista lê</td></tr>
        <tr><td>Raias</td><td>sem seleção, o painel lista as raias: adicionar time central, reordenar, remover (vazia) ou criar novo time</td></tr></tbody></table>
      <p>Atalhos: ${K("Ctrl+Z")} desfaz, ${K("Ctrl+Shift+Z")} refaz, ${K("Del")} exclui, ${K("Ctrl+D")} duplica, ${K("Esc")} limpa a seleção, ${K("Ctrl+S")} salva.</p>
      <p>O modo <b>&lt;/&gt; Código</b> mostra o fluxo em Mermaid (ver <a href="#/docs/mermaid">Linguagem de fluxo</a>). A página 2 do <code>.drawio</code> é preservada ao salvar.</p>` },
    { id: "ramos", role: "editor", title: "Ramos (R1, R2…)", html: `
      <p>Ramo é um cenário do playbook (ex.: R1 Varredura, R2 Credenciais). Ele existe nos dois lados e fica <b>sincronizado</b>:</p>
      <table><thead><tr><th>Onde</th><th>Forma</th></tr></thead><tbody>
        <tr><td>Documento</td><td>subseção <code>R3 · Nome</code> (em "Ramos em detalhe"), com a tabela de detalhe; o item "É sucesso quando" é o indicador</td></tr>
        <tr><td>Fluxograma</td><td>caixa cujo texto começa com <code>R3</code> e que está vinculada a R3; a linha cinza é o indicador</td></tr>
        <tr><td>Aba Ramos</td><td>lista lida do documento</td></tr></tbody></table>
      <p><b>Criar:</b> forma <b>Ramo</b> na paleta do fluxograma, <b>＋ Novo ramo</b> no documento ou <b>＋ Novo ramo</b> na aba Ramos. Ao salvar, o outro lado recebe o ramo. No fluxograma, o ramo novo fica ao lado do último e copia as ligações dele; se não houver ramo ainda, liga-se à decisão "Ramo".</p>
      <p><b>Renomear / indicador:</b> altere de um lado e salve; o outro acompanha. <b>Excluir:</b> excluir a caixa ou a subseção remove o ramo do outro lado ao salvar (a tela confirma antes).</p>
      <p>O texto "R1 a Rn" (decisão de ramo, passo T2) é atualizado sozinho. A notificação depois de salvar lista o que foi sincronizado.</p>
      <p>Em <b>templates</b>, o ramo é o modelo <code>R{{ramo.n}} · {{ramo.nome}}</code>: na criação do playbook ele é repetido para cada ramo informado.</p>` },
    { id: "templates", role: "editor", title: "Templates", html: `
      <p>Menu do perfil → <b>📐 Templates, times e tags</b>. O template define o documento modelo, o fluxograma modelo, os ramos e os times e tags que um playbook novo recebe.</p>
      <ul><li><b>Padrão</b>: o template inicial da instalação (não pode ser excluído). Raias SOC N1, SOC N2 e CSIRT, times de apoio de segurança (DFIR, Threat Intel, IAM, Vulnerabilidades, AppSec, Cloud Security, Infraestrutura, Privacidade), ramos e um ciclo completo: triagem, análise, investigação, contenção e pós-incidente.</li>
        <li><b>Novo em branco</b>: entrada <i>Alerta</i>, decisão de ramo com o ramo-modelo, seções mínimas e somente os times SOC N1, SOC N2 e CSIRT.</li>
        <li><b>Duplicar</b> parte de um template existente; <b>Exportar/Importar</b> usa o arquivo <code>.medusa-template.md</code>.</li>
        <li>Template sem ramos mostra <b>＋ Adicionar ramos</b> na aba Geral.</li></ul>
      <p><b>Variáveis</b> (substituídas na criação): <code>{{id}}</code> <code>{{nome}}</code> <code>{{autor}}</code> <code>{{data}}</code> <code>{{owner}}</code> <code>{{nist}}</code> <code>{{mitre}}</code> <code>{{objetivo}}</code> <code>{{pergunta}}</code> <code>{{ramos.total}}</code> <code>{{ramos.lista}}</code> <code>{{arquivo_drawio}}</code>.
        O que contém <code>{{ramo.n}}</code>, <code>{{ramo.nome}}</code> ou <code>{{ramo.pergunta}}</code> (subseção, linha de tabela, item, parágrafo ou caixa) é repetido por ramo.</p>
      <p>Excluir template é exclusivo do administrador (vai para a lixeira). Os playbooks criados com ele passam para o template Padrão, que recebe os times que eles usam.</p>` },
    { id: "times", role: "editor", title: "Times e tags", html: `
      <p>Times e tags pertencem aos <b>templates</b>: cada template tem os seus, gerenciados na aba <b>Times e tags</b> do template (menu do perfil → Templates, times e tags).</p>
      <ul><li><i>Central</i> pode virar raia; <i>apoio/tag</i> vira caixa de apoio e tag clicável nos textos. Cada time tem cor, resumo, responsabilidades e o que não faz.</li>
        <li>Um playbook usa os times do template com que foi criado (ou importado). Em <b>✎ Editar time</b> (ao clicar num time dentro do playbook), a alteração vale para o template e todos os playbooks dele.</li>
        <li>Template novo começa com SOC N1, SOC N2 e CSIRT. Dá para criar times, copiar de outro template ou tirar os que não usa.</li>
        <li>Um time usado no fluxograma do template ou em algum playbook dele não pode ser retirado.</li>
        <li>Usar no fluxograma um time de outro template o acrescenta ao template ao salvar.</li></ul>` },
    { id: "importar", role: "editor", title: "Importar", html: `
      <p><b>⤒ Importar</b> na página inicial aceita <code>.medusa.md</code> de qualquer instalação ou um <code>.md</code> comum (título <code># PB-00 — Nome</code> e seções <code>##</code>). A tela mostra uma prévia (seções, caixas, raias, times novos e avisos) antes de gravar.</p>
      <ul><li>Se o ID já existir: importar com outro ID ou substituir (o atual vai para a lixeira).</li>
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
      <p><b>⚙ Administração → Usuários</b>:</p>
      <ul><li><b>Criar:</b> login (3 a 40 caracteres: minúsculas, números, <code>. _ -</code>), nome e perfil. A senha temporária aparece uma única vez; o usuário é obrigado a trocá-la no primeiro acesso (mínimo 10 caracteres).</li>
        <li><b>Redefinir senha</b> gera outra temporária e encerra as sessões. <b>Encerrar</b> derruba as sessões abertas.</li>
        <li><b>Desativar</b> bloqueia o acesso sem perder o histórico; <b>excluir</b> remove o usuário.</li>
        <li>Sempre há pelo menos um administrador ativo: a ferramenta não deixa rebaixar, desativar ou excluir o último.</li>
        <li>5 senhas erradas seguidas bloqueiam o login por 5 minutos. Sessões expiram após 8 h sem uso.</li></ul>` },
    { id: "aparencia", role: "admin", title: "Aparência", html: `
      <p><b>⚙ Administração → Aparência</b>: nome exibido no topo, cor primária (seletor, código <code>#RRGGBB</code> ou RGB), logo (PNG, JPG, SVG sem script ou WEBP, até 512 KB) e o <b>título e subtítulo da página inicial</b>. Vale para todos os usuários. As cores do fluxograma não mudam: seguem o modelo dos playbooks.</p>` },
    { id: "auditoria", role: "admin", title: "Auditoria", html: `
      <p><b>⚙ Administração → Auditoria</b> lista quem fez o quê e quando: login e falhas, gravações (com os ramos sincronizados), mudanças de status, criação, importação, exportação, exclusão, templates, times, usuários e aparência. Fica na tabela <code>audit</code> do banco.</p>` },
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
        <tr><td><code>MEDUSA_ADMIN_LOGIN</code> · <code>MEDUSA_ADMIN_NAME</code> · <code>MEDUSA_ADMIN_PASSWORD</code></td><td>administrador inicial (só quando não há nenhum)</td></tr></tbody></table>
      <p>Dentro de <code>MEDUSA_HOME</code>:</p>
      <table><thead><tr><th>Caminho</th><th>Conteúdo</th></tr></thead><tbody>
        <tr><td><code>playbooks/PB-xx-*/</code></td><td><code>.md</code> e <code>.drawio</code> de cada playbook</td></tr>
        <tr><td><code>mappings.json</code></td><td>caixa do fluxograma → passos, ramos ou seções</td></tr>
        <tr><td><code>templates/*.medusa-template.md</code></td><td>templates, com os times e tags de cada um</td></tr>
        <tr><td><code>data/playbooks.db</code></td><td>SQLite: usuários, sessões, tentativas, auditoria, aparência e o template de cada playbook</td></tr>
        <tr><td><code>data/lixeira/</code></td><td>playbooks e templates excluídos (para restaurar, mova de volta e reinicie)</td></tr>
        <tr><td><code>.backups/&lt;PB&gt;/&lt;data-hora&gt;/</code></td><td>versão anterior de cada arquivo, a cada gravação</td></tr></tbody></table>
      <p><b>Backup do banco:</b> copie <code>data/playbooks.db</code> com o servidor parado ou use <code>sqlite3 data/playbooks.db ".backup copia.db"</code>. Novas versões do esquema são aplicadas sozinhas ao iniciar.</p>
      <p><b>Ambiente de teste:</b> aponte <code>MEDUSA_HOME</code> para uma cópia da pasta de dados.</p>` },
    { id: "seguranca", role: "admin", title: "Segurança", html: `
      <table><tbody>
        <tr><td>Senhas</td><td>PBKDF2-SHA256 com 310 mil iterações; nunca em texto</td></tr>
        <tr><td>Sessão</td><td>cookie HttpOnly + SameSite=Strict; no banco só o SHA-256 do token</td></tr>
        <tr><td>Requisições</td><td>alterações exigem o cabeçalho <code>X-Requested-With</code> (anti-CSRF)</td></tr>
        <tr><td>Navegador</td><td>CSP sem script inline, X-Frame-Options, nosniff; logo servida em sandbox</td></tr>
        <tr><td>Arquivos</td><td>só o front-end é servido; <code>.md</code>, <code>.drawio</code>, banco e backups não ficam acessíveis pela web</td></tr>
        <tr><td>Concorrência</td><td>gravação sobre versão desatualizada é recusada (409)</td></tr></tbody></table>` },
    { id: "problemas", role: "editor", title: "Solução de problemas", html: `
      <table><thead><tr><th>Sintoma</th><th>O que fazer</th></tr></thead><tbody>
        <tr><td>"Foi salvo por outra pessoa"</td><td>copie o que precisar, clique em Recarregar e reaplique</td></tr>
        <tr><td>Ramo não aparece na aba Ramos</td><td>salve o fluxograma: a subseção é criada no documento ao salvar. A caixa precisa começar com R# e estar vinculada a R#</td></tr>
        <tr><td>Time não aparece para virar raia</td><td>ele precisa ser <i>central</i> e estar nos times do template do playbook (aba Times e tags do template)</td></tr>
        <tr><td>Conta bloqueada</td><td>aguarde 5 minutos ou peça ao administrador para redefinir a senha</td></tr>
        <tr><td>Perdeu o acesso de administrador</td><td>no servidor: <code>python3 server.py adduser &lt;login&gt; --role admin</code></td></tr>
        <tr><td>Restaurar uma versão</td><td>copie o arquivo de <code>.backups/&lt;PB&gt;/&lt;data-hora&gt;/</code> para a pasta do playbook</td></tr></tbody></table>` },
  ];
  const ROLE_LBL = { viewer: "todos", editor: "editores", admin: "administradores" };

  function render(root, focus) {
    const secs = SECTIONS.filter(s => can(s.role));
    root.innerHTML = `<div class="pbbar"><div class="wrap"><div class="pbhead"><span class="pbid">📖</span><h1>Documentação</h1>
        <div class="pbactions"><input class="in sm" id="docQ" type="search" placeholder="Filtrar tópicos…" style="width:220px"></div></div>
        <p class="muted" style="margin:6px 0 16px">Como usar e administrar o ${esc(Brand.get().name)}. Você vê os tópicos do seu perfil (${esc(App.user.roleName)}).</p></div></div>
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
