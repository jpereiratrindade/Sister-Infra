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

git_init_commit() {
  local path="$1"
  git -C "$path" init -q
  git -C "$path" config user.email test@example.invalid
  git -C "$path" config user.name "SisTer Test"
  git -C "$path" add .
  git -C "$path" commit -q -m init
}

make_infra() {
  local path="$WORKSPACE/sister-infra"

  mkdir -p \
    "$path/bin" \
    "$path/secrets" \
    "$path/templates/systemd"

  cp "$ROOT/bin/sister-infra" \
    "$path/bin/sister-infra"

  cp "$ROOT/bin/sister-workstation" \
    "$path/bin/sister-workstation"

  cp "$ROOT/templates/systemd/sister-workstation.service.in" \
    "$path/templates/systemd/sister-workstation.service.in"

  chmod +x "$path/bin/"*
  printf 'infra\n' > "$path/README.md"

  cat > "$path/.gitignore" <<'EOF_IGNORE_INFRA_TEST'
secrets/*
!secrets/.gitkeep
EOF_IGNORE_INFRA_TEST

  : > "$path/secrets/.gitkeep"
  git_init_commit "$path"

  printf 'test-ca\n' > "$path/secrets/ecosystem-lab-ca.crt"
  printf 'test-pem\n' > "$path/secrets/ecosystem-lab.pem"
  printf 'test-key\n' > "$path/secrets/ecosystem-lab-ca.key"
}

make_sister() {
  local path="$WORKSPACE/SisTer"

  mkdir -p "$path/apps/sisterd"

  cat > "$path/CMakeLists.txt" <<'EOF_CMAKE_SISTER'
cmake_minimum_required(VERSION 3.20)
project(test_sister LANGUAGES CXX)
enable_testing()
add_subdirectory(apps/sisterd)
EOF_CMAKE_SISTER

  cat > "$path/apps/sisterd/CMakeLists.txt" <<'EOF_CMAKE_SISTERD'
add_executable(sisterd main.cpp)
add_test(NAME sisterd_runs COMMAND sisterd)
EOF_CMAKE_SISTERD

  cat > "$path/apps/sisterd/main.cpp" <<'EOF_CPP_SISTER'
int main() { return 0; }
EOF_CPP_SISTER

  printf 'sister\n' > "$path/README.md"
  git_init_commit "$path"
}

make_nexo() {
  local path="$WORKSPACE/sister-nexo"
  mkdir -p "$path"

  cat > "$path/CMakeLists.txt" <<'EOF_CMAKE_NEXO'
cmake_minimum_required(VERSION 3.20)
project(test_nexo LANGUAGES CXX)
enable_testing()
add_executable(sister-nexo main.cpp)
add_test(NAME nexo_runs COMMAND sister-nexo)
EOF_CMAKE_NEXO

  cat > "$path/main.cpp" <<'EOF_CPP_NEXO'
int main() { return 0; }
EOF_CPP_NEXO

  cat > "$path/.env.example" <<'EOF_ENV_NEXO'
NEXO_HOST=127.0.0.1
NEXO_PORT=8015
NEXO_DB_PASSWORD=test-only
EOF_ENV_NEXO

  printf 'nexo\n' > "$path/README.md"
  git_init_commit "$path"
}

make_praxis() {
  local path="$WORKSPACE/sister-praxis"
  mkdir -p "$path"

  cat > "$path/CMakeLists.txt" <<'EOF_CMAKE_PRAXIS'
cmake_minimum_required(VERSION 3.20)
project(test_praxis LANGUAGES CXX)
enable_testing()
add_executable(sister-praxis-http main.cpp)
add_test(NAME praxis_runs COMMAND sister-praxis-http)
EOF_CMAKE_PRAXIS

  cat > "$path/main.cpp" <<'EOF_CPP_PRAXIS'
int main() { return 0; }
EOF_CPP_PRAXIS

  printf 'praxis\n' > "$path/README.md"
  git_init_commit "$path"
}

make_infra
make_sister
make_nexo
make_praxis

export SISTER_SOURCE_WORKSPACE="$WORKSPACE"

echo "=== doctor ==="
"$CLI" doctor

echo
echo "=== release 1 build-qualified ==="
OUT1="$("$CLI" release-create)"
printf '%s\n' "$OUT1"
ID1="$(printf '%s\n' "$OUT1" | tail -n1)"
RELEASE1="$SISTER_WORKSTATION_INSTALL_ROOT/releases/$ID1"

[[ -f "$RELEASE1/components/sister-infra/templates/systemd/sister-workstation.service.in" ]] || {
  echo "[FAIL] release não contém template systemd do sister-infra" >&2
  exit 1
}

grep -Fxq \
  'Environment=SISTER_INFRA_RUNTIME_MODE=installed' \
  "$RELEASE1/components/sister-infra/templates/systemd/sister-workstation.service.in" || {
    echo "[FAIL] template da release perdeu contrato installed" >&2
    exit 1
  }

jq -e '.schema == "sister.infra.workstation.release/2"' \
  "$RELEASE1/manifest.json" >/dev/null
jq -e '.qualification.build.status == "PASS"' \
  "$RELEASE1/manifest.json" >/dev/null

[[ -x "$RELEASE1/components/SisTer/build/apps/sisterd/sisterd" ]]
[[ -x "$RELEASE1/components/sister-nexo/build/sister-nexo" ]]
[[ -x "$RELEASE1/components/sister-praxis/build/sister-praxis-http" ]]

echo
echo "=== install não habilita ==="
"$CLI" install "$ID1"

[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/current")")" == "$ID1" ]]

UNIT="$SISTER_WORKSTATION_SYSTEMD_ROOT/sister-workstation.service"

[[ -f "$UNIT" ]] || {
  echo "[FAIL] unit workstation não foi materializada" >&2
  exit 1
}

grep -Fxq \
  'Environment=SISTER_INFRA_RUNTIME_MODE=installed' \
  "$UNIT" || {
    echo "[FAIL] unit instalada não declarou runtime installed" >&2
    exit 1
  }

grep -Fq \
  "ExecStart=$SISTER_WORKSTATION_INSTALL_ROOT/current/components/sister-infra/bin/sister-infra up --profile lan" \
  "$UNIT" || {
    echo "[FAIL] ExecStart da unit instalada não aponta para current" >&2
    exit 1
  }

echo "[PASS] unit instalada deriva da release e declara installed mode"

echo
echo "=== release 2 ==="
printf '//change\n' >> "$WORKSPACE/SisTer/apps/sisterd/main.cpp"
git -C "$WORKSPACE/SisTer" add apps/sisterd/main.cpp
git -C "$WORKSPACE/SisTer" commit -q -m second

OUT2="$("$CLI" release-create)"
printf '%s\n' "$OUT2"
ID2="$(printf '%s\n' "$OUT2" | tail -n1)"

"$CLI" install "$ID2"

[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/current")")" == "$ID2" ]]
[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/previous")")" == "$ID1" ]]

echo
echo "=== rollback parado ==="
"$CLI" rollback
[[ "$(basename "$(readlink -f "$SISTER_WORKSTATION_INSTALL_ROOT/current")")" == "$ID1" ]]

echo
echo "=== hash detecta adulteração ==="
printf 'tamper' >> "$RELEASE1/components/sister-praxis/build/sister-praxis-http"

if "$CLI" status >/dev/null 2>&1; then
  echo "[FAIL] adulteração de artefato não foi detectada" >&2
  exit 1
fi

echo "[PASS] workstation build-qualified release tests"
