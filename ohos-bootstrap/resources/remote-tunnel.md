# Remote hdc: bootstrapping the workstation side

Setup: a **Windows workstation** owns the USB device and runs the hdc server; the agent runs on
a **Linux server**, often in a container, and runs only the hdc client. The model, how bare `hdc`
reaches the server (per-user port, container options, relay), the rules (no `hdc kill`, exit
status 0 on failure) and what crosses the boundary are in @hdc/resources/remote-hdc.md. This
file is what the user does on the workstation, and the source-level evidence behind it.

## On the workstation

```powershell
> hdc list targets              # the server hdc or DevEco started listens on 127.0.0.1:8710
> ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 `
      -R 127.0.0.1:<port>:127.0.0.1:8710 you@build-server
```

- `<port>` is the user's own port on the build server (shared servers: never 8710), and the agent
  exports `OHOS_HDC_SERVER_PORT=<port>`. Where the forward has to end for a container is in
  the hdc reference.
- Windows ships the OpenSSH client since Windows 10 1809.
- Accept the device's "trust this computer" prompt on first connection.
- A dropped tunnel looks like a dead server (`Connect server failed`). `ServerAliveInterval`
  ends a dead connection instead of leaving it hanging; `autossh` or a retry loop reconnects.

Forwards for device ports, folded into the same session (each is a restart of the tunnel, so
forward a few up front; they are inert until something calls `fport`/`rport`):

| Need | Workstation-side ssh flag |
|---|---|
| agent → device port (WebDriver, devtools) | `-R 127.0.0.1:7000:127.0.0.1:7000` after `hdc fport tcp:7000 tcp:7000` |
| device → a service on the build server (fixture HTTP server, WPR) | `-L 127.0.0.1:8000:127.0.0.1:8000` before `hdc rport tcp:8000 tcp:8000` |

On a shared build server, the `-R` ports need to be per-user too. WPT is not covered by this:
its server listens on ports chosen at random at runtime, which cannot be forwarded up front.

## Version matching is exact

```cpp
// src/host/client.cpp:907
string clientVer = Base::GetVersion() + HDC_MSG_HASH;
string serverVer(hShake->version, strnlen(hShake->version, BUF_SIZE_TINY));
if (clientVer != serverVer) { ... return ERR_CHECK_VERSION; }
```

A string compare — no compatibility range, so `3.2.0b` and `3.2.0c` do not talk. The failure is
**silent**: `ERR_CHECK_VERSION` is returned from the handshake callback and only written to
hdc's log file, so the command prints nothing at all and looks like an absent device.

- The check lives behind `HDC_VERSION_CHECK`, which `hdc.gni` defaults to **off**; SDK-shipped
  binaries are built with it on. To tell which you have: `strings -a <hdc> | grep 'Client
  version:%s'` — present means the check is compiled in.
- `checkserver` sets `isCheckVersionCmd` and deliberately skips the comparison, so it prints
  both numbers even across a mismatch. That is what makes it the right first command.
- The workstation is Windows and the container is Linux, so the binaries cannot be copied
  across. Take both from the same OpenHarmony SDK release — the public SDK on the gitee mirror
  ships `windows` and `linux` builds of one version and is not account-gated.
- After upgrading hdc, the *user* restarts the workstation's server. `hdc -v` reports the
  binary; a server started before the upgrade keeps the old version.

## Why file transfer crosses

Since 2022 the client appends `remote -cwd "<its cwd>"` to every transfer command; the server
sees the `remote` token, bounces `CMD_FILE_INIT` back to the client, and the client runs the
file task itself:

```
developtools/hdc/src/host/main.cpp:121            AppendCwdWhenTransfer -> "remote -cwd ..."
developtools/hdc/src/host/server_for_client.cpp:856  fromClient -> SendChannelWithCmd(...); return false
developtools/hdc/src/host/client.cpp:964          fileTask = std::make_unique<HdcFile>(hTaskInfo)
```

`hdc install` takes the same client-side path (`RemoteType::REMOTE_APP`); both are verified in
the hdc reference. So a remote agent needs no file share for HAPs, fixtures or captures — only
for files a human puts somewhere by hand.

## `OHOS_HDC_SERVER_PORT` is a port, not an address

`InitServerAddr` parses only a port and pins the address (`DEFAULT_SERVER_ADDR_IP =
"::ffff:127.0.0.1"`, `src/common/define.h:38`). That is why the forward has to end on the
loopback of whatever runs the client.
