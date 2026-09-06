#!/usr/bin/env bash
# Wrapper de agendamento da pipeline B3.
#
# Semântica:
# - o slot diário vence às 21:00 em America/Sao_Paulo;
# - se o servidor inicia antes das 21:00, @reboot recupera o slot do dia anterior;
# - se inicia depois das 21:00, @reboot recupera o slot do próprio dia;
# - somente uma execução bem-sucedida marca o slot como concluído;
# - o lock deste script protege o estado do scheduler; run_pipeline.py mantém
#   seu próprio lock para proteger a pipeline em si.

set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"

TIMEZONE="America/Sao_Paulo"
SCHEDULE_HOUR=21
SCHEDULE_MINUTE=0
LOOKBACK_DAYS=10

PYTHON="${B3_PYTHON:-$PROJECT_DIR/.venv/bin/python}"
ENTRYPOINT="${B3_ENTRYPOINT:-$PROJECT_DIR/main.py}"
STATE_DIR="${B3_SCHEDULER_STATE_DIR:-$PROJECT_DIR/.state}"
LAST_SUCCESS_SLOT="$STATE_DIR/last_success_slot"
SCHEDULER_LOCK="$STATE_DIR/scheduler.lock"

mkdir -p "$STATE_DIR"

log() {
    printf '[%s] %s\n' "$(TZ="$TIMEZONE" date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

# Lock do scheduler para impedir corrida entre @reboot e cron.
exec 9>"$SCHEDULER_LOCK"
if ! flock -n 9; then
    log "Scheduler já está ativo; esta chamada será ignorada."
    exit 0
fi

TODAY="$(TZ="$TIMEZONE" date +%F)"
NOW_HM="$(TZ="$TIMEZONE" date +%H%M)"
SCHEDULE_HM="$(printf '%02d%02d' "$SCHEDULE_HOUR" "$SCHEDULE_MINUTE")"

# Antes do horário diário, o último slot devido é o de ontem. Depois do
# horário diário, o slot devido passa a ser o de hoje.
if (( 10#$NOW_HM >= 10#$SCHEDULE_HM )); then
    DUE_SLOT="$TODAY"
else
    DUE_SLOT="$(TZ="$TIMEZONE" date -d 'yesterday' +%F)"
fi

if [[ -f "$LAST_SUCCESS_SLOT" ]]; then
    LAST_SLOT="$(tr -d '[:space:]' < "$LAST_SUCCESS_SLOT")"
    if [[ "$LAST_SLOT" == "$DUE_SLOT" ]]; then
        log "Slot $DUE_SLOT já concluído com sucesso; nada a fazer."
        exit 0
    fi
fi

if [[ ! -x "$PYTHON" ]]; then
    log "ERRO: Python do virtualenv não encontrado/executável em $PYTHON"
    exit 65
fi
if [[ ! -f "$ENTRYPOINT" ]]; then
    log "ERRO: entrypoint não encontrado em $ENTRYPOINT"
    exit 66
fi
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
    log "ERRO: $PROJECT_DIR/.env não existe. Configure as credenciais Dolt antes do agendamento."
    exit 67
fi

log "Executando slot $DUE_SLOT via $ENTRYPOINT (lookback=$LOOKBACK_DAYS)."
cd "$PROJECT_DIR"

if "$PYTHON" "$ENTRYPOINT" --lookback-days "$LOOKBACK_DAYS"; then
    tmp_state="${LAST_SUCCESS_SLOT}.tmp.$$"
    printf '%s\n' "$DUE_SLOT" > "$tmp_state"
    mv -f "$tmp_state" "$LAST_SUCCESS_SLOT"
    log "Slot $DUE_SLOT concluído com sucesso."
else
    status=$?
    log "Pipeline falhou no slot $DUE_SLOT (exit=$status). O slot continuará pendente."
    exit "$status"
fi
