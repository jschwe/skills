# ohos-rust — push & run on a device

End-to-end recipe: build → push binary → run →
capture the device-side exit code.

Talking to the device uses `hdc` (`adb` analog). The hdc skill covers
the connector itself; the **only** thing from there worth repeating in
context is that `hdc shell <cmd>` swallows the device-side exit code,
so naive `set -e` scripts silently miss device failures.

## One-shot run

```sh
TARGET=aarch64-unknown-linux-ohos
BIN=target/$TARGET/release/myapp
LIBCXX="$OHOS_SDK_NATIVE/llvm/lib/aarch64-linux-ohos/libc++_shared.so"

# 1. Build
cargo build --release --target "$TARGET"

# 2. Push binary to a writable+executable location.
#    /data/local/tmp is the standard scratch dir.
hdc file send "$BIN" /data/local/tmp/myapp

# 3. Make the binary executable (file send does not preserve +x)
hdc shell "chmod 0755 /data/local/tmp/myapp"

# 4. Run it, capturing the *device-side* exit code (hdc shell loses $?)
out=$(hdc shell "cd /data/local/tmp && ./myapp; echo __rc=\$?")
rc=${out##*__rc=}; rc=${rc%%[!0-9]*}
printf '%s\n' "${out%__rc=*}"
[ "$rc" = "0" ] || { echo "device exit $rc" >&2; exit "$rc"; }
```

## /data/local/tmp permissions

`/data/local/tmp` is writable on most OHOS dev devices but on
hardened builds may be locked down. If `hdc file send` fails with
permission errors:

- Confirm the device is in developer mode (`hdc list targets` shows it).
- If the prompt is not a root prompt (`#`) abort and inform the user.

## Multiple devices

```sh
hdc list targets
hdc -t <serial> file send …
hdc -t <serial> shell "…"
```

`-t` must come **before** the subcommand. See the hdc skill for more.

## Non-interactive vs. interactive shell

`hdc shell <cmd>` runs `<cmd>` and exits. For an interactive prompt,
`hdc shell` (no args). When the binary expects a TTY (e.g. uses
`crossterm`, prompts for input), `hdc shell` may not allocate one — run
inside `script -q -c '…' /dev/null` device-side, or test interactively
first.
