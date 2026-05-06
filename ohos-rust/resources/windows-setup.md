# ohos-rust — Windows host setup (PowerShell)

The `<rust-triple>-clang` wrappers in `$OHOS_SDK_NATIVE/llvm/bin/` are
POSIX shell scripts (no `#!/usr/bin/env` interpreter on Windows, no
`.cmd`/`.bat` shim). Cargo on Windows can't invoke them as a linker, so
this host needs the longer env-var form: point the linker at
`clang.exe` directly and pass `--target=` / `--sysroot=` via rustflags.

Everything below assumes PowerShell. If you're using `cmd.exe`, swap
`$env:NAME = "value"` for `set NAME=value` and forward slashes still
work in most paths.

## Prerequisites

- Stable rustup with the OHOS targets installed:

  ```powershell
  rustup target add `
      aarch64-unknown-linux-ohos `
      armv7-unknown-linux-ohos `
      x86_64-unknown-linux-ohos
  ```

- The **Windows** OHOS SDK (not the Linux/macOS one) extracted somewhere,
  with `$env:OHOS_SDK_NATIVE` pointing at its `native\` directory. The
  same discovery rules from SKILL.md apply, but on Windows the
  api-level dir is the same shape — `<sdk-root>\<api>\native\`.

- A few sanity checks:

  ```powershell
  Test-Path "$env:OHOS_SDK_NATIVE\llvm\bin\clang.exe"   # → True
  Test-Path "$env:OHOS_SDK_NATIVE\sysroot"              # → True
  & "$env:OHOS_SDK_NATIVE\llvm\bin\clang.exe" --version
  ```

## Linker + rustflags

```powershell
$NDK   = $env:OHOS_SDK_NATIVE
$CLANG = "$NDK\llvm\bin\clang.exe"

# aarch64
$env:CARGO_TARGET_AARCH64_UNKNOWN_LINUX_OHOS_LINKER   = $CLANG
$env:CARGO_TARGET_AARCH64_UNKNOWN_LINUX_OHOS_RUSTFLAGS = `
    "-C link-arg=--target=aarch64-linux-ohos " +
    "-C link-arg=--sysroot=$NDK\sysroot"

# armv7 — clang target is arm-linux-ohos, not armv7-…
$env:CARGO_TARGET_ARMV7_UNKNOWN_LINUX_OHOS_LINKER     = $CLANG
$env:CARGO_TARGET_ARMV7_UNKNOWN_LINUX_OHOS_RUSTFLAGS  = `
    "-C link-arg=--target=arm-linux-ohos " +
    "-C link-arg=-march=armv7-a " +
    "-C link-arg=-mfloat-abi=softfp " +
    "-C link-arg=--sysroot=$NDK\sysroot"

# x86_64
$env:CARGO_TARGET_X86_64_UNKNOWN_LINUX_OHOS_LINKER    = $CLANG
$env:CARGO_TARGET_X86_64_UNKNOWN_LINUX_OHOS_RUSTFLAGS = `
    "-C link-arg=--target=x86_64-linux-ohos " +
    "-C link-arg=--sysroot=$NDK\sysroot"

cargo build --release --target aarch64-unknown-linux-ohos
```

The Rust→clang triple mapping is identical to the Unix case (see the
table at the bottom of SKILL.md). It just has to be specified explicitly
here because no wrapper script is doing it for you.

## Path separators

Cargo passes the rustflags string to rustc verbatim, which forwards them
to clang. clang on Windows accepts both `\` and `/` in paths, but `\`
inside double-quoted PowerShell strings is fine — no escaping needed
unless the path contains spaces, in which case wrap individual args
with extra quoting:

```powershell
$env:CARGO_TARGET_AARCH64_UNKNOWN_LINUX_OHOS_RUSTFLAGS = `
    "-C link-arg=--target=aarch64-linux-ohos " +
    "-C ""link-arg=--sysroot=$NDK\sysroot"""   # double-quotes inside the string
```

If you see clang complaining `cannot find input file` and the path in
the error message is truncated at a space, that's the cause.

## Persisting the env vars

The blocks above set the variables for the **current PowerShell session
only**. To make them survive a reboot, write them into your PowerShell
profile (`$PROFILE`):

```powershell
notepad $PROFILE
```

…and paste the same `$env:CARGO_TARGET_…` lines, with `$NDK` resolved at
profile-load time, e.g.:

```powershell
$env:OHOS_SDK_NATIVE = "C:\ohos-sdk\windows\14\native"
$env:CARGO_TARGET_AARCH64_UNKNOWN_LINUX_OHOS_LINKER = "$env:OHOS_SDK_NATIVE\llvm\bin\clang.exe"
# … etc.
```

Or set them as **user-level** environment variables via
`[Environment]::SetEnvironmentVariable(...)` so they apply to every
shell, not just PowerShell:

```powershell
[Environment]::SetEnvironmentVariable(
    "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_OHOS_LINKER",
    "$env:OHOS_SDK_NATIVE\llvm\bin\clang.exe",
    "User")
```

## C/C++ deps on Windows

The cc-rs / bindgen wiring described in @ohos-rust/resources/c-deps.md
applies on Windows too — translate each `export FOO=bar` to
`$env:FOO = "bar"`. The same caveat about `--target=`/`--sysroot=`
having to be specified explicitly (since the Unix wrappers aren't
usable) holds for `CFLAGS_*` / `CXXFLAGS_*` /
`BINDGEN_EXTRA_CLANG_ARGS_*`.
