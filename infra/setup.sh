#!/bin/sh
set -eu
if [ ! -f /workspace/.env ]; then
    umask 077
    pass=$(openssl rand -hex 12)
    secret=$(openssl rand -hex 32)
    dbpass=$(openssl rand -hex 24)
    cat > /workspace/.env <<ENV
POSTGRES_PASSWORD=$dbpass
APP_SESSION_SECRET=$secret
MERCHANT_PASSCODE=$pass
APP_ORIGIN=http://localhost:8080
SITE_ADDRESS=http://localhost
HTTP_BIND=127.0.0.1:8080:80
HTTPS_BIND=127.0.0.1:8443:443
EXECUTION_MODE=demo
ENV
    echo "Created .env with private random settings. Read MERCHANT_PASSCODE in .env to sign in."
fi
if [ ! -f /workspace/.env.providers ]; then
    cp /workspace/.env.providers.example /workspace/.env.providers
    chmod 600 /workspace/.env.providers
fi
