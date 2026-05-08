---
name: servo
description: Troubleshoot Servo build and runtime issues — confirm known bugs and apply documented work-arounds. Trigger when `./mach build` or `servoshell` fails;
---

# servo

A growing log of issues encountered when building or running [Servo](https://github.com/servo/servo), plus the diagnostic recipes that confirm them and the work-arounds where one exists. Issues unique to the OpenHarmony / HarmonyOS port live under "OHOS port" below.

## How this skill is organized

Each known issue lives in its own file under `resources/`. Files follow a fixed shape:

1. **Symptom** — the user-visible failure (build error, crash dialog, log line). Quote the message verbatim where possible so future grep-style lookups land in the right file.
2. **Confirm** — commands or checks that distinguish this issue from look-alikes. The user-visible symptom often matches several causes; this section pins down the right one.
3. **Root cause** — the underlying mechanism, with pointers into the source tree where it matters.
4. **Fix / work-around** — concrete options, in order of cheapness.

Add new issues by dropping a `resources/<slug>.md` file in the same shape, then linking it from the index below with a one-line symptom hook so symptom-grep against `SKILL.md` lands users on the right file.

## Known issues

### Build

- **`mach build --use-crown` aborts with `Library not loaded: librustc_driver-<hash>.{dylib,so,dll}`** after a `rust-toolchain.toml` bump — `crown` was built against the previous rustc and cargo only puts the active toolchain's `lib/` on the loader path, so the matching `librustc_driver` isn't visible. Fix is `cargo install --locked --path support/crown`. Details: @servo/resources/crown-librustc-driver.md
- **`mach build` fails inside a clang resource header (e.g. `avx10_2bf16intrin.h: error: use of undeclared identifier '__builtin_ia32_*'`)** — bindgen loaded one clang version's `libclang` but a different version's `clang` binary, so `libclang` is parsing intrinsic headers that reference builtins it doesn't know ([rust-bindgen#2682](https://github.com/rust-lang/rust-bindgen/issues/2682)). Fix is to set both `LIBCLANG_PATH` and `CLANG_PATH` to the same toolchain. Details: @servo/resources/bindgen-libclang-clang-mismatch.md

### OHOS port

- **`org.servo.servo` bundle launches then immediately terminates with `TypeError: Cannot read property initServo of undefined`** — `libservoshell.so` failed to load because the build SDK references NDK symbols (e.g. `OH_AVPlayer_SetDataSource`) at a higher API level than the device runtime supports; the napi loader logs this as a warning under `MUSL-LDSO` / `org.servo.servo/NAPI` in hilog, then binds `servoshell` to `undefined`, which surfaces as the misleading JS TypeError. Fix is to align the build SDK and `ohos-*-sys` feature pins with the device's `apiCompatibleVersion`. Details: @servo/resources/ohos-api-level-mismatch.md
