#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"

# shellcheck disable=SC1091
source "$ROOT/bin/sister-infra"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

pass_test() {
  printf '[PASS TEST] %s\n' "$*"
}

fail_test() {
  printf '[FAIL TEST] %s\n' "$*" >&2
  exit 1
}

write_resolved_deployment() {
  python3 - "$SISTER_RESOLVED_DEPLOYMENT_FILE" "$@" <<'PY'
import json
import sys
from pathlib import Path

out = Path(sys.argv[1])
hosts = sys.argv[2:]
components = [
    {
        "component_id": f"component_{index}",
        "system_id": f"system_{index}",
        "component_path": f"components/component_{index}",
        "runtime": {
            "transport": "tcp",
            "listen": "127.0.0.1",
            "port": 18000 + index,
        },
        "probe": {"health_path": "/health"},
        "gateway": {"host": host},
    }
    for index, host in enumerate(hosts, start=1)
]
out.write_text(
    json.dumps(
        {
            "schema": "sister.infra.deployment.resolved/1",
            "status": "READY",
            "deployment_id": "tls-fixture",
            "candidate_id": "wc-tls-fixture",
            "composition_id": "tls-fixture",
            "components": components,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

setup_case() {
  local name="$1"

  CASE="$TMP/$name"

  mkdir -p \
    "$CASE/secrets" \
    "$CASE/run" \
    "$CASE/sister/.run/gateway"

  PROFILE="lan"
  TLS_MODE="lab"

  SISTER_DIR="$CASE/sister"

  GATEWAY_RUN="$CASE/run"
  TLS_PEM="$CASE/secrets/ecosystem-lab.pem"
  CA_CERT="$CASE/secrets/ecosystem-lab-ca.crt"
  CA_KEY="$CASE/secrets/ecosystem-lab-ca.key"
  SISTER_RESOLVED_DEPLOYMENT_FILE="$CASE/resolved.json"

  write_resolved_deployment \
    "alpha-gateway.test" \
    "beta-gateway.test"

  TLS_RENEW_BEFORE_SECONDS=2592000
  CA_RENEW_BEFORE_SECONDS=2592000
}

make_ca() {
  local days="$1"

  openssl genrsa -out "$CA_KEY" 2048 >/dev/null 2>&1

  openssl req \
    -x509 \
    -new \
    -nodes \
    -key "$CA_KEY" \
    -sha256 \
    -days "$days" \
    -subj "/CN=Test SisTer Infra CA" \
    -out "$CA_CERT" >/dev/null 2>&1
}

make_cert() {
  local days="$1"
  shift

  local -a hosts=("$@")
  local issue="$CASE/issue"

  rm -rf "$issue"
  mkdir -p "$issue"

  openssl genrsa -out "$issue/server.key" 2048 >/dev/null 2>&1

  {
    cat <<CFG
[req]
prompt = no
distinguished_name = dn
req_extensions = req_ext

[dn]
CN = ${hosts[0]}

[req_ext]
subjectAltName = @alt_names

[alt_names]
CFG

    local i=1
    local host
    for host in "${hosts[@]}"; do
      printf 'DNS.%d = %s\n' "$i" "$host"
      i=$((i + 1))
    done
  } > "$issue/openssl.cnf"

  openssl req \
    -new \
    -key "$issue/server.key" \
    -out "$issue/server.csr" \
    -config "$issue/openssl.cnf" >/dev/null 2>&1

  {
    printf 'subjectAltName='
    local first=1
    local host

    for host in "${hosts[@]}"; do
      [[ "$first" -eq 1 ]] || printf ','
      printf 'DNS:%s' "$host"
      first=0
    done

    printf '\nextendedKeyUsage=serverAuth\n'
    printf 'keyUsage=digitalSignature,keyEncipherment\n'
  } > "$issue/ext.cnf"

  openssl x509 \
    -req \
    -in "$issue/server.csr" \
    -CA "$CA_CERT" \
    -CAkey "$CA_KEY" \
    -CAserial "$issue/ca.srl" \
    -CAcreateserial \
    -out "$issue/server.crt" \
    -days "$days" \
    -sha256 \
    -extfile "$issue/ext.cnf" >/dev/null 2>&1

  cat "$issue/server.crt" "$issue/server.key" > "$TLS_PEM"
  chmod 600 "$TLS_PEM"
}

sha_file() {
  sha256sum "$1" | awk '{print $1}'
}

echo "=== TEST 1: bootstrap novo ==="
setup_case bootstrap
generate_lab_tls

lab_tls_ca_valid || fail_test "CA nova inválida"
lab_tls_cert_valid || fail_test "certificado novo inválido"
lab_tls_cert_signed_by_current_ca || fail_test "assinatura inválida"
lab_tls_cert_matches_expected_hosts || fail_test "SANs divergentes"

pass_test "bootstrap gera cadeia válida com hosts do deployment"

echo
echo "=== TEST 2: idempotência ==="

ca_before="$(sha_file "$CA_CERT")"
pem_before="$(sha_file "$TLS_PEM")"

generate_lab_tls

ca_after="$(sha_file "$CA_CERT")"
pem_after="$(sha_file "$TLS_PEM")"

[[ "$ca_before" == "$ca_after" ]] || \
  fail_test "CA válida foi alterada sem necessidade"

[[ "$pem_before" == "$pem_after" ]] || \
  fail_test "certificado válido foi alterado sem necessidade"

pass_test "segunda execução preserva bytes"

echo
echo "=== TEST 3: SAN ausente preserva CA ==="
setup_case missing-san

make_ca 3650
make_cert 825 \
  "alpha-gateway.test"

ca_before="$(sha_file "$CA_CERT")"

lab_tls_cert_matches_expected_hosts && \
  fail_test "fixture deveria estar sem SAN beta"

generate_lab_tls

ca_after="$(sha_file "$CA_CERT")"

[[ "$ca_before" == "$ca_after" ]] || \
  fail_test "CA foi rotacionada ao corrigir somente SAN"

lab_tls_cert_matches_expected_hosts || \
  fail_test "beta não foi incluído após renovação"

pass_test "SAN ausente reemite apenas certificado"

echo
echo "=== TEST 4: certificado em janela preventiva preserva CA ==="
setup_case expiring-cert

make_ca 3650
make_cert 1 \
  "alpha-gateway.test" \
  "beta-gateway.test"

TLS_RENEW_BEFORE_SECONDS=172800

ca_before="$(sha_file "$CA_CERT")"
pem_before="$(sha_file "$TLS_PEM")"

lab_tls_cert_valid && \
  fail_test "fixture deveria estar na janela preventiva do certificado"

generate_lab_tls

ca_after="$(sha_file "$CA_CERT")"
pem_after="$(sha_file "$TLS_PEM")"

[[ "$ca_before" == "$ca_after" ]] || \
  fail_test "CA foi alterada ao renovar somente certificado"

[[ "$pem_before" != "$pem_after" ]] || \
  fail_test "certificado não foi renovado"

lab_tls_cert_valid || \
  fail_test "novo certificado permanece na janela preventiva"

pass_test "certificado é renovado preservando CA"

echo
echo "=== TEST 5: CA em janela preventiva força rotação ==="
setup_case expiring-ca

make_ca 1
make_cert 1 \
  "alpha-gateway.test" \
  "beta-gateway.test"

CA_RENEW_BEFORE_SECONDS=172800
TLS_RENEW_BEFORE_SECONDS=0

ca_before="$(sha_file "$CA_CERT")"

lab_tls_ca_valid && \
  fail_test "fixture deveria estar na janela preventiva da CA"

generate_lab_tls

ca_after="$(sha_file "$CA_CERT")"

[[ "$ca_before" != "$ca_after" ]] || \
  fail_test "CA não foi rotacionada"

lab_tls_ca_valid || \
  fail_test "nova CA inválida"

lab_tls_cert_signed_by_current_ca || \
  fail_test "novo certificado não pertence à nova CA"

lab_tls_cert_matches_expected_hosts || \
  fail_test "novo certificado perdeu SANs"

pass_test "CA em expiração rotaciona cadeia completa"

echo
echo "=== TEST 6: adicionar host deriva novo SAN ==="
setup_case add-host

make_ca 3650
make_cert 825 \
  "alpha-gateway.test" \
  "beta-gateway.test"

write_resolved_deployment \
  "alpha-gateway.test" \
  "beta-gateway.test" \
  "gamma-gateway.test"

generate_lab_tls

lab_tls_cert_matches_expected_hosts || \
  fail_test "gamma não foi derivado do deployment"

lab_tls_cert_has_host "gamma-gateway.test" || \
  fail_test "certificado não contém gamma"

pass_test "adicionar gamma ao deployment adiciona SAN"

echo
echo "=== TEST 7: remover host elimina SAN excedente ==="

write_resolved_deployment \
  "alpha-gateway.test" \
  "gamma-gateway.test"

generate_lab_tls

lab_tls_cert_matches_expected_hosts || \
  fail_test "SANs não acompanham remoção de beta"

lab_tls_cert_has_host "beta-gateway.test" && \
  fail_test "certificado ainda contém beta removido"

pass_test "remover beta do deployment remove SAN"

echo
echo "=== RESULTADO ==="
echo "[PASS] TLS lifecycle regression suite"
