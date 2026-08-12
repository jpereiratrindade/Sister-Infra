#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

# Cria a primeira versão operacional do sister-infra no diretório atual.
# Uso:
#   cd /caminho/para/sister-infra
#   bash /caminho/para/setup_sister_infra.sh
#
# Depois:
#   ./bin/sister-infra bootstrap --profile lan
#   ./bin/sister-infra up --profile lan

ROOT="$(pwd -P)"

if [[ -e "$ROOT/bin/sister-infra" ]]; then
  echo "ERRO: $ROOT/bin/sister-infra já existe; não vou sobrescrever." >&2
  exit 2
fi

mkdir -p \
  "$ROOT/bin" \
  "$ROOT/config" \
  "$ROOT/gateway" \
  "$ROOT/secrets" \
  "$ROOT/.run/gateway" \
  "$ROOT/.run/logs"

chmod 700 "$ROOT/secrets" "$ROOT/.run" "$ROOT/.run/gateway" "$ROOT/.run/logs"

touch "$ROOT/secrets/.gitkeep"

cat > "$ROOT/.gitignore" <<'EOF'
.run/
secrets/*
!secrets/.gitkeep
config/production.env
*.pem
*.key
*.crt
EOF

cat > "$ROOT/config/common.env" <<'EOF'
# Diretórios dos projetos. Por padrão, são irmãos de sister-infra.
SISTER_DIR="${SISTER_DIR:-$WORKSPACE_DIR/SisTer}"
NEXO_DIR="${NEXO_DIR:-$WORKSPACE_DIR/sister-nexo}"

# Serviços internos — nunca devem ser expostos diretamente na LAN/Internet.
SISTER_ADDRESS="127.0.0.1"
SISTER_PORT="8000"
NEXO_ADDRESS="127.0.0.1"
NEXO_PORT="8015"

SISTER_HEALTH_PATH="/api/health"
NEXO_HEALTH_PATH="/api/health"

# Gateway
GATEWAY_LISTEN_PORT="8443"
SISTER_HOST="sister-gateway.test"
NEXO_HOST="nexo-gateway.test"

# HAProxy validado no laboratório. Pode ser sobrescrito por variável de ambiente.
HAPROXY_BIN="${HAPROXY_BIN:-/usr/local/sbin/haproxy-3.2.22}"

# Tempo máximo para aguardar cada serviço.
STARTUP_TIMEOUT_SECONDS="90"
EOF

cat > "$ROOT/config/dev.env" <<'EOF'
PROFILE="dev"
GATEWAY_LISTEN_ADDRESS="127.0.0.1"
TLS_MODE="lab"
SISTER_ENVIRONMENT="dev"
SISTER_RUN_PROFILE="dev-core"
EOF

cat > "$ROOT/config/lan.env" <<'EOF'
PROFILE="lan"
# Endereço atual do sister-gateway no laboratório.
# Altere aqui quando o IP da máquina mudar.
GATEWAY_LISTEN_ADDRESS="10.163.80.176"
TLS_MODE="lab"
SISTER_ENVIRONMENT="dev"
SISTER_RUN_PROFILE="dev-core"
EOF

cat > "$ROOT/config/production.env.example" <<'EOF'
# NÃO renomeie para production.env antes de preencher e revisar.
PROFILE="production"

# Exemplo: 0.0.0.0, IP da interface institucional ou endereço dedicado.
GATEWAY_LISTEN_ADDRESS="0.0.0.0"
GATEWAY_LISTEN_PORT="443"

# DNS reais de produção.
SISTER_HOST="sister.exemplo.org"
NEXO_HOST="nexo.exemplo.org"

# Produção nunca gera certificado automaticamente.
TLS_MODE="external"
TLS_PEM="/etc/sister-infra/tls/ecosystem.pem"

# Comandos de produção devem ser explicitamente definidos quando a implantação
# produtiva estiver materializada. Não reutilizamos dev-core silenciosamente.
SISTER_PRODUCTION_START_CMD=""
NEXO_PRODUCTION_START_CMD=""
SISTER_PRODUCTION_STOP_CMD=""
NEXO_PRODUCTION_STOP_CMD=""

# Gate opcional/esperado. Exemplo:
# PRODUCTION_GATE_CMD='cd "$SISTER_DIR" && python3 scripts/prod01_readiness.py'
PRODUCTION_GATE_CMD=""

# Dupla trava deliberada para impedir promoção acidental.
PRODUCTION_APPROVED="NO"
EOF

cat > "$ROOT/gateway/haproxy.cfg.in" <<'EOF'
global
    log stdout format raw local0
    maxconn 512

    ssl-default-bind-options ssl-min-ver TLSv1.2

defaults
    mode http
    log global
    option httplog
    option dontlognull
    option http-keep-alive
    timeout connect 3s
    timeout client 30s
    timeout server 30s
    timeout http-request 10s

frontend ecosystem_https
    bind __LISTEN_ADDRESS__:__LISTEN_PORT__ ssl crt __TLS_PEM__

    # Não confiar em identidade/forwarding fornecidos pelo cliente externo.
    http-request del-header Forwarded
    http-request del-header X-Forwarded-For
    http-request del-header X-Forwarded-Host
    http-request del-header X-Forwarded-Proto
    http-request del-header X-Sister-User
    http-request del-header X-Sister-Email
    http-request del-header X-Sister-Role
    http-request del-header X-Sister-Capabilities

    http-request set-header X-Forwarded-Proto https
    http-request set-header X-Forwarded-Host %[req.hdr(host)]

    acl host_sister hdr(host),lower -i __SISTER_HOST__ __SISTER_HOST__:__LISTEN_PORT__
    acl host_nexo   hdr(host),lower -i __NEXO_HOST__ __NEXO_HOST__:__LISTEN_PORT__

    # Host desconhecido falha fechado.
    http-request deny deny_status 421 unless host_sister or host_nexo

    use_backend nexo_backend if host_nexo
    use_backend sister_backend if host_sister

backend sister_backend
    option httpchk GET __SISTER_HEALTH_PATH__
    http-check expect status 200
    server sister __SISTER_ADDRESS__:__SISTER_PORT__ check inter 2s fall 3 rise 2

backend nexo_backend
    option httpchk GET __NEXO_HEALTH_PATH__
    http-check expect status 200
    server nexo __NEXO_ADDRESS__:__NEXO_PORT__ check inter 2s fall 3 rise 2
EOF

cat > "$ROOT/bin/sister-infra" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

INFRA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
WORKSPACE_DIR="$(dirname "$INFRA_ROOT")"
RUN_ROOT="$INFRA_ROOT/.run"
GATEWAY_RUN="$RUN_ROOT/gateway"
LOG_ROOT="$RUN_ROOT/logs"
PROFILE="lan"
COMMAND=""

usage() {
  cat <<'USAGE'
SisTer Infra — harness operacional do ecossistema

Uso:
  ./bin/sister-infra <comando> [--profile dev|lan|production]

Comandos:
  bootstrap   prepara diretórios e TLS do perfil
  up          sobe Nexo, SisTer e o gateway único
  down        derruba gateway e tenta parar SisTer/Nexo sem destruir dados
  status      mostra saúde, processos e URLs
  verify      valida configuração e endpoints
  gateway     reinicia apenas o HAProxy do sister-infra

Exemplos:
  ./bin/sister-infra bootstrap --profile lan
  ./bin/sister-infra up --profile lan
  ./bin/sister-infra status --profile lan
  ./bin/sister-infra down --profile lan

Produção exige config/production.env, PRODUCTION_APPROVED=YES e:
  SISTER_INFRA_PRODUCTION_CONFIRM=YES ./bin/sister-infra up --profile production
USAGE
}

log()  { printf '[infra] %s\n' "$*"; }
pass() { printf '[PASS] %s\n' "$*"; }
warn() { printf '[WARN] %s\n' "$*" >&2; }
die()  { printf '[FAIL] %s\n' "$*" >&2; exit 2; }

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "comando obrigatório ausente: $1"
}

load_profile() {
  # shellcheck disable=SC1091
  source "$INFRA_ROOT/config/common.env"

  local profile_file="$INFRA_ROOT/config/${PROFILE}.env"
  if [[ "$PROFILE" == "production" && ! -f "$profile_file" ]]; then
    die "produção não configurada. Copie config/production.env.example para config/production.env e revise."
  fi
  [[ -f "$profile_file" ]] || die "perfil inexistente: $PROFILE"
  # shellcheck disable=SC1090
  source "$profile_file"

  mkdir -p "$GATEWAY_RUN" "$LOG_ROOT" "$INFRA_ROOT/secrets"
  chmod 700 "$RUN_ROOT" "$GATEWAY_RUN" "$LOG_ROOT" "$INFRA_ROOT/secrets" 2>/dev/null || true

  TLS_PEM="${TLS_PEM:-$INFRA_ROOT/secrets/ecosystem-lab.pem}"
  CA_CERT="${CA_CERT:-$INFRA_ROOT/secrets/ecosystem-lab-ca.crt}"
  CA_KEY="${CA_KEY:-$INFRA_ROOT/secrets/ecosystem-lab-ca.key}"
  GATEWAY_CFG="$GATEWAY_RUN/haproxy-${PROFILE}.cfg"
  GATEWAY_PID="$GATEWAY_RUN/haproxy-${PROFILE}.pid"
  GATEWAY_LOG="$LOG_ROOT/haproxy-${PROFILE}.log"
}

preflight_common() {
  require_command curl
  require_command sed
  require_command openssl

  [[ -d "$SISTER_DIR" ]] || die "SisTer não encontrado: $SISTER_DIR"
  [[ -d "$NEXO_DIR" ]] || die "Nexo não encontrado: $NEXO_DIR"

  if [[ ! -x "$HAPROXY_BIN" ]]; then
    local detected
    detected="$(command -v haproxy 2>/dev/null || true)"
    [[ -n "$detected" ]] || die "HAProxy não encontrado em $HAPROXY_BIN nem no PATH"
    HAPROXY_BIN="$detected"
  fi

  "$HAPROXY_BIN" -vv >/dev/null 2>&1 || die "HAProxy não executável: $HAPROXY_BIN"
}

production_preflight() {
  [[ "$PROFILE" == "production" ]] || return 0

  [[ "${PRODUCTION_APPROVED:-NO}" == "YES" ]] || \
    die "PRODUCTION_APPROVED=YES não está definido em config/production.env"

  [[ "${SISTER_INFRA_PRODUCTION_CONFIRM:-NO}" == "YES" ]] || \
    die "produção exige SISTER_INFRA_PRODUCTION_CONFIRM=YES no comando"

  [[ "${TLS_MODE:-}" == "external" ]] || die "produção exige TLS_MODE=external"
  [[ -f "$TLS_PEM" ]] || die "TLS PEM de produção não encontrado: $TLS_PEM"
  [[ -n "${SISTER_PRODUCTION_START_CMD:-}" ]] || die "SISTER_PRODUCTION_START_CMD não definido"
  [[ -n "${NEXO_PRODUCTION_START_CMD:-}" ]] || die "NEXO_PRODUCTION_START_CMD não definido"

  if [[ -n "${PRODUCTION_GATE_CMD:-}" ]]; then
    log "Executando gate de produção..."
    bash -lc "$PRODUCTION_GATE_CMD" || die "gate de produção bloqueou a promoção"
    pass "gate de produção"
  else
    die "PRODUCTION_GATE_CMD não definido; produção falha fechado"
  fi
}

migrate_existing_lab_tls() {
  [[ "$PROFILE" != "production" ]] || return 0
  [[ -f "$TLS_PEM" && -f "$CA_CERT" ]] && return 0

  local old="$SISTER_DIR/.run/gateway"
  if [[ -f "$old/gateway-lab.pem" && -f "$old/ca-lab.crt" ]]; then
    log "Migrando uma cópia do TLS de laboratório já confiado no SisTer para sister-infra..."
    cp -p "$old/gateway-lab.pem" "$TLS_PEM"
    cp -p "$old/ca-lab.crt" "$CA_CERT"
    chmod 600 "$TLS_PEM"
    chmod 644 "$CA_CERT"
    pass "certificado de laboratório copiado para sister-infra"
  fi
}

generate_lab_tls() {
  [[ "$PROFILE" != "production" ]] || return 0
  [[ "${TLS_MODE:-lab}" == "lab" ]] || return 0

  migrate_existing_lab_tls
  [[ -f "$TLS_PEM" && -f "$CA_CERT" ]] && return 0

  log "Gerando CA e certificado TLS próprios do sister-infra..."
  local tmp="$GATEWAY_RUN/tls"
  rm -rf "$tmp"
  mkdir -p "$tmp"
  chmod 700 "$tmp"

  openssl genrsa -out "$CA_KEY" 4096 >/dev/null 2>&1
  chmod 600 "$CA_KEY"
  openssl req -x509 -new -nodes \
    -key "$CA_KEY" \
    -sha256 -days 3650 \
    -subj "/CN=SisTer Infra Lab CA" \
    -out "$CA_CERT" >/dev/null 2>&1

  openssl genrsa -out "$tmp/gateway.key" 3072 >/dev/null 2>&1
  cat > "$tmp/openssl.cnf" <<CFG
[req]
prompt = no
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = ${SISTER_HOST}

[req_ext]
subjectAltName = @alt_names

[alt_names]
DNS.1 = ${SISTER_HOST}
DNS.2 = ${NEXO_HOST}
CFG

  openssl req -new \
    -key "$tmp/gateway.key" \
    -out "$tmp/gateway.csr" \
    -config "$tmp/openssl.cnf" >/dev/null 2>&1

  cat > "$tmp/ext.cnf" <<CFG
subjectAltName=DNS:${SISTER_HOST},DNS:${NEXO_HOST}
extendedKeyUsage=serverAuth
keyUsage=digitalSignature,keyEncipherment
CFG

  openssl x509 -req \
    -in "$tmp/gateway.csr" \
    -CA "$CA_CERT" -CAkey "$CA_KEY" -CAcreateserial \
    -out "$tmp/gateway.crt" \
    -days 825 -sha256 \
    -extfile "$tmp/ext.cnf" >/dev/null 2>&1

  cat "$tmp/gateway.crt" "$tmp/gateway.key" > "$TLS_PEM"
  chmod 600 "$TLS_PEM"
  chmod 644 "$CA_CERT"
  rm -rf "$tmp"
  pass "TLS lab gerado para $SISTER_HOST e $NEXO_HOST"
}

render_gateway() {
  [[ -f "$TLS_PEM" ]] || die "TLS PEM ausente: $TLS_PEM"

  sed \
    -e "s|__LISTEN_ADDRESS__|$GATEWAY_LISTEN_ADDRESS|g" \
    -e "s|__LISTEN_PORT__|$GATEWAY_LISTEN_PORT|g" \
    -e "s|__TLS_PEM__|$TLS_PEM|g" \
    -e "s|__SISTER_HOST__|$SISTER_HOST|g" \
    -e "s|__NEXO_HOST__|$NEXO_HOST|g" \
    -e "s|__SISTER_ADDRESS__|$SISTER_ADDRESS|g" \
    -e "s|__SISTER_PORT__|$SISTER_PORT|g" \
    -e "s|__NEXO_ADDRESS__|$NEXO_ADDRESS|g" \
    -e "s|__NEXO_PORT__|$NEXO_PORT|g" \
    -e "s|__SISTER_HEALTH_PATH__|$SISTER_HEALTH_PATH|g" \
    -e "s|__NEXO_HEALTH_PATH__|$NEXO_HEALTH_PATH|g" \
    "$INFRA_ROOT/gateway/haproxy.cfg.in" > "$GATEWAY_CFG"

  "$HAPROXY_BIN" -c -f "$GATEWAY_CFG" >/dev/null || die "configuração HAProxy inválida"
  pass "configuração HAProxy válida"
}

pid_alive() {
  local file="$1"
  [[ -f "$file" ]] || return 1
  local pid
  pid="$(cat "$file" 2>/dev/null || true)"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

stop_gateway() {
  if pid_alive "$GATEWAY_PID"; then
    local pid
    pid="$(cat "$GATEWAY_PID")"
    log "Parando HAProxy PID $pid..."
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 50); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      warn "HAProxy não encerrou graciosamente; enviando TERM novamente"
      kill -TERM "$pid" 2>/dev/null || true
    fi
  fi
  rm -f "$GATEWAY_PID"
}

start_gateway() {
  stop_gateway
  render_gateway
  log "Subindo gateway $GATEWAY_LISTEN_ADDRESS:$GATEWAY_LISTEN_PORT..."
  "$HAPROXY_BIN" -D -f "$GATEWAY_CFG" -p "$GATEWAY_PID" >>"$GATEWAY_LOG" 2>&1
  sleep 0.4
  pid_alive "$GATEWAY_PID" || die "HAProxy não permaneceu ativo; veja $GATEWAY_LOG"
  pass "gateway ativo"
}

health_ok() {
  local address="$1" port="$2" path="$3"
  curl --noproxy '*' -fsS --max-time 2 "http://${address}:${port}${path}" >/dev/null 2>&1
}

wait_health() {
  local name="$1" address="$2" port="$3" path="$4"
  local deadline=$((SECONDS + STARTUP_TIMEOUT_SECONDS))
  while (( SECONDS < deadline )); do
    if health_ok "$address" "$port" "$path"; then
      pass "$name saudável em ${address}:${port}"
      return 0
    fi
    sleep 1
  done
  die "$name não respondeu em ${address}:${port}${path} após ${STARTUP_TIMEOUT_SECONDS}s"
}

start_nexo() {
  if health_ok "$NEXO_ADDRESS" "$NEXO_PORT" "$NEXO_HEALTH_PATH"; then
    pass "Nexo já estava ativo"
    return 0
  fi

  if [[ "$PROFILE" == "production" ]]; then
    log "Subindo Nexo (produção)..."
    (cd "$NEXO_DIR" && bash -lc "$NEXO_PRODUCTION_START_CMD")
  else
    [[ -x "$NEXO_DIR/scripts/run.sh" ]] || die "Nexo sem scripts/run.sh executável"
    log "Subindo Nexo..."
    (cd "$NEXO_DIR" && ./scripts/run.sh)
  fi
  wait_health "Nexo" "$NEXO_ADDRESS" "$NEXO_PORT" "$NEXO_HEALTH_PATH"
}

start_sister() {
  if health_ok "$SISTER_ADDRESS" "$SISTER_PORT" "$SISTER_HEALTH_PATH"; then
    pass "SisTer já estava ativo"
    return 0
  fi

  if [[ "$PROFILE" == "production" ]]; then
    log "Subindo SisTer (produção)..."
    (cd "$SISTER_DIR" && bash -lc "$SISTER_PRODUCTION_START_CMD")
  else
    [[ -x "$SISTER_DIR/scripts/run_all.sh" ]] || die "SisTer sem scripts/run_all.sh executável"
    log "Subindo SisTer em ${SISTER_RUN_PROFILE:-dev-core}..."
    (
      cd "$SISTER_DIR"
      export SISTER_NEXO_PORT="$NEXO_PORT"
      export SISTER_NEXO_PUBLIC_URL="https://${NEXO_HOST}:${GATEWAY_LISTEN_PORT}"
      ./scripts/run_all.sh --profile "${SISTER_RUN_PROFILE:-dev-core}"
    )
  fi
  wait_health "SisTer" "$SISTER_ADDRESS" "$SISTER_PORT" "$SISTER_HEALTH_PATH"
}

stop_sister() {
  if [[ "$PROFILE" == "production" ]]; then
    if [[ -n "${SISTER_PRODUCTION_STOP_CMD:-}" ]]; then
      (cd "$SISTER_DIR" && bash -lc "$SISTER_PRODUCTION_STOP_CMD") || warn "falha ao parar SisTer de produção"
    else
      warn "SISTER_PRODUCTION_STOP_CMD não definido; SisTer não foi parado"
    fi
    return
  fi

  if [[ -x "$SISTER_DIR/scripts/app/stop.sh" ]]; then
    (cd "$SISTER_DIR" && ./scripts/app/stop.sh "${SISTER_ENVIRONMENT:-dev}") || warn "SisTer reportou erro ao parar"
  else
    warn "scripts/app/stop.sh não encontrado; SisTer não foi parado"
  fi
}

stop_nexo() {
  if [[ "$PROFILE" == "production" ]]; then
    if [[ -n "${NEXO_PRODUCTION_STOP_CMD:-}" ]]; then
      (cd "$NEXO_DIR" && bash -lc "$NEXO_PRODUCTION_STOP_CMD") || warn "falha ao parar Nexo de produção"
    else
      warn "NEXO_PRODUCTION_STOP_CMD não definido; Nexo não foi parado"
    fi
    return
  fi

  # Preferir script próprio do Nexo, caso exista em versões futuras.
  if [[ -x "$NEXO_DIR/scripts/stop.sh" ]]; then
    (cd "$NEXO_DIR" && ./scripts/stop.sh) || warn "Nexo reportou erro ao parar"
    return
  fi

  # A versão atual conhecida executa nexo-app e nexo-db via Podman Compose.
  # Removemos somente os containers conhecidos; volumes persistentes NÃO são removidos.
  if command -v podman >/dev/null 2>&1; then
    local app db
    app="$(podman ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^sister-nexo-.*app$|^sister-nexo-dev-app$' | head -n1 || true)"
    db="$(podman ps -a --format '{{.Names}}' 2>/dev/null | grep -E '^sister-nexo-.*db$|^sister-nexo-dev-db$' | head -n1 || true)"
    [[ -z "$app" ]] || podman stop "$app" >/dev/null 2>&1 || true
    [[ -z "$db" ]]  || podman stop "$db"  >/dev/null 2>&1 || true
    if [[ -n "$app$db" ]]; then
      pass "containers Nexo parados; volumes preservados"
    else
      warn "containers Nexo não localizados; nada foi removido"
    fi
  else
    warn "Podman ausente e scripts/stop.sh inexistente; Nexo não foi parado"
  fi
}

bootstrap() {
  preflight_common
  if [[ "$PROFILE" == "production" ]]; then
    [[ "${TLS_MODE:-}" == "external" ]] || die "produção exige TLS_MODE=external"
    [[ -f "$TLS_PEM" ]] || die "TLS de produção ausente: $TLS_PEM"
  else
    generate_lab_tls
  fi
  render_gateway

  echo
  pass "bootstrap concluído ($PROFILE)"
  if [[ "$PROFILE" != "production" ]]; then
    echo "CA de laboratório: $CA_CERT"
  fi
}

verify_gateway_urls() {
  local cacert_args=()
  if [[ "$PROFILE" != "production" && -f "$CA_CERT" ]]; then
    cacert_args=(--cacert "$CA_CERT")
  fi

  curl --noproxy '*' -fsS --max-time 5 \
    "${cacert_args[@]}" \
    --resolve "$SISTER_HOST:$GATEWAY_LISTEN_PORT:$GATEWAY_LISTEN_ADDRESS" \
    "https://$SISTER_HOST:$GATEWAY_LISTEN_PORT$SISTER_HEALTH_PATH" >/dev/null \
      && pass "SisTer via gateway" \
      || die "SisTer não respondeu via gateway"

  curl --noproxy '*' -fsS --max-time 5 \
    "${cacert_args[@]}" \
    --resolve "$NEXO_HOST:$GATEWAY_LISTEN_PORT:$GATEWAY_LISTEN_ADDRESS" \
    "https://$NEXO_HOST:$GATEWAY_LISTEN_PORT$NEXO_HEALTH_PATH" >/dev/null \
      && pass "Nexo via gateway" \
      || die "Nexo não respondeu via gateway"
}

cmd_up() {
  preflight_common
  production_preflight
  [[ "$PROFILE" == "production" ]] || generate_lab_tls

  # O Nexo sobe primeiro porque o SisTer observa sua saúde no catálogo.
  start_nexo
  start_sister
  start_gateway
  verify_gateway_urls

  echo
  echo "Ecossistema ativo ($PROFILE)"
  echo "  SisTer: https://${SISTER_HOST}:${GATEWAY_LISTEN_PORT}"
  echo "  Nexo:   https://${NEXO_HOST}:${GATEWAY_LISTEN_PORT}"
  if [[ "$PROFILE" == "lan" ]]; then
    echo "  Gateway LAN: ${GATEWAY_LISTEN_ADDRESS}:${GATEWAY_LISTEN_PORT}"
  fi
}

cmd_down() {
  preflight_common
  stop_gateway
  stop_sister
  stop_nexo
  pass "encerramento solicitado; dados persistentes preservados"
}

cmd_status() {
  preflight_common

  echo "Perfil: $PROFILE"
  echo "Infra:  $INFRA_ROOT"
  echo "SisTer: $SISTER_DIR"
  echo "Nexo:   $NEXO_DIR"
  echo

  if health_ok "$SISTER_ADDRESS" "$SISTER_PORT" "$SISTER_HEALTH_PATH"; then
    pass "SisTer interno http://${SISTER_ADDRESS}:${SISTER_PORT}"
  else
    warn "SisTer interno OFFLINE"
  fi

  if health_ok "$NEXO_ADDRESS" "$NEXO_PORT" "$NEXO_HEALTH_PATH"; then
    pass "Nexo interno http://${NEXO_ADDRESS}:${NEXO_PORT}"
  else
    warn "Nexo interno OFFLINE"
  fi

  if pid_alive "$GATEWAY_PID"; then
    pass "Gateway HAProxy PID $(cat "$GATEWAY_PID")"
  else
    warn "Gateway HAProxy OFFLINE"
  fi

  echo
  echo "URLs esperadas:"
  echo "  https://${SISTER_HOST}:${GATEWAY_LISTEN_PORT}"
  echo "  https://${NEXO_HOST}:${GATEWAY_LISTEN_PORT}"
}

cmd_verify() {
  preflight_common
  production_preflight
  [[ "$PROFILE" == "production" ]] || generate_lab_tls
  render_gateway
  wait_health "SisTer" "$SISTER_ADDRESS" "$SISTER_PORT" "$SISTER_HEALTH_PATH"
  wait_health "Nexo" "$NEXO_ADDRESS" "$NEXO_PORT" "$NEXO_HEALTH_PATH"
  pid_alive "$GATEWAY_PID" || die "gateway não está ativo"
  verify_gateway_urls
  pass "ecossistema verificado"
}

parse_args() {
  [[ $# -ge 1 ]] || { usage; exit 2; }
  COMMAND="$1"
  shift

  while [[ $# -gt 0 ]]; do
    case "$1" in
      --profile)
        [[ $# -ge 2 ]] || die "--profile exige valor"
        PROFILE="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        die "opção desconhecida: $1"
        ;;
    esac
  done

  case "$PROFILE" in
    dev|lan|production) ;;
    *) die "perfil inválido: $PROFILE" ;;
  esac
}

main() {
  parse_args "$@"
  load_profile

  case "$COMMAND" in
    bootstrap) bootstrap ;;
    up)        cmd_up ;;
    down)      cmd_down ;;
    status)    cmd_status ;;
    verify)    cmd_verify ;;
    gateway)
      preflight_common
      production_preflight
      [[ "$PROFILE" == "production" ]] || generate_lab_tls
      start_gateway
      verify_gateway_urls
      ;;
    help|-h|--help) usage ;;
    *) die "comando desconhecido: $COMMAND" ;;
  esac
}

main "$@"
EOF

chmod +x "$ROOT/bin/sister-infra"

cat > "$ROOT/README.md" <<'EOF'
# sister-infra

Harness operacional externo aos repositórios SisTer e sister-nexo.

## Primeiro uso no laboratório

```bash
./bin/sister-infra bootstrap --profile lan
./bin/sister-infra up --profile lan
```

Depois:

```bash
./bin/sister-infra status --profile lan
./bin/sister-infra verify --profile lan
./bin/sister-infra down --profile lan
```

## Perfis

- `dev`: gateway somente em `127.0.0.1:8443`;
- `lan`: gateway no endereço definido em `config/lan.env`;
- `production`: sempre explícito, exige `config/production.env`, TLS externo,
  gate e dupla autorização.

## TLS de laboratório

No primeiro bootstrap, se existir o certificado já usado pelo SisTer em
`SisTer/.run/gateway`, o sister-infra copia esse material para preservar a CA
já instalada nos clientes. Se ele não existir, uma nova CA de laboratório é
gerada em `secrets/`.

Nunca versione `secrets/` nem `config/production.env`.
EOF

# Validação sintática antes de declarar sucesso.
bash -n "$ROOT/bin/sister-infra"

cat <<EOF

sister-infra criado em:
  $ROOT

Próximo comando recomendado:
  ./bin/sister-infra bootstrap --profile lan

Depois:
  ./bin/sister-infra up --profile lan
EOF
