# hdc — device-side commands reachable via `hdc shell`

OHOS ships a set of CLI tools in `/system/bin` that you invoke through
`hdc shell` (interactive or one-shot). This file is a lookup table —
not a tutorial — for picking the right tool. Each entry links to the
upstream doc for syntax detail. Sourced from
`~/Dev/ohos/ohos-docs/en/application-dev/{tools,dfx,application-test}/`.

Verify presence on a connected device with:

```sh
hdc shell "for c in aa bm cem atm anm acm edm hilog hidumper hitrace hiperf \
  hiprofiler_cmd param power-shell devicedebug mediatool toybox uitest \
  begetctl service_control snapshot_display; do command -v \$c >/dev/null \
  && echo present:\$c || echo missing:\$c; done"
```

Many tools have **eng-version-only** or **root-only** subcommands. The
docs use `<!--Del-->` markers for "user-version users won't see this";
the table below flags those.

## Apps & application lifecycle

| Tool | Purpose | Notable subcommands | Notes |
|---|---|---|---|
| **aa** | Ability Assistant — start, stop, query application components, run tests | `start`, `stop-service`, `force-stop`, `dump`, `test`, `attach`, `process` | Most-used tool for launching ArkTS apps from CLI. Quote args when going through `hdc shell`. |
| **bm** | Bundle Manager — install / uninstall / query / patch HAPs | `install`, `uninstall`, `dump`, `clean`, `quickfix`, `compile`, `get` (UDID), `dump-dependencies` | `enable`/`disable` are root-version only. `clean` works in user version when "Developer options" is on. |
| **devicedebug** | Send signals to debuggable AMS-managed processes | `kill -<sig> <pid>` | Only debuggable apps. Use when `kill(1)` is blocked by SELinux. |
| **uitest** | UI automation — taps, swipes, screenshots, layout dumps, screen recording | `dumpLayout`, `screenCap`, `start-daemon`, `uiInput`, `uiRecord` | Drives CI UI tests. |

## Logs, traces, profiling

| Tool | Purpose | Notes |
|---|---|---|
| **hilog** | OHOS log viewer (analog of `logcat`) — print, filter, configure log buffers | `hilog`, `hilog -x` (one-shot), `hilog -L D -T <tag>` |
| **hidumper** | Export system info — CPU, memory, storage, services, IPC | `hidumper -ls` (list), `hidumper -s <id>`, `hidumper --mem <pid>`, `hidumper --cpuusage` |
| **hitrace** | Collect kernel/userspace traces (text + binary) | `hitrace -l` (categories), `hitrace -t 10 ohos` |
| **hiperf** | Performance sampling, callchains, flamegraphs (covered in detail by the **ohos-performance-testing** skill) | `hiperf record`, `hiperf report`, `hiperf stat` |
| **hiprofiler_cmd** | C/S profiling daemon CLI — feeds DevEco Studio / SmartPerf with native-hook, ftrace, GPU, memory data | Pairs with `hiprofilerd` running on device |

## System parameters and config

| Tool | Purpose | Notes |
|---|---|---|
| **param** | Read/write system parameters | `param get <name>`, `param set <name> <val>`, `param ls`, `param wait`, `param save`. Many params (e.g. `const.ohos.apiversion`) are read-only and used to identify the build. |
| **begetctl** | init / startup-system control | start/stop services, dump init config. Often the only way to restart a system service. |
| **service_control** | Lower-level service start/stop (where present) | Some images expose this instead of / alongside `begetctl`. |

## Security and permissions

| Tool | Purpose | Notes |
|---|---|---|
| **atm** | Access Token Manager — query and (root-only) modify permissions for app processes | `atm dump`, `atm perm` (root), `atm toggle` (root). Token IDs from `bm dump`. |
| **acm** | Account Manager — local account create/delete/switch/dump | All write operations require root. |
| **edm** | Enterprise Device Manager — enable/disable EnterpriseAdminExtensionAbilities | Mostly relevant when developing MDM apps. |

## Notifications, events, media, power

| Tool | Purpose | Notes |
|---|---|---|
| **anm** | Advanced Notification Manager — dump notification state, set caches | **eng-version-only** — user version reports `anm: inaccessible or not found`. |
| **cem** | Common Event Manager — publish events, dump subscribers | Useful for poking event-driven services. |
| **mediatool** | Push/pull files into the gallery (media library) | `mediatool send <local>`, `mediatool recv`, `mediatool delete`. Bypasses the public picker API. |
| **power-shell** | Toggle screen/power state | `power-shell setmode`, `wakeup`, `suspend`, `timeout`. |

## Coreutils / shell environment

| Tool | Purpose | Notes |
|---|---|---|
| **toybox** | Single-binary collection of POSIX coreutils — `ls`, `cat`, `grep`, `ps`, `top`, `chmod`, `mount`, `dd`, … | Most "standard" Unix utilities on OHOS resolve to toybox via symlink. Run `toybox` alone to see the list. |

Things that are **conspicuously missing** from stock OHOS coreutils
(none of these are toybox applets in the shipped configuration):
`stty`, `tput`, `resize`, `script`, `socat`, `screen`, `tmux`, `nc`,
`ssh`. See @hdc/resources/tty.md for the TTY-size workaround that's
needed because of the missing `stty`.

## Discovering more

`/system/bin/` is the canonical bin dir; `ls /system/bin` will show
everything available, including device-image-specific extras
(e.g. wifi/audio/sensor diagnostic binaries) that aren't documented in
the public OHOS docs. Combine with `grep -lE 'hdc shell' 
`<path_to_ohos_docs>/en/**/*.md` for fast lookup of any command's documentation.

## Host-side tools (NOT runnable via `hdc shell`)

For completeness — these live in the SDK's `toolchains/` and run on the
host, not the device. If a guide refers to them, don't try to push them
to the device:

- **app_check_tool** (jar) — analyze HAP/HSP/APP packages.
- **packing-tool / unpacking-tool** — assemble or extract HAPs.
- **binary-sign-tool** — sign HAPs.
- **restool** — compile resources.
- **rawheap-translator** — symbolicate heap captures.
