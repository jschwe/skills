# `println!` / `eprintln!` output is invisible on OHOS and Android

## Symptom

A developer adds `println!()` or `eprintln!()` to `servoshell` (or any crate it pulls in) to print a quick value, builds for OHOS or Android, runs the bundle, and the line never appears anywhere — not in `hilog -x`, not in `logcat`, not in any faultlog. Other log lines from the same code path (`info!`, `debug!`, etc.) do show up, which makes the absence of the `println!` output especially confusing.

## Confirm

1. Check which build profile produced the bundle. The redirect described under "Root cause" is gated on `cfg(not(servo_production))` — i.e. it is compiled out in production builds. The default `--profile=production` of `mach build --ohos` / `mach build --android` is therefore the canonical way to lose stdout entirely.

   ```bash
   ./mach build --ohos --flavor=harmonyos --profile=release   # has redirect
   ./mach build --ohos --flavor=harmonyos --profile=production # no redirect
   ```

2. If the build was non-production, check the **servoshell-internal** log filter. There are two filtering stages between `println!` and your `hilog -x` output, and both have to pass:

   1. **servoshell's in-process log filter** (an `env_filter`-style allowlist set up at startup; see `ports/servoshell/egl/ohos/mod.rs::LOGGER` and `ports/servoshell/egl/android/mod.rs`). The default allowlist on both platforms includes `servoshell::egl::log=debug` *specifically so the redirected stdout/stderr passes through by default*; it also debug-promotes a curated set of Servo modules (`servo`, `servoshell`, `script::dom::console`, `paint::paint`, `servo_constellation::constellation`, `script::dom::bindings::error`, etc.). Everything else is filtered to `Warn`. **If you have overridden this filter** — via the `--log-filter "<spec>"` CLI argument or the `log_filter` user pref on OHOS, or via the `logStr` option on Android — the override on OHOS *replaces* the default outright, so a filter like `--log-filter "servo=info"` silently drops your redirected stdout because `servoshell::egl::log` is no longer in the allowlist. (Android's override is additive: it appends the comma-separated modules to the default allowlist.)
   2. **The system log filter** (hilog on OHOS, logcat on Android). This sits downstream of servoshell's filter and applies normal viewer-side filtering:

      ```bash
      hdc shell "hilog -b D"                          # raise default level to debug
      hdc shell "hilog -p off"                        # disable privacy redaction (otherwise <private> shows up)
      hdc shell "hilog -L D -T servoshell" | grep -i 'your-marker'
      # Android equivalent:
      adb logcat *:D | grep servoshell
      ```

   For the redirect to be visible end-to-end, both stages must allow `debug` for `servoshell::egl::log`. The default config already does on both platforms; the common way to break it is a custom `--log-filter` on OHOS that omits `servoshell::egl::log`.

3. Sanity-check by replacing the `println!()` with `log::debug!("…")` (or `log::info!`) directly. If the `debug!`/`info!` line appears under the same filter but the `println!` does not, the issue is the missing stdout redirect (production build). If the `debug!`/`info!` line is also missing, suspect a too-strict in-process filter override or hilog filter.

## Root cause

OHOS and Android do not attach a controlling terminal to app processes. When the runtime starts the process, file descriptors 1 and 2 are not connected to a console, a host shell, or a log pipe — they're effectively `/dev/null`. Anything written to `stdout` / `stderr` via `println!`, `eprintln!`, `dbg!`, the `print!` family, or `write!` against `io::stdout()` / `io::stderr()` is silently dropped.

To make development possible, servoshell installs a redirect helper at startup *only in non-production builds*:

- `ports/servoshell/egl/log.rs::redirect_stdout_and_stderr` creates an OS pipe, `dup2`s the writer end onto fds 1 and 2, and spawns a thread that reads the pipe and forwards each newline-terminated chunk via `log::debug!`. The `log` facade is wired to hilog (OHOS) or logcat (Android), so the output then surfaces under the configured filter.
- The call sites are gated behind `#[cfg(not(servo_production))]` in `ports/servoshell/egl/ohos/mod.rs` and `ports/servoshell/egl/android/mod.rs` (see the `// We only redirect stdout and stderr for non-production builds` comments). The reasoning recorded in those comments is that the helper is debug-only and saves one thread in production.

