#!/usr/bin/env bash
# Instala/atualiza o bloco de cron do usuário atual de forma idempotente.
# Execute este script com o mesmo usuário que deve rodar a pipeline.

set -Eeuo pipefail

DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd)"
WRAPPER="$PROJECT_DIR/scripts/run_scheduled_pipeline.sh"
LOG_DIR="$PROJECT_DIR/logs"
LOG_FILE="$LOG_DIR/scheduler.log"

BEGIN_MARKER="# BEGIN B3_DERIVATIVES_PIPELINE"
END_MARKER="# END B3_DERIVATIVES_PIPELINE"

if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    echo "ERRO: $PROJECT_DIR/.env não existe."
    echo "Crie-o a partir de .env.example e configure as credenciais antes de instalar o cron."
    exit 1
fi

if [[ ! -x "$PROJECT_DIR/.venv/bin/python" ]]; then
    echo "ERRO: virtualenv ausente em $PROJECT_DIR/.venv"
    echo "Execute: python3 -m venv '$PROJECT_DIR/.venv' && '$PROJECT_DIR/.venv/bin/pip' install -r '$PROJECT_DIR/requirements.txt'"
    exit 1
fi

if ! command -v flock >/dev/null 2>&1; then
    echo "ERRO: comando flock não encontrado (normalmente fornecido pelo pacote util-linux)."
    exit 1
fi

mkdir -p "$LOG_DIR" "$PROJECT_DIR/.state"
chmod 600 "$PROJECT_DIR/.env"

current="$(crontab -l 2>/dev/null || true)"
cleaned="$(printf '%s\n' "$current" | awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin {skip=1; next}
    $0 == end   {skip=0; next}
    !skip {print}
')"

block=$(cat <<EOF
$BEGIN_MARKER
# BVBG.187.01 costuma estar disponível apenas no EOD. Execução principal às 21:00.
0 21 * * * "$WRAPPER" >> "$LOG_FILE" 2>&1
# Recupera o último slot vencido quando o servidor inicia.
@reboot sleep 120 && "$WRAPPER" >> "$LOG_FILE" 2>&1
$END_MARKER
EOF
)

{
    printf '%s\n' "$cleaned"
    printf '%s\n' "$block"
} | sed '/^[[:space:]]*$/N;/^\n$/D' | crontab -

echo "Cron instalado para o usuário: $(id -un)"
echo "Projeto: $PROJECT_DIR"
echo "Log: $LOG_FILE"
echo
echo "Bloco instalado:"
crontab -l | sed -n "/^${BEGIN_MARKER//\//\\/}$/,/^${END_MARKER//\//\\/}$/p"
