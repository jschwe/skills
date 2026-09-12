#!/usr/bin/env bash
# Install DevEco-generated signing material into this container, interactively.
#
# Takes the two things DevEco produces -- a zip of <USER HOME>/.ohos and the project's
# build-profile.json5 -- and leaves a signing config that hvigor can use. Run it whenever
# the material changes (a new device needs a new debug profile).
#
#   bash setup_signing.sh [ohos-signing.zip] [build-profile.json5]
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
workspace="${WORKSPACE_DIR:-/workspaces/servo-workspace}"
dest="$workspace/ohos-config"
out="${SERVO_OHOS_SIGNING_CONFIG:-$dest/signing-configs.json}"

die() { printf '\033[31merror\033[0m %s\n' "$*" >&2; exit 1; }
say() { printf '\033[1m%s\033[0m\n' "$*"; }

ask() {  # ask <prompt> <varname> -- only prompts when the value is still empty
    local prompt="$1" var="$2" reply
    [ -n "${!var}" ] && return 0
    [ -t 0 ] || die "$prompt (no terminal to ask on; pass it as an argument)"
    read -r -e -p "$prompt: " reply
    printf -v "$var" '%s' "${reply/#\~/$HOME}"
}

zip_path="${1:-}"; profile="${2:-}"

say "1/4  locating the uploaded files"
if [ -z "$zip_path" ]; then
    # Most likely landing spots for a scp'd upload.
    mapfile -t found < <(find "$HOME" "$workspace" -maxdepth 2 -name '*.zip' \
        -newermt '-14 days' 2>/dev/null | head -10)
    if [ "${#found[@]}" -eq 1 ]; then
        zip_path="${found[0]}"
        echo "  found $zip_path"
    elif [ "${#found[@]}" -gt 1 ]; then
        printf '  candidates:\n'; printf '    %s\n' "${found[@]}"
    fi
fi
ask "path to the .ohos zip" zip_path
[ -f "$zip_path" ] || die "no such file: $zip_path"
ask "path to build-profile.json5" profile
[ -f "$profile" ] || die "no such file: $profile"

say "2/4  unpacking"
command -v unzip >/dev/null || die "unzip is not installed (apt-get install -y unzip)"
staging="$(mktemp -d)"
trap 'rm -rf "$staging"' EXIT
unzip -q "$zip_path" -d "$staging" || die "could not unpack $zip_path"

# The archive may be rooted at .ohos/ or at config/ depending on how it was made.
src="$(dirname "$(find "$staging" -type d -name material -print -quit)")"
[ -n "$src" ] && [ -d "$src" ] || die \
    "no material/ directory in the archive -- hvigor decrypts the passwords with it, so
       the zip has to include <USER HOME>/.ohos in full, untidied."
echo "  material found under ${src#$staging/}"

if [ -e "$dest/config" ]; then
    backup="$dest/config.bak.$(date +%Y%m%d-%H%M%S)"
    mv "$dest/config" "$backup"
    echo "  previous config/ kept at ${backup#$workspace/}"
fi
mkdir -p "$dest"
cp -r "$src" "$dest/config"

say "3/4  building the signing config"
uv run "$here/install_signing.py" --material-dir "$dest" --build-profile "$profile" --out "$out" \
    || die "install_signing.py failed -- nothing was written to $out"

say "4/4  verifying"
bash "$here/check_env.sh" 2>&1 | sed -n '/^.*signing/,/^$/p'
cat <<EOF

Signing config: $out
Point hvigor at it with:

    export SERVO_OHOS_SIGNING_CONFIG=$out

(already set for you if it is in the devcontainer's containerEnv).
For the ArkWeb test app, repeat with its own material and export
ARKWEB_TEST_SIGNING_CONFIG -- it has a different bundle name.
EOF
