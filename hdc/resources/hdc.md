# hdc — gotchas and reference

This file collects the hdc footguns that aren't covered in the main
`SKILL.md`. Full upstream reference:
<https://gitcode.com/openharmony/docs/blob/master/en/application-dev/dfx/hdc.md>
(and the device-dev variant at
<https://gitcode.com/openharmony/docs/blob/master/en/device-dev/subsystems/subsys-toolchain-hdc-guide.md>).

## Error message strings aren't a stable contract

The OHOS doc explicitly warns:

> The error information is for reference only and may be optimized. Do not
> use the error information for logic judgment of automated scripts or
> programs. In practice, you are advised to use standard error codes
> provided by the system.

For programmatic decisions, prefer the documented error codes (E000001 –
E001xxx in the reference). Note: those codes appear in stdout/stderr text,
not as exit codes — same `hdc shell` exit-code caveat as in `SKILL.md`.

## Multiple devices: `-t <connect-key>` is mandatory

With more than one device attached, every command must specify the target,
otherwise it fails with `[Fail]ExecuteCommand need connect-key?`:

```shell
hdc list targets -v               # find connect-keys + state (USB/TCP, Connected/Offline/Unauthorized)
hdc -t <connect-key> shell ls
```

With a single device, `-t` is optional.

## File transfer: source first, destination second

Both directions use **source-then-destination**, even though the OHOS doc
labels the args `SOURCE`/`DEST` for `send` and `DEST`/`SOURCE` for `recv`
(ignore the labels — they're confusing):

```shell
hdc file send  ./local-file        /data/local/tmp/   # local  -> device
hdc file recv  /data/local/tmp/x   ./                 # device -> local
```

`-b <bundle>` accesses an app sandbox; the app must be installed with a
**debug** signature.

## `bm` passthrough flags need to be quoted *with* their value

`hdc install` and `hdc uninstall` forward flags to the device-side `bm`
tool. Flags that take a value must be quoted as a single string, otherwise
the hdc-side parser eats the flag and `bm` never sees it:

```shell
hdc "-w 180" install foo.hap        # correct
hdc "-u 100" install foo.hap        # correct
hdc -w 180 install foo.hap          # WRONG — parser breaks
```

## Common diagnostic sequence

When something looks broken, work through these in order:

```shell
hdc checkserver                     # client and server versions match?
hdc list targets -v                 # device visible? Connected/Offline/Unauthorized?
hdc kill -r                         # nuke and restart server (clears stale state)
hdc -l 5 start                      # restart with verbose logs in $TMPDIR/hdc.log
```

Frequent root causes:

| Symptom | Likely cause |
|---|---|
| `[Empty]` from `list targets` but device is plugged in | Stale server, port conflict (DevEco Studio bundles its own hdc), or client/server version mismatch |
| `Unauthorized` next to the device | First-time trust prompt was missed or declined — `hdc kill -r` re-arms it |
| `connect failed status:-4078` | Something else owns port 8710; check `OHOS_HDC_SERVER_PORT` and `netstat -an \| grep 8710` |
| Commands hang or return partial output | Client/server version skew |
| Disconnect immediately after `hdc shell reboot` or `hdc tmode port` | Expected — the daemon restarts; reconnect |
| `The communication channel is being established` (E000004) | Wait ~10s after plug-in before issuing commands |

## Useful environment variables

| Var | Effect |
|---|---|
| `OHOS_HDC_SERVER_PORT` | Server listen *port* (default 8710). **Port only — no host.** To target a remote server, use `-s host:port`, not this var. |
| `OHOS_HDC_LOG_LEVEL` | 0–6 (`OFF`, `FATAL`, `WARN`, `INFO`, `DEBUG`, `ALL`, `LIBUSB`). `5` is the usual debug setting. |
| `OHOS_HDC_HEARTBEAT` | `1` disables heartbeat packets between server and daemon. |
| `OHOS_HDC_CMD_RECORD` | `1` enables command-history logging in `$TMPDIR/hdc_cmd/` (API 20+). |

## See also

- Remote / containerized usage (server on another host): `remote-hdc.md`.
- Full command reference: <https://gitcode.com/openharmony/docs/blob/master/en/application-dev/dfx/hdc.md>.
