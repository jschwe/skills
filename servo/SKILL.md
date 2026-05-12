---
name: servo
description: Troubleshoot Servo build and runtime issues, and consult OHOS / HarmonyOS dev/test recipes for `servoshell` — launching via `aa start` with `--ps` / `--psn` flag forms, pushing test files / HTML fixtures / fonts / hosts files / TLS certs / `prefs.json` into the app sandbox, where on the device Servo reads its `prefs.json`, and keeping the device screen awake during testing. Trigger when `./mach build` or `servoshell` fails, OR **before running Servo on OHOS / HarmonyOS**, or when preparing to test Servo on an OHOS device, screenshotting Servo on device, driving Servo via uitest, pushing files into the Servo app sandbox (the running app cannot read `/data/local/tmp/`; files have to land under `/data/storage/...`, typically via `hdc file send -b org.servo.servo …`), setting Servo prefs on device, or launching `servoshell` with custom command-line flags.
crates: servo,servo-*
---

# servo

A growing log of issues encountered when building or running [Servo](https://github.com/servo/servo), plus the diagnostic recipes that confirm them and the work-arounds where one exists, with a few how-to recipes (e.g. launching the OHOS bundle with custom flags) at the bottom. Issues unique to the OpenHarmony / HarmonyOS port live under "Mobile (OHOS / Android)" below.

## How this skill is organized

Each known issue lives in its own file under `resources/`. Issue files follow a fixed shape:

1. **Symptom** — the user-visible failure (build error, crash dialog, log line). Quote the message verbatim where possible so future grep-style lookups land in the right file.
2. **Confirm** — commands or checks that distinguish this issue from look-alikes. The user-visible symptom often matches several causes; this section pins down the right one.
3. **Root cause** — the underlying mechanism, with pointers into the source tree where it matters.
4. **Fix / work-around** — concrete options, in order of cheapness.

Recipe files (under "Recipes" below) are how-tos rather than bug write-ups; they document procedures that other resources may reference (e.g. how to launch the OHOS bundle with custom flags, used while debugging several of the issues above).

Add new issues or recipes by dropping a `resources/<slug>.md` file, then linking it from the appropriate index section below with a one-line hook so symptom-grep against `SKILL.md` lands users on the right file.

## Known issues

### Build

- **`mach build --use-crown` aborts with `Library not loaded: librustc_driver-<hash>.{dylib,so,dll}`** after a `rust-toolchain.toml` bump — `crown` was built against the previous rustc and cargo only puts the active toolchain's `lib/` on the loader path, so the matching `librustc_driver` isn't visible. Fix is `cargo install --locked --path support/crown`. Details: @servo/resources/crown-librustc-driver.md
- **`mach build` fails inside a clang resource header (e.g. `avx10_2bf16intrin.h: error: use of undeclared identifier '__builtin_ia32_*'`)** — bindgen loaded one clang version's `libclang` but a different version's `clang` binary, so `libclang` is parsing intrinsic headers that reference builtins it doesn't know ([rust-bindgen#2682](https://github.com/rust-lang/rust-bindgen/issues/2682)). Fix is to set both `LIBCLANG_PATH` and `CLANG_PATH` to the same toolchain. Details: @servo/resources/bindgen-libclang-clang-mismatch.md

### Mobile (OHOS / Android)

> **Before running Servo on OHOS — grab the SCREEN wakelock.** The very first command of any OHOS Servo session should be:
> ```sh
> hdc shell 'hidumper -s PowerManagerService -a "-t"'    # grab; silent on success
> ```
> Release it when the session ends:
> ```sh
> hdc shell 'hidumper -s PowerManagerService -a "-f"'    # release; silent on success
> ```
> When the screen turns off, OHOS moves the foreground app to background and the system then **freezes** it (cgroup-based suspension): rendering stops, JS timers don't fire, scheduled tasks don't run, hdc-driven scripts see no progress. Consequences if you skip the wakelock:
> - **Performance measurements are invalid.** FPS, paint times, JS benchmarks captured across a screen-off window include an arbitrary frozen interval; the numbers are meaningless, not just "throttled".
> - **Driver scripts hang or time out.** A `--auto-quit-after-load-event=…` deadline can't fire while the app is frozen; uitest steps wait for UI that's not being updated.
> - **Screenshots / `uitest screenCap` return the lock screen**, getting misdiagnosed as a Servo crash.
>
> The screen-off timeout is user-configurable down to ~10s, so do not assume any safe default. Full rationale, idempotency notes, and the `power-shell timeout` alternative: @servo/resources/ohos-keep-screen-awake.md.

- **`org.servo.servo` bundle launches then immediately terminates with `TypeError: Cannot read property initServo of undefined`** *(OHOS only)* — `libservoshell.so` failed to load because the build SDK references NDK symbols (e.g. `OH_AVPlayer_SetDataSource`) at a higher API level than the device runtime supports; the napi loader logs this as a warning under `MUSL-LDSO` / `org.servo.servo/NAPI` in hilog, then binds `servoshell` to `undefined`, which surfaces as the misleading JS TypeError. Fix is to align the build SDK and `ohos-*-sys` feature pins with the device's `const.ohos.apiversion`. Details: @servo/resources/ohos-api-level-mismatch.md
- **`println!()` / `eprintln!()` produce no output on device** — `stdout` / `stderr` are not attached to a console on OHOS/Android. servoshell installs a redirect that forwards both fds through `log::debug!` (→ hilog/logcat), but it's gated on `cfg(not(servo_production))`, so production builds silently drop the output entirely. Non-production builds also pass through servoshell's in-process log filter (default allowlist includes `servoshell::egl::log=debug`), which a custom `--log-filter` / `log_filter` pref can inadvertently silence. Fix is to use `log!`/`tracing` macros instead of `println!`. Details: @servo/resources/mobile-stdout-not-visible.md

## Recipes

- **Launching Servo on OHOS and passing servoshell flags** — `hdc shell "aa start -a EntryAbility -b org.servo.servo"` to launch (force-stop first if it's already running); pass servoshell flags via `--psn=--<flag>[=value]` (single-token) or `--ps=--<key> <value>` (two-token), with the `=` between `--ps`/`--psn` and the flag mandatory. Flags reach `servoshell` via a translation step in `support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets`. Details: @servo/resources/ohos-launch-with-args.md
- **Keeping the OHOS screen awake during testing** — the screen-off timeout is user-configurable (no fixed default; can be as short as ~10s), so screenshots taken between launch and observation can come back as the lock screen even when Servo is fine. Detect via `hidumper -s ScreenlockService -a "-all"` (look at `screenLocked`) and `hidumper -s PowerManagerService -a "-s"` (look at `Current State` / `ScreenOffTime`). Two independent fixes: preferred is grabbing a SCREEN running lock with `hidumper -s PowerManagerService -a "-t"` (release at session end with `-f`), so the screen never sleeps while the lock is held; alternative is `power-shell timeout -o <ms>` / `-r` to extend the screen-off duration. `power-shell wakeup` to bring the screen back if it's already off. Details: @servo/resources/ohos-keep-screen-awake.md
- **Pushing test files into Servo's app sandbox on OHOS** — `hdc shell` and the running app see two different views of the filesystem; the simplest way to drop a fixture (HTML, font, image) where Servo can read it is `hdc file send -b org.servo.servo ./local /data/storage/el2/base/haps/servoshell/files/local` (host hdc ≥ 3.1.0e, debug-signed bundle, installed-and-started). Note Servo's HAP module name is `servoshell` despite the source-tree path being `support/openharmony/entry/...`. Resource also covers **pushing/editing the prefs file** — Servo reads `/data/storage/el2/base/cache/servo/prefs.json` (application-level *cache* dir, eviction-prone), with `--prefs-file` and `--pref=…` from the launch command as more durable alternatives. Plus the full sandbox-↔-physical mapping table, `-b` prerequisites, the last-resort fallback when `-b` is unavailable, and how to navigate Servo via `file://`. Details: @servo/resources/ohos-app-sandbox-and-pushing-files.md
