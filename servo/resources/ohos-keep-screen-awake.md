# Keeping the OHOS screen awake during testing

How to detect and avoid screen-off / lock-screen interference when iterating on Servo on a real OHOS device — taking screenshots, navigating, capturing logs, running performance measurements, or driving the device with `uitest`. The screen-off timeout is **user-configurable in Settings** (typical values range from ~10 seconds to a few minutes; there is no fixed system default to rely on), and on devices the user has set to short timeouts the screen routinely goes black mid-loop. Don't assume any particular timeout — query the device, then override.

## Why this matters: more than just screenshots

When the screen turns off, OHOS moves the foreground app to the **background** state, and the system then applies app-freeze (cgroup-based suspension) to background apps. While frozen, Servo:

- **Does not render frames.** Compositor and pipeline tasks are paused.
- **Does not run JS timers or `requestAnimationFrame` callbacks.** They queue or get coalesced; some are dropped entirely depending on the policy.
- **Does not service network I/O or page-load events.** A page that was "almost loaded" stays that way until the device is woken.
- **Does not respond to hdc-driven input.** `uitest uiInput` either fails to find the (un-rendered) target or finds it but the click has no effect because the app isn't scheduling.

Consequences cascade through every common task:

- **Performance measurements are invalid.** FPS counters, frame-time histograms, paint times, JS benchmark scores, and `tracing` spans that straddle the screen-off transition include an arbitrary "lights out" gap. The numbers are not "throttled" — they are *paused for some fraction of the interval you measured*, and there is no marker telling you which fraction.
- **Automation scripts hang or quietly stall.** A `--auto-quit-after-load-event=10s` timeout cannot fire while the app is frozen; `uitest` steps wait indefinitely for UI that's not being updated; host-side polling loops keep timing out on "the page should have loaded by now".
- **Screenshots return the lock screen.** `snapshot_display` / `uitest screenCap` capture whatever the display is currently showing — and "currently showing" is the lock-screen UI, regardless of what Servo would render if it were running.

Hilog tends to mislead the diagnosis: the *last* lines before the screen turned off look like normal Servo activity, log-only reasoning concludes "everything is fine", and the next visible event is the user pressing the power button minutes later. The freeze itself is silent.

## Symptom

- Performance numbers (FPS, paint times, JS bench scores) vary wildly run-to-run with no code change between runs, and the spread correlates with how long a run takes (longer runs → more screen-off time → worse numbers).
- An automation script appears to "hang" after a successful launch; `hdc shell` is still responsive, but the target app is not making progress.
- Screenshots taken via `snapshot_display -f /data/local/tmp/screen.png` (or `uitest screenCap`) return a clock-only / "swipe to unlock" image, even when Servo had been alive and rendering, because the device dimmed and locked between launch and capture.
- Hilog continues to show normal Servo activity up to a point and then goes silent, with the silence misread as "Servo crashed without a panic line".

## Confirm — was the screen actually off / locked?

Before assuming Servo crashed, query the device's own state directly. These are far more reliable than parsing a screenshot:

```bash
# Lock-screen state. Look at `screenState`, `screenLocked`, `deviceLocked`.
hdc shell 'hidumper -s ScreenlockService -a "-all"'
#  * screenState        true       screen on / off
#  * screenLocked       false      lock screen showing? (true = lock UI visible)
#  * deviceLocked       false      requires user auth before unlock?
#  * interactiveState   2          2 = interactive

# Power state + current screen-off timing.
hdc shell 'hidumper -s PowerManagerService -a "-s"'
# Current State: AWAKE  Reason: …  Time: …
# ScreenOffTime: Timeout=<N>ms                   ← whatever the user has configured;
#                                                  do not assume a particular default
# State: INACTIVE  Reason: TIMEOUT  Time: …      ← last transition into "about to sleep"
# State: SLEEP     Reason: TIMEOUT  Time: …
```

A "Current State: AWAKE" with `screenLocked: false` means the screen is on and the agent's screenshot, if blank, is not a screen-off problem (look at Servo itself instead). A `Current State: INACTIVE` / `SLEEP` or `screenLocked: true` confirms the device went to sleep mid-loop — apply the fix below.

## Fix — keep the screen on for the duration of the run

There are **two independent mechanisms** for this on OHOS. They can be used together, but most test workflows only need one. Both are non-persistent (released on reboot).

### Preferred: grab a SCREEN running lock (`hidumper -t` / `-f`)

`hidumper -s PowerManagerService -a "-t"` makes PowerManagerService take a `SCREEN`-type *running lock* (visible in dumps as `name=PowerMgrKeepOnLock`). As long as that lock is held, the screen does not turn off, regardless of the configured timeout. Release it with `-f`.

```bash
# Before:  hidumper ... -r | grep "SCREEN:"   → "SCREEN: 0"
hdc shell 'hidumper -s PowerManagerService -a "-t"'    # silent on success
# After:   hidumper ... -r | grep "SCREEN:"   → "SCREEN: 1"

# … run your test …

# Release the lock so screen-off resumes normally:
hdc shell 'hidumper -s PowerManagerService -a "-f"'    # also silent on success
```

Properties verified on device:
- Both `-t` and `-f` produce no confirmation output. Verify with the dump:
  ```bash
  hdc shell 'hidumper -s PowerManagerService -a "-r"' | grep -E 'SCREEN:|PowerMgrKeepOnLock'
  ```
  `SCREEN: 1` and an `index=… type=SCREEN name=PowerMgrKeepOnLock … state=1` line means the lock is held.
