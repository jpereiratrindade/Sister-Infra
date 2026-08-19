#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CLI="$ROOT/bin/sister-workstation"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export HOME="$TMP/home"
export SISTER_WORKSTATION_INSTALL_ROOT="$HOME/.local/share/sister"
export SISTER_WORKSTATION_CONFIG_ROOT="$HOME/.config/sister/workstation"
export SISTER_WORKSTATION_STATE_ROOT="$HOME/.local/state/sister/workstation"
export SISTER_WORKSTATION_SYSTEMD_ROOT="$HOME/.config/systemd/user"
export SISTER_WORKSTATION_BIN_ROOT="$HOME/.local/bin"
export SISTER_WORKSTATION_TEST_MODE=1

WORKSPACE="$TMP/workspace"
mkdir -p "$HOME" "$WORKSPACE"

make_repo() {
  local path="$1"
  local name="$2"

  mkdir -p "$path"
  git -C "$path" init -q
  git -C "$path" config user.email test@example.invalid
  git -C "$path" config user.name "SisTer Test"

  printf '%s\n' "$name" > "$path/README.md"

  case "$name" in
    sister-infra)
      mkdir -p "$path/bin" "$path/secrets"

      cp "$ROOT/bin/sister-infra" "$path/bin/sister-infra"
      cp "$ROOT/bin/sister-workstation" "$path/bin/sister-workstation"
      chmod +x "$path/bin/"*

      # Reproduz a política real:
      # .gitkeep rastreado; material TLS operacional ignorado.
      cat > "$path/.gitignore" <<'EOF'
secrets/*
!secrets/.gitkeep
EOF
      : > "$path/secrets/.gitkeep"
      ;;

    sister-nexo)
      cat > "$path/.env.example" <<'EOF'
NEXO_HOST=127.0.0.1
NEXO_PORT=8015
NEXO_DB_PASSWORD=test-only
EOF
      ;;
  esac

  git -C "$path" add .
  git -C "$path" commit -q -m init
}

make_repo "$WORKSPACE/sister-infra" sister-infra
make_repo "$WORKSPACE/SisTer" SisTer
make_repo "$WORKSPACE/sister-nexo" sister-nexo
make_repo "$WORKSPACE/sister-praxis" sister-praxis

# TLS sintético: presente no filesystem, ignorado pelo Git.
printf 'test-ca\n'  > "$WORKSPACE/sister-infra/secrets/ecosystem-lab-ca.crt"
printf 'test-pem\n' > "$WORKSPACE/sister-infra/secrets/ecosystem-lab.pem"
printf 'test-key\n' > "$WORKSPACE/sister-infra/secrets/ecosystem-lab-ca.key"

source_status="$(git -C "$WORKSPACE/sister-infra" status --porcelain)"
[[ -z "$source_status" ]] || {
  printf '[FAIL] fixture sister-infra deveria estar clean, mas está:\n%s\n' \
    "$source_status" >&2
  exit 1
}

export SISTER_SOURCE_WORKSPACE="$WORKSPACE"

echo "=== doctor ==="
"$CLI" doctor

echo
echo "=== plan sem current ==="
plan_output="$("$CLI" plan)"
printf '%s\n' "$plan_output"
[[ "$plan_output" == *"NEW"* ]]

echo
echo "=== release 1 ==="
OUT1="$("$CLI" release-create)"
printf '%s\n' "$OUT1"
ID1="$(printf '%s\n' "$OUT1" | tail -n1)"

RELEASE1="$SISTER_WORKSTATION_INSTALL_ROOT/releases/$ID1"

[[ -d "$RELEASE1" ]]
[[ -f "$RELEASE1/components/sister-infra/secrets/.gitkeep" ]]
[[ -L "$RELEASE1/components/sister-infra/secrets/ecosystem-lab-ca.crt" ]]
[[ -L "$RELEASE1/components/sister-infra/secrets/ecosystem-lab.pem" ]]
[[ -L "$RELEASE1/components/sister-infra/secrets/ecosystem-lab-ca.key" ]]

infra_status="$(
  git -C "$RELEASE1/components/sister-infra" \
    status --porcelain --untracked-files=no
)"

[[ -z "$infra_status" ]] || {
  printf '[FAIL] sister-infra da release nasceu dirty:\n%s\n' \
    "$infra_status" >&2
  exit 1
}

jq -e '.schema == "sister.infra.workstation.release/1"' \
  "$RELEASE1/manifest.json" >/dev/null

echo
echo "=== install 1 ==="
"$CLI" install "$ID1"

[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/current")")" == "$ID1" ]]
[[ -f "$SISTER_WORKSTATION_SYSTEMD_ROOT/sister-workstation.service" ]]

echo
echo "=== release 2 ==="
printf 'change\n' >> "$WORKSPACE/SisTer/README.md"
git -C "$WORKSPACE/SisTer" add README.md
git -C "$WORKSPACE/SisTer" commit -q -m second

OUT2="$("$CLI" release-create)"
printf '%s\n' "$OUT2"
ID2="$(printf '%s\n' "$OUT2" | tail -n1)"

[[ "$ID1" != "$ID2" ]]

echo
echo "=== install 2 / previous ==="
"$CLI" install "$ID2"

[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/current")")" == "$ID2" ]]
[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/previous")")" == "$ID1" ]]

echo
echo "=== rollback com serviço parado ==="
"$CLI" rollback

[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/current")")" == "$ID1" ]]
[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/previous")")" == "$ID2" ]]

echo
echo "=== integridade detecta mutação rastreada ==="
printf 'tamper\n' >> "$RELEASE1/components/SisTer/README.md"

if "$CLI" status >/dev/null 2>&1; then
  echo "[FAIL] mutação rastreada não foi detectada" >&2
  exit 1
fi

echo "[PASS] workstation control plane tests"
