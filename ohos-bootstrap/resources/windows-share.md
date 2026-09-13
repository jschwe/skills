# Sharing a Windows folder with the agent, and mounting it in a devcontainer

Useful for moving bulk files between the workstation and the agent: the signing
bundle, DevEco build output, `hstack` inputs, captures the user took by hand.

**It is not needed for `hdc file send` / `recv`.** Those do their file I/O in the
client process, so an agent talking to a remote hdc server reads and writes its
own local filesystem — see @ohos-bootstrap/resources/remote-tunnel.md for the
measurement. Set up a share because moving files by hand is annoying, not
because hdc requires it.

## On Windows (user, PowerShell as Administrator)

```powershell
New-Item -ItemType Directory -Path C:\devshare -Force
New-SmbShare -Name devshare -Path C:\devshare -FullAccess $env:USERNAME
Get-SmbShare devshare
```

The account used to authenticate needs a password — a passwordless local account
cannot log in over SMB. On a machine signed in with a Microsoft account, the SMB
username is the account email, and it is usually less painful to create a
dedicated local user for the share:

```powershell
New-LocalUser -Name devshare -Password (Read-Host -AsSecureString) -PasswordNeverExpires
Grant-SmbShareAccess -Name devshare -AccountName devshare -AccessRight Full -Force
```

No firewall change is needed if the connection arrives over the SSH tunnel
described below — it reaches the SMB service on loopback.

## Getting to it from the Linux side

If the workstation is behind NAT and dials out (the usual case), carry 445 in
the same reverse tunnel that carries hdc:

```powershell
ssh -N -R 8710:127.0.0.1:8710 -R 4445:127.0.0.1:445 you@cloud
```

Then on the Linux host — **the host, not the container**:

```shell
sudo apt install cifs-utils
printf 'username=devshare\npassword=...\n' | sudo tee /etc/samba/devshare.cred >/dev/null
sudo chmod 600 /etc/samba/devshare.cred
sudo mkdir -p /mnt/devshare
sudo mount -t cifs //127.0.0.1/devshare /mnt/devshare \
    -o port=4445,credentials=/etc/samba/devshare.cred,uid=1000,gid=1000,vers=3.1.1,nobrl
```

- `uid=`/`gid=` — CIFS carries no usable POSIX ownership here, so ownership is
  assigned at mount time. Use the host uid that maps to the container's user.
- `nobrl` — avoids byte-range-lock failures from tools that lock while reading.
- `vers=3.1.1` — pin it; negotiation failures are otherwise reported as
  permission errors.

For persistence, an fstab line with `x-systemd.automount,_netdev,noauto` keeps
boot from hanging when the tunnel is down.

## Mounting it in the devcontainer

Do **not** try to mount CIFS inside the container. This one has neither the
capability nor the helper:

```
$ capsh --print | grep -o 'cap_sys_admin'      # (nothing — it is in the dropped set)
$ ls /sbin/mount.cifs                          # No such file or directory
```

Mount on the host as above, then bind-mount the mountpoint. In
`devcontainer.json`:

```jsonc
"mounts": [
    "source=/mnt/devshare,target=/mnt/devshare,type=bind"
]
```

A bind mount of a filesystem that may be absent at container start will fail the
start, so mount the share first (or use the systemd automount unit above, which
makes the path always exist).

### Alternatives, and why not

- **Docker CIFS volume** (`type=volume,volume-driver=local,volume-opt=type=cifs,…`)
  lets the daemon do the mount. It works under rootful Docker; under rootless
  Docker or Podman the daemon has no more privilege than the user, and the
  `mount(2)` fails.
- **`--cap-add SYS_ADMIN` plus `cifs-utils` in the image** works and is exactly
  the privilege escalation the container exists to avoid.

## Gotchas

- The share is **case-insensitive**. Never put a build tree on it — mozjs in
  particular breaks on case-insensitive filesystems. Staging area only.
- Executable bits do not survive. `chmod +x` after copying anything runnable.
- The mount drops when the workstation sleeps and comes back stale; `mount -o
  remount` does not fix that, an unmount/remount does.
- Windows path vs Linux path for the same bytes: `Z:\devshare\x` and
  `/mnt/devshare/x`. Only relevant when handing a path to a tool running on the
  workstation.
