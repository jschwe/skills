---
name: servo
description: Troubleshoot Servo build and runtime issues — confirm known bugs and apply documented work-arounds. Trigger when `./mach build` or `servoshell` fails;
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

- **`org.servo.servo` bundle launches then immediately terminates with `TypeError: Cannot read property initServo of undefined`** *(OHOS only)* — `libservoshell.so` failed to load because the build SDK references NDK symbols (e.g. `OH_AVPlayer_SetDataSource`) at a higher API level than the device runtime supports; the napi loader logs this as a warning under `MUSL-LDSO` / `org.servo.servo/NAPI` in hilog, then binds `servoshell` to `undefined`, which surfaces as the misleading JS TypeError. Fix is to align the build SDK and `ohos-*-sys` feature pins with the device's `const.ohos.apiversion`. Details: @servo/resources/ohos-api-level-mismatch.md
- **`println!()` / `eprintln!()` produce no output on device** — `stdout` / `stderr` are not attached to a console on OHOS/Android. servoshell installs a redirect that forwards both fds through `log::debug!` (→ hilog/logcat), but it's gated on `cfg(not(servo_production))`, so production builds silently drop the output entirely. Non-production builds also pass through servoshell's in-process log filter (default allowlist includes `servoshell::egl::log=debug`), which a custom `--log-filter` / `log_filter` pref can inadvertently silence. Fix is to use `log!`/`tracing` macros instead of `println!`. Details: @servo/resources/mobile-stdout-not-visible.md

## Recipes

- **Launching Servo on OHOS and passing servoshell flags** — `hdc shell "aa start -a EntryAbility -b org.servo.servo"` to launch (force-stop first if it's already running); pass servoshell flags via `--psn=--<flag>[=value]` (single-token) or `--ps=--<key> <value>` (two-token), with the `=` between `--ps`/`--psn` and the flag mandatory. Flags reach `servoshell` via a translation step in `support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets`. Details: @servo/resources/ohos-launch-with-args.md
