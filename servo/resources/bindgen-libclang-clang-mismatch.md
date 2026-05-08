# Build fails inside clang internal headers (e.g. `avx10_2bf16intrin.h`)

## Symptom

`./mach build` fails during a `bindgen`-driven crate's `build.rs` (typically `mozjs_sys`, `style`, `script`, or any `*-sys` crate) with errors *inside clang's own bundled headers* — undefined `__builtin_*` identifiers, missing intrinsic types, or unrecognized attributes. Verbatim example from [servo/servo#40782](https://github.com/servo/servo/issues/40782) on Ubuntu 26.04:

```
--- stderr
/usr/lib/llvm-20/lib/clang/20/include/avx10_2bf16intrin.h:855:20: error: use of undeclared identifier '__builtin_ia32_vfmaddnepbh256'
/usr/lib/llvm-20/lib/clang/20/include/avx10_2bf16intrin.h:883:20: error: use of undeclared identifier '__builtin_ia32_vfmaddnepbh256'
/usr/lib/llvm-20/lib/clang/20/include/avx10_2bf16intrin.h:911:20: error: use of undeclared identifier '__builtin_ia32_vfmaddnepbh256'
…
```

The hallmark is that the file path of the failing header points *into a clang resource directory* (`.../lib/clang/<version>/include/`), not into Servo, libc, or a vendored dep, and the failing identifiers are clang built-ins (`__builtin_ia32_*`, `__builtin_arm_*`, `__nvvm_*`, …) that the *compiler* should have provided.

## Confirm

The failure is the bindgen-side consequence of [rust-bindgen#2682](https://github.com/rust-lang/rust-bindgen/issues/2682): bindgen is loading **two different clang versions** — `libclang.so` for parsing, and the `clang` binary for include-path detection — and the version mismatch only surfaces when the two disagree about which builtins exist.

1. Check the version of the `clang` binary that's first on `PATH`:

   ```bash
   clang --version
   ```

2. Check which `libclang` bindgen would load. `bindgen` (via `clang-sys`) picks the highest-versioned `libclang` it finds in the system search paths, **independent** of `clang`. On Debian/Ubuntu:

   ```bash
   dpkg -l | grep -E 'libclang(1)?-[0-9]+'        # all installed libclang runtimes
   ldconfig -p | grep libclang                    # what the dynamic loader sees
   ```

   This issue is mainly seen on Linux where multiple `clang` / `libclang` packages can coexist. macOS systems generally have only the Xcode/Command Line Tools clang in play (Servo does not currently build with Homebrew LLVM out of the box, and `clang-sys` falls through to the Xcode toolchain), so the mismatch does not normally arise there.

3. Compare the `clang` binary version with the highest `libclang` version present. **If they differ, this is the issue.** In the linked Servo report, the user had `clang-20` as the binary and `libclang1-21` also installed; bindgen used libclang-21 to parse headers from clang-20's resource directory, and `avx10_2bf16intrin.h` shipped by clang-20 referenced `__builtin_ia32_vfmaddnepbh256` — a builtin that libclang-21 does not expose under that name in clang-20's header tree.

   The reporter resolved it by removing `libclang1-21` from the system; that works but is collateral damage. Setting `LIBCLANG_PATH` and `CLANG_PATH` (below) is the targeted fix and does not require uninstalling anything.

## Root cause

`bindgen` does two things that should agree but don't:

- **Parses** C/C++ headers using `libclang.so` / `libclang.dylib`. The path is taken from `LIBCLANG_PATH` if set, otherwise `clang-sys` searches a hard-coded list of system locations and picks the highest version it finds.
- **Discovers system include paths** (where libc, the clang resource dir, etc. live) by spawning the `clang` *binary* with `clang -E -xc -v -` and parsing its output. The binary used is whatever `clang-sys::support::Clang::find` resolves first — `CLANG_PATH` if set, otherwise the first `clang` on `PATH`.

Each clang release ships its own resource directory containing version-specific intrinsic headers (`avx10_2bf16intrin.h`, `avx512fp16intrin.h`, `arm_neon.h`, …) that reference built-in functions newly added in *that* release. When the parser (`libclang`) and the resource-dir owner (`clang` binary) are different versions:

- libclang vN tries to compile clang vM's intrinsic header.
- The header references `__builtin_<foo>` introduced in clang vM.
- libclang vN's built-in table doesn't include that symbol.
- Compilation aborts inside the system header.

This is fully upstream's bug — see [rust-bindgen#2682](https://github.com/rust-lang/rust-bindgen/issues/2682) — and not a Servo-specific issue. It just hits Servo more often than most projects because Servo bindings touch many C/C++ headers and `mach bootstrap` does not pin a clang for the user.

## Fix / work-around

Set **both** environment variables to point at the same toolchain so bindgen's libclang and bindgen's `clang -E` invocation are version-locked:

```bash
# Linux example (LLVM 20 from the distro packages):
export LIBCLANG_PATH=/usr/lib/llvm-20/lib
export CLANG_PATH=/usr/lib/llvm-20/bin/clang
```

Then re-run `./mach build`. Persist the exports in your shell rc / direnv / `.cargo/config.toml`'s `[env]` table if multiple developers on the machine hit it.

**Setting only one of the two is not enough.** `LIBCLANG_PATH` alone leaves the include-path detection still using whatever `clang` happens to be on `PATH`; `CLANG_PATH` alone leaves `libclang` selection to `clang-sys`'s version-greedy search.

Other valid resolutions, in decreasing order of cleanliness:

1. **Uninstall the higher-versioned `libclang` runtime** (e.g. `apt purge libclang1-21` in the linked report) so only one version is reachable. Works, but heavy-handed and breaks unrelated tools that wanted that libclang.
2. **Uninstall the lower-versioned `clang` binary** so only the higher one is on `PATH`. Same caveats.
3. **Match versions at install time.** On distros where the metapackage `clang` and `libclang-dev` track the same major version, install both from the same release (`clang-20` + `libclang-20-dev`) and ensure no other `libclang*` package is present.
