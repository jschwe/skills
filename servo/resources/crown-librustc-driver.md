# `crown` aborts: `Library not loaded: librustc_driver-<hash>`

## Symptom

A `mach build --use-crown` (or any cargo invocation that runs `crown` as a rustc wrapper) aborts before compilation starts with a dynamic-loader error pointing at `librustc_driver-<hash>.{dylib,so,dll}`. On macOS:

```
error: process didn't exit successfully: `crown -vV` (signal: 6, SIGABRT: process abort signal)
--- stderr
dyld[72840]: Library not loaded: @rpath/librustc_driver-6baea8b00e20195f.dylib
  Referenced from: <…> /Users/<user>/.cargo/bin/crown
  Reason: tried: '/Users/<user>/.rustup/toolchains/1.95.0-aarch64-apple-darwin/lib/librustc_driver-6baea8b00e20195f.dylib' (no such file), …

Failed in 0:00:00
```

The hash, suffix, and exact wording vary by platform — Linux reports `error while loading shared libraries: librustc_driver-<hash>.so`, Windows reports a missing `rustc_driver-<hash>.dll` — but the shape is the same: `crown` cannot find the `librustc_driver` it was linked against.

## Confirm

1. Read the rustc version Servo currently pins:

   ```bash
   grep '^channel' rust-toolchain.toml      # e.g. channel = "1.95.0"
   ```

2. List the `librustc_driver` actually present in that toolchain:

   ```bash
   # Assumes `rust-toolchain.toml` is in the CWD.
   ls "${RUSTUP_HOME:-$HOME/.rustup}/toolchains/$(grep -E '^channel' rust-toolchain.toml | cut -d'"' -f2)-$(rustc -vV | awk '/host:/ {print $2}')/lib/" | grep rustc_driver
   ```

   Compare the hash in the filename to the hash in the error message. **If the toolchain is present but the hash differs, `crown` was built against an older rustc than the one now pinned** — that is this issue. If the toolchain directory itself is missing, run `rustup toolchain install` first; that is a different problem.

3. Confirm that `crown` is installed (`which crown` resolves, typically to `~/.cargo/bin/crown`). If it isn't installed at all, the error wording is different (`crown: command not found`).

## Root cause

`crown` is Servo's lint driver to prevent GC hazards, implemented as a rustc plugin. Plugins link directly against `librustc_driver`, whose ABI is unstable and whose filename embeds a per-build hash that changes with every rustc build.

When `cargo` invokes a rustc wrapper (such as `crown`), it sets the dynamic-linker search path (`LD_LIBRARY_PATH` on Linux, `DYLD_FALLBACK_LIBRARY_PATH` on macOS, `PATH` on Windows) to point at the **active** toolchain's `lib/` directory — i.e. the one selected by `rust-toolchain.toml`. Other rustup toolchains on disk are not added to the search path, even if they still exist.

So after a `rust-toolchain.toml` bump:

- The active toolchain's `lib/` contains `librustc_driver-<new-hash>.{dylib,so,dll}`.
- The installed `crown` binary, built against the previous toolchain, embeds an rpath reference to `librustc_driver-<old-hash>.{dylib,so,dll}`.
- The loader looks for `<old-hash>` only in the paths cargo provided (the active toolchain) and reports "no such file", even when the old toolchain — and its matching `librustc_driver` — is still installed elsewhere under `~/.rustup/toolchains/`.

The expected library — the one cargo's search path covers — lives at:

```
${RUSTUP_HOME:-$HOME/.rustup}/toolchains/<channel>-<host-triple>/lib/librustc_driver-<hash>.{dylib,so,dll}
```

where `<channel>` is whatever `rust-toolchain.toml` declares.

## Fix / work-around

> **Do not** try to "fix" this by exporting `LD_LIBRARY_PATH` / `DYLD_FALLBACK_LIBRARY_PATH` to point at an older toolchain's `lib/`, copying or symlinking the old `librustc_driver` into the active toolchain, or otherwise tricking the loader into finding the stale library. Even if `crown` then starts, it is now running with a `librustc_driver` whose ABI does not match the rustc that cargo is invoking for the rest of the build — results range from silent miscompilation to confusing crashes deep inside compilation. The only correct fix is to rebuild `crown` against the active toolchain.

In order of cheapness:

1. **Rebuild and reinstall `crown` against the new toolchain.** From the Servo checkout:

   ```bash
   cargo install --locked --path support/crown
   ```

   This is the canonical fix and is what the Servo docs prescribe after every toolchain bump.

2. **Skip `crown` for the build.** Drop `--use-crown` from the `mach build` invocation. The build will succeed but the Servo-specific lints `crown` enforces (e.g. unrooted GC types in DOM code) will not run, so this is only acceptable for local iteration — never for code you intend to land.

## Notes

- The companion `support/crown/rust-toolchain.toml` must match the top-level `rust-toolchain.toml`; if a contributor has updated only one of them, `cargo install --locked --path support/crown` will pull the wrong rustc and the rebuilt `crown` will still mismatch. Cross-check both files before reinstalling.
- This is not specific to `--use-crown`: any tool that invokes `crown` as a rustc wrapper (e.g. some `mach test-tidy` paths) hits the same failure.