So in a `--profile=production` build the redirect simply isn't there, and any `println!()` you add is writing to a closed/null fd. Even in non-production builds, the redirect funnels everything through `debug!`, so the *visibility* of the output is then subject to whatever log filter `hilog` / `logcat` is using.

This is also a desktop / mobile asymmetry trap: identical code that prints fine when developing on Linux/macOS goes silent the moment it runs inside the OHOS or Android bundle, with no compile-time warning that `stdout` won't reach the user.

## Fix / work-around

In order of preference:

1. **Don't use `println!` / `eprintln!` in code that runs on mobile.** Use the `log` (or `tracing`) macros — `info!`, `debug!`, `warn!`, `error!` — which already go through the platform's structured logger. They work identically on desktop and mobile, are filterable by tag/level on device, and are not affected by the production gate.

   ```rust
   // Replace this:
   println!("loaded {n} prefs");
   // With:
   log::info!("loaded {n} prefs");
   ```

2. **If you have an existing non-production build and want to avoid recompiling** (for example, the missing output is from a vendored crate's `eprintln!` you can't easily patch, or you're chasing a regression you can already reproduce on a build that's installed), the redirect helper is already compiled in and the default in-process log filter already passes `servoshell::egl::log=debug`, so redirected output reaches hilog/logcat without further configuration. (For a one-off `println!` you were planning to add yourself, prefer option 1 — switch the call to `log::info!` instead.)

   ```bash
   ./mach build --ohos --flavor=harmonyos --profile=release
   hdc shell "aa start -a EntryAbility -b org.servo.servo -U https://example.com/"
   hdc shell "hilog -x" | grep -i 'your-marker'
   # If your marker is missing, also try:
   hdc shell "hilog -b D"          # bump system filter
   hdc shell "hilog -p off"        # disable privacy redaction
   ```

   If you've passed `--log-filter` on the command line or set the `log_filter` pref on OHOS, **include `servoshell::egl::log=debug` in the override** — the override replaces the default allowlist, so any spec that omits this module silences your redirected stdout:

   ```bash
   # OK on OHOS — keeps the stdout redirect visible while raising script:: to trace:
   --log-filter "servoshell::egl::log=debug,script=trace,warn"
   ```

3. **Do not** "fix" the production silence by removing the `#[cfg(not(servo_production))]` gate around `redirect_stdout_and_stderr` in `ports/servoshell/egl/{ohos,android}/mod.rs` to push your debug print out the door. Production profile is what ships to users; the gate is intentional. Convert the call site to a logging macro instead.

## Notes

- Crate dependencies that print directly (e.g. some C bindings, or `dbg!` left in third-party code) are also silenced under this mechanism. If a vendored crate is producing critical diagnostics via `eprintln!`, prefer raising the issue upstream / patching the dep to use `log!` rather than disabling the production gate.
- The redirect operates per-line: very long unterminated writes are flushed once the 512-byte internal buffer fills, so partial lines are not strictly lost — they're just split. Invalid UTF-8 produces a `warn!` ("Dropping 1 log message due to invalid encoding") followed by the raw bytes at `debug!`.
- **hilog rate-limits log output, and the limit is per-level.** Even with the redirect installed and both filters open, if the source emits messages faster than hilog accepts them, individual lines are dropped silently — there is no "X messages suppressed" marker. The thresholds vary by message type: `error!` lines have a relatively low rate limit (the system protects itself against an error storm filling the buffer), while `debug!` lines — including everything that comes through the stdout/stderr redirect, since it forwards via `log::debug!` — have a much higher one. So a tight loop of `error!` calls is more likely to lose messages than the same volume of `debug!` calls. If you suspect you're hitting this, either down-level the noisy site to `debug!` / `trace!`, batch multiple events into one log call, or capture the data through a non-hilog channel (file write, DevTools, tracing-perfetto). The same caveat applies on Android (logcat has its own per-buffer rate limits).
