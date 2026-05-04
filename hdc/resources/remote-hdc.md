# Reaching an OpenHarmony device from a containerized agent via remote hdc

This describes how to run `hdc` commands from inside a container against an OpenHarmony
device that is physically attached (USB) to a *different* machine.

## Architecture recap

`hdc` is a three-tier tool:

```
client (CLI)  <-- TCP -->  server (background)  <-- USB / TCP -->  daemon (on device)
```

- The **server** must run on the machine that has the device attached. It owns the
  USB connection and exposes a TCP socket (default `127.0.0.1:8710`) for clients.
- The **client** is just a CLI that talks to the server. It does not need USB
  access. With `hdc -s IP:port <cmd>` it can target any reachable server.

This makes the container scenario straightforward: run the server on the host that
owns the device, and reach it from the agent's container over TCP.

```
+--------------------+        +---------------------------------+
|  Container (agent) |        |  Host A (device attached)       |
|  hdc client        |  ---> |  hdc server  ---USB--> [device]  |
|  hdc -s host:8710  |        |  hdc -s 0.0.0.0:8710 -m         |
+--------------------+        +---------------------------------+
```

## Version requirement

The client and server must run the **same hdc version**. After connecting, verify
with:

```shell
hdc -s <host>:8710 checkserver
```

If versions disagree, copy the server's `hdc` binary into the container (or vice
versa) so both sides match.

## Option 1 — SSH tunnel (recommended)

Keep the hdc server bound to loopback on Host A and forward port 8710 into the
container over SSH. Nothing on Host A is exposed to the network.

### On Host A (device-attached machine)

```shell
# Make sure no stale server is running, then start a fresh one on loopback.
hdc kill
hdc start                  # background, listens on 127.0.0.1:8710 by default
hdc list targets           # confirm the device is visible locally first
```

`hdc start` daemonizes the server. Alternatively `hdc -m` runs it in the foreground
(useful under systemd / `tmux`).

### In the container

Open an SSH tunnel from the container to Host A. The tunnel maps
`container:127.0.0.1:8710` → `hostA:127.0.0.1:8710`:

```shell
ssh -N -f -L 8710:127.0.0.1:8710 user@host-a
```

(`-N` no remote command, `-f` background. Use a key-based login; do not embed
passwords.)

Then every client call inside the container uses the local forwarded port:

```shell
hdc -s 127.0.0.1:8710 list targets
hdc -s 127.0.0.1:8710 shell hiperf stat -a -d 2
hdc -s 127.0.0.1:8710 file recv /data/local/tmp/perf.data ./perf.data
```

To avoid repeating `-s` everywhere, wrap it:

```shell
alias hdc='hdc -s 127.0.0.1:8710'
```

(Note: `OHOS_HDC_SERVER_PORT` only sets the *port*, not the host, so an env var
alone cannot point the client at a remote server — `-s` or an alias is required.)

## Option 2 — Direct TCP bind on Host A

Simpler but **unauthenticated**: anyone who can reach the port can drive the
device. Only use on a trusted network or behind a firewall rule.

### On Host A

```shell
hdc kill
hdc -s 0.0.0.0:8710 -m     # bind on all interfaces, foreground
# or a specific LAN IP, e.g. -s 192.168.1.50:8710
```

Run it under `nohup`/systemd/`tmux` if you want it to persist:

```shell
nohup hdc -s 0.0.0.0:8710 -m >/var/log/hdc.log 2>&1 &
```

The OpenHarmony docs explicitly warn:

> If the `-s` parameter is used to specify the server address, and the listening
> address is not the local loopback address, pay attention to the access security.

### In the container

```shell
hdc -s host-a.lan:8710 list targets
```

If the agent runs on the same physical host as the hdc server (just inside a
container), use `host.docker.internal` (Docker Desktop) or the host's bridge IP,
or share the host network with `--network=host`.

## Port forwarding *into the device*

Independent of the client/server transport above, `hdc fport` / `hdc rport` set
up TCP forwards between the host running the **server** and the device. They
work transparently from a remote client — the forward terminates on the
server-side machine, not in the container:

```shell
# Forward Host-A:tcp:9229 -> device:tcp:9229 (e.g. for a debugger)
hdc -s 127.0.0.1:8710 fport tcp:9229 tcp:9229
hdc -s 127.0.0.1:8710 fport ls
```

If the agent in the container needs to talk to that forwarded port, add a second
SSH `-L` (or extra `docker -p`) for `9229` on top of the 8710 tunnel.

## Connecting the device over TCP instead of USB

Orthogonal to the remote-server setup, the device itself can be exposed over
TCP from Host A:

```shell
hdc tmode port 5555                # device restarts daemon on TCP:5555
hdc tconn <device-ip>:5555         # server now talks to device over the network
```

This can replace the USB attachment entirely if the device is reachable from
Host A over the network.

## Troubleshooting checklist

| Symptom | Likely cause |
|---|---|
| `Connect server failed.` | Server not running on Host A, or port not reachable from container. Test with `nc -vz host-a 8710`. |
| `[Empty]` from `list targets` on the remote client but works locally on Host A | A second hdc server started on the container side stole the port. Run `hdc kill` in the container, then re-issue with `-s`. |
| Commands hang / partial output | Client/server version mismatch. Run `hdc -s <host>:8710 checkserver` and align binaries. |
| Device shows `Unauthorized` | First-time authorization prompt appears on the device's screen — needs to be accepted physically once on Host A. |
| `hdc kill` in the container kills nothing useful | Correct — `kill` only affects the *local* hdc server. To restart the remote one you have to do it on Host A. |

## Quick recipe for the agent

Inside the container, before any hdc call:

```shell
export HDC_REMOTE=127.0.0.1:8710        # or host-a:8710 for Option 2
hdc -s "$HDC_REMOTE" checkserver        # fail fast if versions disagree
hdc -s "$HDC_REMOTE" list targets       # confirm a device is connected
```

Then use `hdc -s "$HDC_REMOTE" ...` for every subsequent command.