- **Idempotent.** Calling `-t` repeatedly in the same session does not stack — there is at most one `PowerMgrKeepOnLock` outstanding. A single `-f` releases it regardless of how many `-t` calls preceded.
- **Survives `aa start`/`aa force-stop`, app crashes, and host-side `hdc` reconnects.** A single `-t` at the start of the run covers the whole session.
- The lock is owned by PowerManagerService itself (uid 5528), not by the hdc client. So if your hdc session disconnects, the lock stays held — that's why `-f` at the end matters.

This is the right choice for almost all test workflows: the contract you actually want is "screen never sleeps until I'm done", not "screen sleeps after N minutes".

### Alternative: extend the screen-off timeout (`power-shell timeout -o` / `-r`)

`power-shell timeout` overrides the system's screen-off duration without changing any persisted setting. The screen still sleeps after the override interval expires, but the interval can be set arbitrarily long.

```bash
# Override to 30 minutes (in milliseconds). System message confirms:
#   "Override screen off time to 1800000"
hdc shell "power-shell timeout -o 1800000"

# … run your test …

# Restore the user's configured timeout:
hdc shell "power-shell timeout -r"
```

Use this rather than `-t`/`-f` when you specifically want a *bounded* keep-awake window — for example, a CI run that should self-recover by letting the screen sleep if the run hangs, with no host process available to send `-f`.

The override is observable in `hidumper -s PowerManagerService -a "-s"` as `OverrideTimeout=<N>ms` alongside the unchanged `Timeout=<N>ms`. Setting both `power-shell timeout -o` and `hidumper -t` simultaneously is harmless — they're independent — but you then need to remember to release both (`-r` and `-f`) at session end.

### Wake the screen first if it's already off

Both mechanisms only *prevent* future screen-offs; neither turns the screen back on. If the screen is already off when you start:

```bash
hdc shell "power-shell wakeup"                          # screen on (but still locked if a passcode is set)
hdc shell 'hidumper -s PowerManagerService -a "-t"'     # then take the keep-on lock
```

### Quick-reference command table

`power-shell help` and `hidumper -s PowerManagerService -a "-h"` list the full sets. The relevant ones for testing:

| Command | Effect |
|---|---|
| `hidumper -s PowerManagerService -a "-t"` | **Grab** the SCREEN running lock (`PowerMgrKeepOnLock`). Screen will not turn off while it is held. Idempotent. Silent on success. |
| `hidumper -s PowerManagerService -a "-f"` | **Release** the SCREEN running lock. Screen-off resumes per the configured timeout. Silent on success. |
| `hidumper -s PowerManagerService -a "-r"` | Inspect held running locks. `SCREEN: <N>` in the summary tells you whether the keep-on lock is currently held. |
| `hidumper -s PowerManagerService -a "-s"` | Inspect power state machine + current `Timeout` / `OverrideTimeout`. |
| `hidumper -s ScreenlockService -a "-all"` | Inspect lock-screen state (`screenState`, `screenLocked`, `deviceLocked`). |
| `power-shell wakeup` | Wake the system, turn the screen on. |
| `power-shell suspend` | Put the system to sleep, screen off. (Useful when explicitly testing background behavior.) |
| `power-shell timeout -o <ms>` | Override the screen-off time. Argument is milliseconds. |
| `power-shell timeout -r` | Restore the user's configured screen-off time. |
| `power-shell setmode <mode>` | Switch power profile: `600` normal / `601` power-save / `602` performance / `603` extreme power-save. Affects CPU/GPU governors and so changes Servo's measurable behavior — don't toggle this mid-measurement run unless that's the dimension you're testing. |

## Caveats

- **Both mechanisms are non-persistent across reboot.** If your test loop is robust to reboots, re-apply `-t` (or `power-shell timeout -o`) after every reboot.
- **Always pair the grab with the release.** `-t` without `-f`, or `power-shell timeout -o` without `-r`, leaves the device unable to ever sleep until the next reboot — the lock or override survives across hdc disconnects, app crashes, and CI cleanup. Even if your harness force-kills your script, neither of these get cleaned up automatically. Treat them like opening a file: if you grab one, register the release in a `trap` / `defer` / `finally` block.
- **Devices with a screen passcode still lock.** `power-shell wakeup` turns the screen on but it lands on the lock screen, not on the previously-foregrounded app. On a typical *debug* device without a passcode, swipe-up to unlock is automatic on wake; on user devices with a configured PIN/biometric, the agent will need additional steps (e.g. `uitest uiInput`) to actually reach the app's UI again. Plan for this on devices that aren't dev-only.
- **Don't conflate `power-shell setmode` with the keep-awake mechanisms.** `setmode` changes the CPU/GPU governor (and therefore performance characteristics), which is a separate axis from screen state. Most test runs want `-t`/`-f` (or `timeout -o`/`-r`) only, leaving `setmode` alone.

## Relating to the rest of this skill

- For taking screenshots themselves: `hdc shell "snapshot_display -f /data/local/tmp/screen.png"` followed by `hdc file recv /data/local/tmp/screen.png ./screen.png`. (The agent's harness also typically supports a screen-capture tool that wraps these.)
- The general `aa start` launch idiom and flag-passing rules live in `ohos-launch-with-args.md`. Combine: `power-shell wakeup` → `hidumper -s PowerManagerService -a "-t"` → `aa force-stop org.servo.servo` → `aa start -a EntryAbility -b org.servo.servo …` → (run + observe) → `hidumper -s PowerManagerService -a "-f"`.
- Servo's own logging filter is unaffected by screen state. If you're chasing a "did the page load?" question, prefer the `Servo is being initialised with the following Options` and `JSAPP: New URL from native` hilog lines (see `ohos-app-sandbox-and-pushing-files.md` "Verification") over a screenshot — they work regardless of screen state.
