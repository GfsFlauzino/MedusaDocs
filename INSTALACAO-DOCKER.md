# Guia de instalação com Docker

Este guia instala o Medusa Docs num servidor com Docker, do zero até o acesso do time por HTTPS, com backup e
atualização. Tempo estimado: 10 minutos.

## 1. Requisitos

| Item | Mínimo |
| --- | --- |
| Docker Engine | 20.10 ou superior, com o plugin **Docker Compose v2** (`docker compose version`) |
| Sistema | Linux, macOS ou Windows (Docker Desktop) |
| Recursos | 1 vCPU, 256 MB de RAM, 1 GB de disco para começar |
| Rede | Uma porta livre no host (padrão `8765`) e, para acesso do time, um proxy reverso com HTTPS |

A imagem usa `python:3.12-alpine` e não instala nenhuma dependência extra.

## 2. Obter os arquivos

Copie a pasta da aplicação para o servidor (por Git ou cópia). Ela precisa conter, entre outros:

```text
Dockerfile  docker-compose.yml  .env.example  server.py  app.js  index.html  …
```

Entre na pasta:

```bash
cd medusa-docs
```

## 3. Configurar

```bash
cp .env.example .env
```

Edite o `.env`:

| Variável | O que definir |
| --- | --- |
| `MEDUSA_ADMIN_LOGIN` | Login do primeiro administrador (letras minúsculas, números, `.` `_` `-`) |
| `MEDUSA_ADMIN_NAME` | Nome exibido |
| `MEDUSA_ADMIN_PASSWORD` | Deixe **vazio** para gerar uma senha temporária (recomendado) |
| `MEDUSA_BIND` / `MEDUSA_PUBLISH_PORT` | Onde a porta é publicada. Mantenha `127.0.0.1` se houver proxy no mesmo host |
| `MEDUSA_SECURE_COOKIES` | `1` quando o acesso for por HTTPS (passo 6) |

O administrador só é criado se ainda não houver nenhum. Em qualquer caso, a troca de senha é obrigatória no primeiro acesso.

## 4. Subir

```bash
docker compose up -d --build
docker compose ps
```

Aguarde o status `healthy` (cerca de 15 segundos). Veja a senha temporária do administrador:

```bash
docker compose logs medusa
```

```text
================================================================
Administrador inicial criado: admin
Senha temporária: ••••••••••••••••
A troca de senha é obrigatória no primeiro acesso.
================================================================
```

A senha aparece **uma única vez**, na primeira subida. Depois do primeiro acesso ela deixa de valer.

## 5. Primeiro acesso

1. Abra `http://localhost:8765` (ou `http://IP-DO-SERVIDOR:8765` se publicou na rede).
2. Entre com o login e a senha temporária e defina a sua senha (mínimo 10 caracteres, com letras e números).
3. Em **⚙ Administração → Aparência**, ajuste nome, cor, logo e o título e subtítulo da página inicial.
4. Em **⚙ Administração → Usuários**, crie os usuários do time (visualizador, editor ou administrador).
5. Em **📐 Templates, times e tags**, revise o template **Padrão** e os times de apoio.

A instalação começa com o template Padrão e nenhum playbook. Crie playbooks em **＋ Novo playbook** ou importe
arquivos `.medusa.md` em **⤒ Importar**.

## 6. Acesso pelo time com HTTPS

O servidor fala HTTP. Para o time acessar pela rede, coloque um proxy reverso com HTTPS na frente e:

1. mantenha `MEDUSA_BIND=127.0.0.1` (só o proxy acessa a porta);
2. defina `MEDUSA_SECURE_COOKIES=1` no `.env`;
3. aplique: `docker compose up -d`.

Com `MEDUSA_SECURE_COOKIES=1`, o login só funciona por `https://`.

### Caddy (certificado automático)

```text
playbooks.suaempresa.com.br {
    reverse_proxy 127.0.0.1:8765
}
```

### nginx

```nginx
server {
    listen 443 ssl http2;
    server_name playbooks.suaempresa.com.br;
    ssl_certificate     /etc/ssl/certs/playbooks.crt;
    ssl_certificate_key /etc/ssl/private/playbooks.key;
    client_max_body_size 10m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
server {
    listen 80;
    server_name playbooks.suaempresa.com.br;
    return 301 https://$host$request_uri;
}
```

Se o proxy roda em outro container na mesma rede Docker, aponte para `http://medusa-docs:8765` e remova a seção
`ports` do `docker-compose.yml`.

## 7. Onde ficam os dados

Tudo fica no volume `medusa-data`, montado em `/data` no container:

| Caminho no volume | Conteúdo |
| --- | --- |
| `playbooks/` | `.md` e `.drawio` de cada playbook |
| `templates/` | Templates, com os times e tags de cada um |
| `mappings.json` | Vínculos das caixas do fluxograma com o documento |
| `data/playbooks.db` | Banco SQLite: usuários, sessões, auditoria, aparência |
| `data/lixeira/` | Playbooks e templates excluídos |
| `.backups/` | Versão anterior de cada arquivo, a cada gravação |

