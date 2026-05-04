---
name: hdc
description: OpenHarmony Device Connector (hdc) — port-forwarding (fport / rport), shell, file transfer, install. Trigger when the user mentions hdc, OpenHarmony device connector, hdc port forwarding, fport/rport, or troubleshooting hdc commands.
---

# hdc

OpenHarmony Device Connector — the OHOS analog of `adb`. Three-tier model:
**client** (CLI) ↔ **server** (background, owns USB connection) ↔ **daemon** (on the device).

## Critical gotcha — `hdc shell` exit codes do not propagate

The exit status of `hdc shell <cmd>` only signals whether the command was
*delivered* to the device. The device-side exit code is **lost**: a failure
on the device almost always returns 0 to the host, silently breaking
`set -e`, CI failure detection, and `hdc shell ... && next-step` chains.
Capture the exit code on the device side instead:

```shell
out=$(hdc shell "your-command; echo __rc=\$?")
rc=${out##*__rc=}; rc=${rc%%[!0-9]*}
[ "$rc" = "0" ] || { printf '%s\n' "$out" >&2; exit "$rc"; }
```

For tools that print structured success/failure markers (`bm install`,
`aa start`, hiperf …), grep their output instead of trusting `$?`.

## Port forwarding

- `hdc fport <local> <remote>` — forward a host TCP port *to* the device.
- `hdc rport <remote> <local>` — reverse-forward: device TCP port *to* host. Useful for letting the device reach a host-side fixture / proxy / WPR over its loopback.
- `hdc fport ls` — list all forwards (covers both fport and rport entries).

### Removal

Removal goes through `fport rm`, regardless of whether the entry was created by `fport` or `rport`. The argument order is the same as the matching setup command — the *local* (host) port first:

```sh
# Set up
hdc rport tcp:4480 tcp:4480

# Tear down — note `fport`, not `rport`
hdc fport rm tcp:4480 tcp:4480
```

`hdc rport rm tcp:N tcp:N` is rejected as `Incorrect forward command` and is a frequent source of "why won't this clean up" confusion.

## More

For multi-device targeting (`-t`), `file send`/`recv` argument order, `bm`-passthrough flag quoting on `hdc install`, the common diagnostic sequence, and env vars, see @hdc/resources/hdc.md.

For running hdc from a containerized agent against a device attached to another host (SSH-tunneled or direct TCP), see @hdc/resources/remote-hdc.md.

Full OHOS reference: <https://gitcode.com/openharmony/docs/blob/master/en/application-dev/dfx/hdc.md>.
