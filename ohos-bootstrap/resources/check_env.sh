#!/usr/bin/env bash
# Check that this container can drive an OpenHarmony device, and say what to fix when it can't.
# Run it inside the agent's container. HDC_REMOTE overrides the auto-detected <gateway>:8710.
set -uo pipefail

pass=0; fail=0
ok()   { printf '  \033[32mok\033[0m    %s\n' "$1"; pass=$((pass + 1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$1"; shift; for l in "$@"; do printf '        %s\n' "$l"; done; fail=$((fail + 1)); }
warn() { printf '  \033[33mwarn\033[0m  %s\n' "$1"; shift; for l in "$@"; do printf '        %s\n' "$l"; done; }
section() { printf '\n\033[1m%s\033[0m\n' "$1"; }

gateway() {
    python3 - <<'PY' 2>/dev/null
import socket, struct
for line in open('/proc/net/route').readlines()[1:]:
    f = line.split()
    if f[1] == '00000000':
        print(socket.inet_ntoa(struct.pack('<L', int(f[2], 16))))
        break
PY
}

section "hdc client"
if ! command -v hdc >/dev/null; then
    bad "hdc is not on PATH" \
        "copy toolchains/hdc AND toolchains/libusb_shared.so from the SDK — hdc finds" \
        "libusb by rpath, so the two have to sit in the same directory."
else
    client_ver=$(hdc -v 2>/dev/null | tr -d '\r')
    ok "hdc on PATH: $client_ver"
    if grep -aq 'Client version:%s' "$(command -v hdc)" 2>/dev/null; then
        ok "built with HDC_VERSION_CHECK — versions must match exactly"
    else
        warn "built WITHOUT HDC_VERSION_CHECK" \
             "no version is exchanged, so a mismatched server connects and misbehaves later."
    fi
fi

section "reaching the hdc server"
gw=$(gateway)
remote=${HDC_REMOTE:-${gw:+$gw:8710}}
if [ -z "$remote" ]; then
    bad "cannot work out where the server is" "set HDC_REMOTE=<host>:<port> and re-run."
else
    [ -n "${HDC_REMOTE:-}" ] || printf '        (auto-detected from the default route: %s)\n' "$gw"
    host=${remote%:*}; port=${remote##*:}
    if timeout 5 bash -c "exec 3<>/dev/tcp/$host/$port" 2>/dev/null; then
        ok "TCP $remote is open"
    else
        bad "cannot connect to $remote" \
            "the tunnel binds on the cloud host's loopback by default, which this container" \
            "cannot see. On the host: 'ss -tlnp | grep $port' should show $host:$port." \
            "If it shows 127.0.0.1, set 'GatewayPorts clientspecified' in a" \
            "/etc/ssh/sshd_config.d/ drop-in, reload ssh, and restart the tunnel." \
            "A hang instead of a refusal usually means a host firewall dropping" \
            "container-to-gateway traffic."
    fi
fi

if [ -n "$remote" ] && command -v hdc >/dev/null; then
    section "server handshake"
    # checkserver skips the version comparison on purpose, so it answers across a mismatch.
    cs=$(timeout 20 hdc -s "$remote" checkserver 2>&1 | tr -d '\r')
    if [ -z "$cs" ]; then
        bad "checkserver said nothing" "no output at all is what a failed handshake looks like."
    else
        printf '        %s\n' "$cs"
        c=$(sed -n 's/.*Client version:\(.*\), server version:.*/\1/p' <<<"$cs")
        s=$(sed -n 's/.*server version:\(.*\)/\1/p' <<<"$cs")
        if [ -n "$c" ] && [ "$c" = "$s" ]; then
            ok "client and server agree"
        elif [ -z "$c" ]; then
            bad "checkserver did not report versions" \
                "that line is the server's answer, not a version pair — the handshake failed."
        else
            bad "version mismatch: client '$c', server '$s'" \
                "every other command will fail silently. Restart the server after upgrading" \
                "('hdc kill && hdc start' on the workstation) — hdc -v reports the binary," \
                "not the running process. If they are genuinely different builds, take both" \
                "from the same OpenHarmony SDK release."
        fi
    fi

    section "devices"
    targets=$(timeout 20 hdc -s "$remote" list targets 2>&1 | tr -d '\r' | grep -v '^[[:space:]]*$')
    if [ -z "$targets" ] || grep -qiE 'empty|failed|error' <<<"$targets"; then
        bad "no device: ${targets:-no output}" \
            "developer mode + USB debugging on, and the trust prompt accepted on the" \
            "device's own screen — that one cannot be answered remotely."
    else
        while read -r t; do ok "device $t"; done <<<"$targets"
    fi
fi

section "signing"
cfg=${SERVO_OHOS_SIGNING_CONFIG:-}
if [ -z "$cfg" ]; then
    bad "SERVO_OHOS_SIGNING_CONFIG is unset" \
        "hvigor falls back to build-profile.json5 and emits an UNSIGNED hap." \
        "See resources/signing.md; build the file with install_signing.py."
elif [ ! -f "$cfg" ]; then
    bad "SERVO_OHOS_SIGNING_CONFIG points at a missing file: $cfg"
else
    python3 - "$cfg" <<'PY'
import json, os, sys
path = sys.argv[1]
base = os.path.dirname(os.path.abspath(path))
try:
    configs = json.load(open(path))
except Exception as e:
    print(f"  \033[31mFAIL\033[0m  {path} is not valid JSON: {e}"); sys.exit(0)
for c in configs:
    name = c.get("name"); m = c.get("material", {})
    missing = [k for k in ("certpath", "profile", "storeFile")
               if not os.path.exists(os.path.join(base, m.get(k, "")))]
    if missing:
        print(f"  \033[31mFAIL\033[0m  {name!r}: unresolvable {missing}")
        print( "        paths are resolved relative to the config file itself.")
        continue
    pw = m.get("storePassword", "")
    if len(pw) < 32 or any(c not in "0123456789abcdefABCDEF" for c in pw):
        print(f"  \033[33mwarn\033[0m  {name!r}: password is plaintext, not the DevEco-encrypted form")
        print( "        hvigor's signHap rejects these; such a config can only be used by")
        print( "        signing the unsigned hap by hand with hap-sign-tool.jar.")
        continue
    # hvigor decrypts the passwords with key material next to the keystore.
    mat = os.path.join(os.path.dirname(os.path.join(base, m["storeFile"])), "material")
    if not os.path.isdir(mat):
        print(f"  \033[31mFAIL\033[0m  {name!r}: {mat} missing")
        print( "        the .p12 has to stay in the .ohos config dir, beside material/.")
    elif [d for d in ("fd", "ce", "ac") if not os.path.isdir(os.path.join(mat, d))]:
        print(f"  \033[31mFAIL\033[0m  {name!r}: material/ is incomplete (want fd, ce, ac)")
    else:
        print(f"  \033[32mok\033[0m    {name!r} ({c.get('type')}) resolves, material present")
PY
fi
[ -n "${ARKWEB_TEST_SIGNING_CONFIG:-}" ] \
    && ok "ARKWEB_TEST_SIGNING_CONFIG set: $ARKWEB_TEST_SIGNING_CONFIG" \
    || warn "ARKWEB_TEST_SIGNING_CONFIG unset" \
            "only needed to sign the ArkWeb test app; it has its own bundle name."

section "SDK"
[ -d "${OHOS_SDK_NATIVE:-}" ] && ok "OHOS_SDK_NATIVE=$OHOS_SDK_NATIVE" \
    || bad "OHOS_SDK_NATIVE is unset or missing" "needed to cross-compile for the device."
[ -d "${DEVECO_SDK_HOME:-}" ] && ok "DEVECO_SDK_HOME=$DEVECO_SDK_HOME" \
    || warn "DEVECO_SDK_HOME is unset or missing" "needed to package a HAP."
if [ -n "${OHOS_BASE_SDK_HOME:-}" ]; then
    if [ -w "${OHOS_BASE_SDK_HOME}" ]; then
        ok "OHOS_BASE_SDK_HOME=$OHOS_BASE_SDK_HOME is writable"
    else
        bad "OHOS_BASE_SDK_HOME=$OHOS_BASE_SDK_HOME is not writable" \
            "hvigor writes into the SDK tree. Point it at a writable symlink farm" \
            "(<root>/<api-level> -> the read-only SDK); see .devcontainer/post-start.sh."
    fi
else
    warn "OHOS_BASE_SDK_HOME is unset" "required for OpenHarmony (as opposed to HarmonyOS) builds."
fi

printf '\n%d ok, %d to fix\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
