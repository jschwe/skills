# Driving a device attached to another machine

The device hangs off the USB port of a **device host** (typically a Windows or macOS workstation
with DevEco Studio). The agent, the build and the tests run on a **build machine** (a Linux server
or VM, often inside a container). This file is the reference for that setup; facts marked
*verified* were measured with hdc 3.2.0f.

## Model

```
build machine (or a container on it)                     device host

  hdc client ──► 127.0.0.1:<port> ◄═══ ssh -R ═══════════ hdc server ──── USB ────► device
                 (forwarded port)      opened by the                127.0.0.1:8710
                                       device host
```

- Only the **server** needs the device. The client is a CLI that talks TCP to a server.
- The device host opens the SSH connection (`ssh -R`): it is usually behind NAT, it is the
  machine the user sits at, and it needs no SSH server. The hdc server keeps listening on its
  own loopback, so nothing is exposed to the network.

## Make bare `hdc` reach the remote server

The goal is that plain `hdc …` works, with no `-s` and no alias: skills, `./mach`, scripts, the
WPT harness and `ohos-test-runner` all run `hdc` as a process, and aliases never reach those.
`./mach install --ohos` even runs the SDK's hdc by absolute path, so a `PATH` wrapper misses it.

Bare `hdc` connects to `127.0.0.1:$OHOS_HDC_SERVER_PORT` (default 8710). So the forward has to
end on the loopback *of the environment the tools run in*:

| where the tools run | how the forward reaches its loopback |
|---|---|
| on the build machine itself | `ssh -R 127.0.0.1:<port>:127.0.0.1:8710 user@build-machine` |
| in a container, own network namespace | sshd inside the container, and the device host SSHes into the container (published port or jump host). Private to the container. |
| in a container with `--network=host` | same as the build machine itself. Shares the host's loopback. |
| in a container, forward on the bridge | a relay in the container, see below. Needs `GatewayPorts clientspecified` on the host's sshd. |

Then, in the environment of the tools: `export OHOS_HDC_SERVER_PORT=<port>` (unless it is 8710).

**Shared build machines: use a per-user port.** Loopback ports are open to every user of the
machine, and hdc has no authentication: whoever forwards 8710 makes every other user's bare
`hdc` drive *their* device. A dedicated port prevents accidents, not misuse; only a network
namespace of your own (sshd in your container) isolates the forward. Host networking and the
bridge relay are both reachable by everyone on the machine.

`ExitOnForwardFailure=yes` makes ssh stop with `remote port forwarding failed for listen port
<port>` when the port is taken (*verified*), instead of carrying on without the forward.

### The bridge relay

When the forward listens on the host's bridge address (e.g. `ssh -R 172.17.0.1:<port>:…`), a
relay in the container makes bare `hdc` reach it (*verified* with a relay to a local server:
`checkserver`, `list targets`, `shell`, `file send` all work, no extra server starts):

```sh
socat TCP-LISTEN:<port>,bind=127.0.0.1,fork,reuseaddr TCP:172.17.0.1:<port>
```

Find the bridge address from inside the container with `ip route show default` (without
`iproute2`: the `Gateway` column of `/proc/net/route`, little-endian hex); `172.17.0.1` is only
Docker's default network, and rootless Docker/Podman may emulate it. sshd only lets a
forward listen on a non-loopback address with `GatewayPorts clientspecified`, and without it
**silently** binds loopback instead — even with `ExitOnForwardFailure` (*verified*). Check with
`ss -tln | grep <port>` on the host.

If the relay dies, the next bare `hdc` starts an empty **local** server on the port, which
answers `[Empty]` and keeps the relay from binding again. `ss -ltnp | grep <port>` tells whether
the listener is the relay or an `hdc -m` process.

## Rules on a remote device

1. **Check the connection first:** `hdc checkserver` (prints both versions, even across a
   mismatch), then `hdc list targets`.
2. **Never `hdc kill` or `hdc start`.** Through the forward, `hdc kill` stops the device host's
   server, and only the user can start it again.
3. **Versions must match exactly.** A mismatched client prints nothing at all — no error, no
   devices. Take both binaries from the same OpenHarmony SDK release.
4. **hdc reports failure on its output, with exit status 0** (*verified*):
   - `Connect server failed` on stderr: nothing listens at the address (tunnel down). An
     unroutable address takes about 12 s.
   - no output at all: something accepted the connection but is not an hdc server (a tunnel
     without a server behind it), or the versions differ.
   - `-s content IP incorrect.` / `-s content port incorrect.` on stdout: `-s` only takes a
     numeric IP and a non-zero port; `localhost` and `[::1]` are rejected.
   - `[Fail]…` on stdout for failed transfers and unknown connect-keys.
5. **`-s` is only for tools configured with a server** (`OHOS_TEST_RUNNER_HDC_SERVER`,
   servoperf's `--hdc-server`). With several `-s`, the last one wins (*verified*).

## What crosses the boundary

- **File transfer and installs run on the client.** `hdc file send`/`recv` and `hdc install`
  read and write the build machine's files (*verified*: a file visible only in the client's
  mount namespace was sent, and installed — rejected by `bm` as an invalid package, which proves
  the transfer; without the file, the client itself failed with `Error opening file`). No file
  share is needed. `./mach install --ohos` works unchanged.
- **Shell, logs, uitest** just stream over the channel. `uitest screenCap` + `file recv` works.
- **Port forwards end on the device host**, since the server executes them:
  - `hdc fport tcp:P tcp:Q` listens on the **device host's** port P. To reach it from the build
    machine, the device host adds `-R 127.0.0.1:P:127.0.0.1:P` to its ssh command.
    WebDriver and devtools need this.
  - `hdc rport tcp:P tcp:Q` makes the device's port P connect to the **device host's** port Q.
    To reach a server on the build machine, the device host adds
    `-L 127.0.0.1:Q:127.0.0.1:Q`. Local HTTP servers, WPR and WPT need this.
  - Each forward is a flag on the device host's ssh command, so a new port means asking the
    user to restart the tunnel. Forward a few ports up front.
  - `hdc fport rm tcp:P tcp:Q` removes both kinds; `rport rm` is rejected.
- **The trust prompt** for a new host appears on the device's screen, and only a person there
  can accept it.

## `tconn` does not replace the tunnel

`-s`/the forward picks the **server**; `tconn ip:port` tells a server which **device** to attach
to over TCP. Running the server on the build machine and `tconn`-ing the device removes the
second hop for forwards, but needs an IP route to the device, and `tmode port` is persistent:
undoing it needs a working connection, so a device on another network may need recovering over
USB. The emulator rejects `tmode` (`[E001300]Not support tmode for Emulator`). And a device on
TCP is unauthenticated — keep it tunnelled.