Recriar ou atualizar o container **não apaga** o volume. Só `docker compose down -v` o apaga.

### Usar uma pasta do host em vez do volume

No `docker-compose.yml`, troque `medusa-data:/data` por `./medusa-data:/data` e dê a pasta ao usuário do container (UID 10001):

```bash
mkdir -p medusa-data
sudo chown -R 10001:10001 medusa-data
docker compose up -d
```

## 8. Backup e restauração

### Backup completo (recomendado, alguns segundos fora do ar)

```bash
docker compose stop
docker run --rm --volumes-from medusa-docs -v "$PWD":/backup alpine \
  tar czf /backup/medusa-backup-$(date +%F).tar.gz -C /data .
docker compose start
```

### Backup só do banco, sem parar

```bash
docker compose exec medusa python3 -c "import sqlite3; s=sqlite3.connect('/data/data/playbooks.db'); d=sqlite3.connect('/data/data/backup.db'); s.backup(d); d.close()"
docker cp medusa-docs:/data/data/backup.db ./playbooks-$(date +%F).db
```

### Restaurar

```bash
docker compose stop
docker run --rm --volumes-from medusa-docs -v "$PWD":/backup alpine \
  sh -c "find /data -mindepth 1 -delete && tar xzf /backup/medusa-backup-AAAA-MM-DD.tar.gz -C /data"
docker compose start
```

Agende o backup completo (cron, por exemplo) e guarde as cópias fora do servidor.

## 9. Atualizar a versão

```bash
# com os arquivos novos na pasta
docker compose up -d --build
docker image prune -f
```

Os dados continuam no volume; ajustes no banco são aplicados sozinhos ao iniciar. Faça um backup antes.

## 10. Trazer dados de outra instalação

- **Playbooks:** exporte na origem (**⤓ Exportar todos** gera um `.zip` de `.medusa.md`) e importe cada arquivo em **⤒ Importar**, escolhendo o template.
- **Templates:** **⤓ Exportar** na lista de templates da origem e **⤒ Importar template** no destino.
- **Instalação inteira** (incluindo usuários e auditoria): copie a pasta de dados da origem (`playbooks/`, `templates/`, `data/`, `mappings.json`, `.backups/`) para o volume, com o container parado:

```bash
docker compose stop
docker run --rm --volumes-from medusa-docs -v /caminho/da/origem:/origem alpine \
  sh -c "cp -a /origem/. /data/ && chown -R 10001:10001 /data"
docker compose start
```

## 11. Comandos úteis

| Tarefa | Comando |
| --- | --- |
| Ver logs | `docker compose logs -f medusa` |
| Reiniciar | `docker compose restart` |
| Parar / iniciar | `docker compose stop` / `docker compose start` |
| Estado e saúde | `docker compose ps` |
| Criar ou redefinir um usuário pelo terminal | `docker compose exec -it medusa python3 /app/server.py adduser <login> --role admin --name "Nome"` |

O comando `adduser` pede a senha no terminal e também serve para recuperar o acesso de administrador.

## 12. Sem Docker Compose

```bash
docker build -t medusa-docs .
docker volume create medusa-data
docker run -d --name medusa-docs --restart unless-stopped \
  -p 127.0.0.1:8765:8765 -v medusa-data:/data \
  -e MEDUSA_ADMIN_LOGIN=admin -e MEDUSA_ADMIN_NAME="Administrador" \
  --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges:true \
  medusa-docs
docker logs medusa-docs
```

## 13. Solução de problemas

| Sintoma | Causa e solução |
| --- | --- |
| Não aparece a senha temporária no log | Já existia um administrador no volume (a senha só é gerada uma vez). Use o `adduser` do passo 11 |
| `Permission denied` em `/data` | Pasta do host sem permissão: `sudo chown -R 10001:10001 medusa-data` |
| `port is already allocated` | Porta ocupada: troque `MEDUSA_PUBLISH_PORT` no `.env` |
| Login volta para a tela de login | `MEDUSA_SECURE_COOKIES=1` com acesso por `http://`. Use HTTPS ou volte para `0` |
| Container `unhealthy` | Veja `docker compose logs medusa`; o healthcheck consulta `http://127.0.0.1:8765/api/branding` dentro do container |
| Log diz "exposto na rede sem --secure-cookies" | Aviso normal dentro do container (ele escuta em `0.0.0.0`). Proteja com `MEDUSA_BIND=127.0.0.1` e proxy HTTPS |
| Conta bloqueada | 5 senhas erradas bloqueiam por 5 minutos. Aguarde ou peça a um administrador para redefinir a senha |

## Segurança da imagem

- Roda como usuário sem privilégios (`medusa`, UID 10001).
- Sistema de arquivos somente leitura; só o volume `/data` e `/tmp` aceitam gravação.
- Sem capabilities do Linux e com `no-new-privileges`.
- Senhas com PBKDF2-SHA256, sessão em cookie `HttpOnly` e `SameSite=Strict`, proteção contra CSRF, CSP sem script inline e auditoria de todas as alterações.
