#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI="$ROOT/bin/sister-data-paths"

TMP="$(mktemp -d -t sister-data-plane-test.XXXXXX)"

cleanup() {
    rm -rf "$TMP"
}

trap cleanup EXIT INT TERM

fail() {
    printf '[FAIL] %s\n' "$*" >&2
    exit 1
}

expect_line() {
    local output="$1"
    local expected="$2"

    grep -Fxq "$expected" <<<"$output" || {
        printf 'Esperado:\n%s\n\nObtido:\n%s\n' \
            "$expected" "$output" >&2
        fail "linha esperada ausente"
    }
}

DATA_ROOT="$TMP/sister-data"

[[ ! -e "$DATA_ROOT" ]] || fail "data root de teste já existe"

dev="$(
    "$CLI" show \
        --root "$DATA_ROOT" \
        --class development \
        --component alpha \
        --component beta
)"

expect_line "$dev" "deployment_class=development"
expect_line "$dev" "environment_root=$DATA_ROOT/development"
expect_line "$dev" $'component_state_dir=alpha\t'"$DATA_ROOT/development/components/alpha"
expect_line "$dev" $'component_state_dir=beta\t'"$DATA_ROOT/development/components/beta"

[[ ! -e "$DATA_ROOT" ]] || \
    fail "resolvedor criou diretório durante show"

candidate="$(
    "$CLI" show \
        --root "$DATA_ROOT" \
        --class candidate \
        --candidate-id rc-20260819 \
        --component alpha \
        --component beta
)"

expect_line "$candidate" "deployment_class=candidate"
expect_line "$candidate" \
    "environment_root=$DATA_ROOT/candidate/rc-20260819"
expect_line "$candidate" $'component_state_dir=alpha\t'"$DATA_ROOT/candidate/rc-20260819/components/alpha"
expect_line "$candidate" $'component_state_dir=beta\t'"$DATA_ROOT/candidate/rc-20260819/components/beta"

operational="$(
    "$CLI" show \
        --root "$DATA_ROOT" \
        --class operational \
        --component alpha \
        --component beta
)"

expect_line "$operational" "deployment_class=operational"
expect_line "$operational" \
    "environment_root=$DATA_ROOT/operational"
expect_line "$operational" $'component_state_dir=alpha\t'"$DATA_ROOT/operational/components/alpha"
expect_line "$operational" $'component_state_dir=beta\t'"$DATA_ROOT/operational/components/beta"

if "$CLI" show \
    --root "$DATA_ROOT" \
    --class candidate \
    >/dev/null 2>&1
then
    fail "candidate sem candidate-id foi aceita"
fi

if "$CLI" show \
    --root "$DATA_ROOT" \
    --class invalid \
    >/dev/null 2>&1
then
    fail "deployment class inválida foi aceita"
fi

if "$CLI" show \
    --root relative/path \
    --class development \
    >/dev/null 2>&1
then
    fail "data root relativo foi aceito"
fi

if "$CLI" show \
    --root "$DATA_ROOT" \
    --class candidate \
    --candidate-id '../escape' \
    >/dev/null 2>&1
then
    fail "candidate-id inseguro foi aceito"
fi

if "$CLI" show \
    --root "$DATA_ROOT" \
    --class development \
    --candidate-id rc-improper \
    >/dev/null 2>&1
then
    fail "development aceitou candidate-id"
fi

if "$CLI" show \
    --root "$DATA_ROOT" \
    --class operational \
    --candidate-id rc-improper \
    >/dev/null 2>&1
then
    fail "operational aceitou candidate-id"
fi

[[ ! -e "$DATA_ROOT" ]] || \
    fail "testes de resolução criaram o data root"

echo "[PASS] development paths"
echo "[PASS] candidate paths"
echo "[PASS] operational paths"
echo "[PASS] candidate-id obrigatório"
echo "[PASS] deployment class validada"
echo "[PASS] data root absoluto"
echo "[PASS] candidate-id sanitizado"
echo "[PASS] candidate-id restrito ao candidate"
echo "[PASS] resolução é read-only"
