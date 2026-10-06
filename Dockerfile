# Medusa Docs — imagem de produção
# Só a biblioteca padrão do Python: nada é instalado além da imagem base.
FROM python:3.12-alpine

LABEL org.opencontainers.image.title="Medusa Docs" \
      org.opencontainers.image.description="Playbooks interativos de resposta a incidentes (documento + fluxograma), com perfis, templates e auditoria" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="2.1.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDUSA_HOME=/data \
    MEDUSA_HOST=0.0.0.0 \
    MEDUSA_PORT=8765

# usuário sem privilégios, com UID/GID fixos (facilita dar permissão a pastas montadas do host)
RUN addgroup -S -g 10001 medusa && adduser -S -D -H -u 10001 -G medusa medusa \
 && mkdir -p /data && chown medusa:medusa /data && chmod 750 /data

WORKDIR /app
COPY server.py store.py pbcore.py templates.py ramos.py bundle.py flowdsl.py logfwd.py sso.py mitre.json ./
COPY index.html app.js editor.js flow.js docs.js theme.js style.css ./
COPY assets ./assets
COPY LICENSE ./

USER medusa
VOLUME ["/data"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python3 -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/api/branding' % os.environ.get('MEDUSA_PORT','8765'), timeout=4)" || exit 1

ENTRYPOINT ["python3", "/app/server.py"]
