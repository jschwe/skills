# OHOS app sandbox: pushing files where Servo can read them

How to put a test file (image, font, prefs.json, fixture HTML, …) onto the device so the running `org.servo.servo` bundle can open it. The trick is that what `hdc shell` sees on the filesystem and what Servo sees from inside its app sandbox are **two different views of the same files** — so you have to push to the right path *and* know how to address it from servoshell.

## Two views of the filesystem

OHOS isolates each application via a per-app sandbox: the application can only see (a) the directories explicitly mapped into its sandbox and (b) a curated subset of system files. `hdc shell`, by contrast, runs as a system-level shell and sees the *physical* paths used to back those sandbox mappings. The two views are not one-to-one — sandbox paths are always shorter, and many physical paths have no sandbox mapping at all.

The authoritative mapping table from `~/Dev/ohos/ohos-docs/en/application-dev/file-management/app-sandbox-directory.md` (substitute `<USERID>` = current user, typically `100`, and `<PACKAGENAME>` = `org.servo.servo` for Servo):

| Sandbox path (what Servo sees) | Physical path (what `hdc shell` sees) | Purpose |
|---|---|---|
| `/data/storage/el1/bundle` | `/data/app/el1/bundle/public/<PACKAGENAME>` | Installation package directory — HAP, native libs, baked-in resources. Read-only at runtime. |
| `/data/storage/el1/base` | `/data/app/el1/<USERID>/base/<PACKAGENAME>` | EL1 (boot-time, no auth) per-app data. |
| `/data/storage/el2/base` | `/data/app/el2/<USERID>/base/<PACKAGENAME>` | **EL2 (post-auth) per-app data — the default writable area.** Subdirs: `files/`, `cache/`, `temp/`, `database/`, `distributedfiles/`, `haps/<MODULE>/{files,cache,temp,…}`. |
| `/data/storage/el1/database` | `/data/app/el1/<USERID>/database/<PACKAGENAME>` | EL1 database files. |
| `/data/storage/el2/database` | `/data/app/el2/<USERID>/database/<PACKAGENAME>` | EL2 database files. |
| `/data/storage/el2/distributedfiles` | `/mnt/hmdfs/<USERID>/account/merge_view/data/<PACKAGENAME>` | Distributed-files mount. |

EL1/EL2 are encryption levels: EL1 is unlocked once the device is on; EL2 is unlocked after the first user authentication. Default for app data is EL2; put data needed before first unlock (clock, alarm, wallpaper) under EL1.

The MUSL-LDSO log line that appears in the OHOS launch crash (see `ohos-api-level-mismatch.md`) — `dso=/data/storage/el1/bundle/libs/arm64/libservoshell.so` — is a sandbox path; the same `.so` exists at `/data/app/el1/bundle/public/org.servo.servo/libs/arm64/libservoshell.so` from `hdc shell`'s point of view.

### `<MODULE>` — the HAP module name, not the source-tree path

Inside `el2/base/haps/` and `el1/bundle/`, each HAP gets its own subdirectory named after its **module name** as declared in that HAP's `module.json5` (`module.name`). For Servo, that module is **`servoshell`** — declared in `support/openharmony/entry/src/main/module.json5` as `"name": "servoshell"`. So the actual on-device paths look like:

- `/data/storage/el2/base/haps/servoshell/files/` (sandbox)
- `/data/app/el2/100/base/org.servo.servo/haps/servoshell/files/` (`hdc shell` view)
- `/data/storage/el1/bundle/servoshell/resources/resfile/` (the read-only resource dir Servo's `EntryAbility.onCreate` passes to `initServo` as `resource_dir`)

> **Don't be misled by the source path.** Servo's HAP source tree is rooted at `support/openharmony/entry/src/...` because it was scaffolded from DevEco's default "entry" template, but the runtime module name is `servoshell`. If you grep for `"entry"` looking for the on-device module dir, you will not find it. Confirm with `grep -E '"name"' support/openharmony/entry/src/main/module.json5 | head -1`.

## Pushing a file into the sandbox

`hdc file send` supports a `-b <bundlename>` flag that targets the **sandbox view directly**, transparently mapping to the physical path and (importantly) setting the right uid/gid/SELinux labels so the app can actually open the file afterwards. This is the right tool for the job:

```bash
# Push host-side ./test.html into Servo's per-module files/ dir.
# DEST is in sandbox notation — i.e. what Servo will see, not what `hdc shell` sees.
hdc file send -b org.servo.servo ./test.html /data/storage/el2/base/haps/servoshell/files/test.html
```

After the push, `ls -la` on the *physical* path shows the file owned by the bundle's uid (`20020198` on the device tested) with `rw-rw----` (660) perms — i.e. servoshell can immediately read it without further `chown`. Verified end-to-end on a Mate 70 Pro running OpenHarmony 6.0.0.107 with hdc 3.2.0c: a pushed `file://...servo-sandbox-test.html` was loaded by Servo (`I … org.servo.servo/servoshell::egl::ohos: Servo is being initialised with the following Options: InitOpts { url: "file:///data/storage/el2/base/haps/servoshell/files/servo-sandbox-test.html", … }` followed by a successful navigation log line).

> **Prerequisites for `-b`:**
>
> 1. **The host hdc must be at least 3.1.0e** (the version that introduced `-b`). Check with `hdc -v`. Older hdc replies `[Fail]Unknown file option: -b` and there is no override — upgrade the client. As of mid-2026 mainstream HOS device firmware ships with a daemon that supports `-b`, but the host CLI is the easier thing to forget about, especially after switching machines.
> 2. **The bundle must be signed with a debug certificate.** The default Servo `mach build --ohos` builds a debug-signed HAP, so this is normally fine; release-signed HAPs reject the `-b` access path.
> 3. **The bundle must be installed and started at least once** so its sandbox is realized on disk. If you've just `bm install`-ed without running it, do `aa start -a EntryAbility -b org.servo.servo` first (then `aa force-stop org.servo.servo` if you want a clean state before pushing).

The same `-b` flag applies to `hdc file recv` for pulling files *out* of the sandbox (e.g. capturing logs, dumps, screenshots written by Servo to its `files/` dir):

```bash
hdc file recv -b org.servo.servo /data/storage/el2/base/haps/servoshell/files/screenshot.png ./screenshot.png
```

## Without `-b` (last-resort fallback)

If `-b` is genuinely unavailable — release build with no debug-cert option, or you need to land a file outside the app's sandbox (e.g. in `/system/lib64/...` to swap a system library on a rooted/eng device) — you have to operate in physical-path land:

```bash
# Stage in a globally-writable spot:
hdc file send ./test.html /data/local/tmp/test.html

# Move into the app's data dir from hdc shell. Requires root, AND many sandboxed
# automation environments (this skill's harness included) refuse to write into
# another bundle's data dir even when hdc shell is root, on the grounds that it's
# privileged manipulation of shared device state.
hdc shell "mv /data/local/tmp/test.html /data/app/el2/100/base/org.servo.servo/haps/servoshell/files/test.html"
# If the moved file ends up root-owned, also chown to the bundle uid (also root-only and
# also typically refused by hardened automation policies). The bundle uid for org.servo.servo
# can be read from `bm dump -n org.servo.servo | grep -E 'uid|gid'` or the directory's
# existing ownership; on the test device above it was 20020198.
```

In practice, if `hdc -v` reports a 3.1.0e+ host on a debug-signed bundle, the `-b` path is not just easier but also actually *permitted* — the fallback above tends to fail closed even on devices where it would mechanically work. **Upgrade your host hdc rather than chasing the fallback.**

## Where Servo can address pushed files from

Servo's entry ability already passes `this.context.resourceDir` into the napi `initServo` call (`support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets`). That gives Servo a path to the bundle's *bundled* (read-only, shipped-in-HAP) resources at `/data/storage/el1/bundle/servoshell/resources/resfile/`. For files you want to *push at test time*, prefer one of:

| Where to push | Sandbox path Servo sees | Survives uninstall? | Notes |
|---|---|---|---|
| `haps/servoshell/files/` | `/data/storage/el2/base/haps/servoshell/files/` | No (cleared on uninstall) | Standard module-scoped writable dir. First choice for per-test fixtures. |
| `files/` (app-level) | `/data/storage/el2/base/files/` | No | Application-scoped, shared across HAPs in the same app. Servo currently has only the `servoshell` HAP, so equivalent in practice. |
| `cache/` | `/data/storage/el2/base/haps/servoshell/cache/` | No, may be auto-cleared at runtime | Don't use for fixtures — system can reclaim. |
| `temp/` | `/data/storage/el2/base/haps/servoshell/temp/` | No, cleared on app exit | Useful for inputs you want gone after the run. |

If you need Servo to actually *navigate* to a pushed local file, use the standard `file://` URL form against the sandbox path:

```bash
hdc file send -b org.servo.servo ./fixture.html /data/storage/el2/base/haps/servoshell/files/fixture.html

# Then launch Servo pointing at it (see ohos-launch-with-args.md for the launch idiom):
hdc shell "aa force-stop org.servo.servo"
hdc shell "aa start -a EntryAbility -b org.servo.servo -U file:///data/storage/el2/base/haps/servoshell/files/fixture.html"
```

## Pushing or editing Servo's prefs file

Servo's user prefs file on OHOS lives at the **application-level cache dir**, not the per-module `files/` dir, because `ports/servoshell/egl/ohos/mod.rs::init_app` builds the config dir from `OH_AbilityRuntime_ApplicationContextGetCacheDir()` (i.e. `Context::cacheDir`):

| | Path |
|---|---|
| Source line | `let config_dir = PathBuf::from(&native_values.cache_dir).join("servo");` (`ports/servoshell/egl/ohos/mod.rs`, around `init_app`) |
| Sandbox view (what Servo opens) | `/data/storage/el2/base/cache/servo/prefs.json` |
| Physical view (where to push) | `/data/app/el2/100/base/org.servo.servo/cache/servo/prefs.json` |
| Bundled fallback (read-only) | `/data/storage/el1/bundle/servoshell/resources/resfile/servo/prefs.json` — copied to the cache path on first launch *only if a `prefs.json` was actually shipped in the HAP* (see `ports/servoshell/egl/ohos/mod.rs` "Try copy `prefs.json`" block) |

Loading order (`ports/servoshell/prefs.rs::get_preferences`): `Preferences::default()` → `<config_dir>/prefs.json` if it exists → each `--prefs-file <path>` from the CLI in order → individual `--pref=key=value` overrides from the CLI.

**Quick override — push a prefs.json into the cache dir:**

```bash
# Author your override. Only override the keys you actually want — no need
# to enumerate the full default set; missing keys keep their defaults.
cat > /tmp/prefs.json <<'EOF'
{
  "fonts.ohos.font_mgr.enabled": true,
  "dom.shadowdom.enabled": true
}
EOF

# Push to the application-level cache dir Servo reads on next launch.
hdc file send -b org.servo.servo /tmp/prefs.json /data/storage/el2/base/cache/servo/prefs.json

# Restart Servo to pick it up:
hdc shell "aa force-stop org.servo.servo"
hdc shell "aa start -a EntryAbility -b org.servo.servo"
```

**Caveat — the cache dir is reclaimable.** OHOS may auto-evict cache contents under storage pressure, so a prefs.json placed there is *not* guaranteed to survive across long-lived test runs or device reboots. Two more durable alternatives:

- **`--prefs-file` from the launch command.** Push the file to the (non-cache) module `files/` dir and point Servo at it on launch. This bypasses the cache entirely:

  ```bash
  hdc file send -b org.servo.servo /tmp/prefs.json /data/storage/el2/base/haps/servoshell/files/prefs.json
  hdc shell "aa force-stop org.servo.servo"
  hdc shell "aa start -a EntryAbility -b org.servo.servo \
    --psn=--prefs-file=/data/storage/el2/base/haps/servoshell/files/prefs.json"
  ```

  See `ohos-launch-with-args.md` for why `--psn=--<flag>=<value>` (single-token, `=`-glued) is the safe form. `--prefs-file` is `many`/repeatable; pass multiple `--psn=--prefs-file=<path>` to layer overlays.

- **Individual `--pref` flags on the launch command.** For one or two keys, skip the file entirely:

  ```bash
  hdc shell "aa start -a EntryAbility -b org.servo.servo \
    --psn=--pref=dom.shadowdom.enabled=true \
    --psn=--pref=fonts.ohos.font_mgr.enabled=true"
  ```

  Same caveat as in `ohos-launch-with-args.md`: repeating `--pref` requires `--psn=`, never `--ps=`, or the OHOS want-parameters dedup eats all but the last.

**Verifying the prefs took effect:**

```bash
# Confirm what Servo actually read:
hdc shell "cat /data/app/el2/100/base/org.servo.servo/cache/servo/prefs.json"
# And check at runtime via hilog — Servo logs preference application during init.
hdc shell "hilog -x" | grep -E 'org\.servo\.servo.*pref'
```

If the file isn't there at all and you didn't pass `--prefs-file`, Servo is running on `Preferences::default()` plus any `--pref=` overrides — no warning is emitted for a missing user prefs file (the path filter is `.filter(|path| path.exists())`).

## Verification

After a push, confirm placement and permissions from the *physical* view (so you also see uid/gid):

```bash
hdc shell "ls -lZ /data/app/el2/100/base/org.servo.servo/haps/servoshell/files/"
```

A successful `-b` push shows the file owned by the bundle uid (e.g. `20020198 20020198`) with mode `-rw-rw----`. If it shows `root root` instead, you pushed without `-b` (or the fallback dropped the chown step) and the open will fail with `EACCES` once Servo tries to read it — typically surfacing as a generic load error rather than a clear permission-denied message.

To confirm Servo actually opened the file end-to-end, grep hilog for the URL:

```bash
hdc shell "hilog -x" | grep -E 'org\.servo\.servo/servoshell::egl::ohos.*Servo is being initialised|org\.servo\.servo/JSAPP.*New URL'
```

You should see lines like:

```
I A0E0C3/org.servo.servo/servoshell::egl::ohos: Servo is being initialised with the following Options: InitOpts { url: "file:///data/storage/el2/base/haps/servoshell/files/<file>", resource_dir: "/data/storage/el1/bundle/servoshell/resources/resfile", commandline_args: "" }
I A03D00/org.servo.servo/JSAPP: New URL from native:  file:///data/storage/el2/base/haps/servoshell/files/<file>
```

If the URL is what you expected and there's no `EACCES` / "couldn't open" warning under `org.servo.servo/servo_base`, the file landed in the right place and was reachable from inside the sandbox.

## Reference

- `~/Dev/ohos/ohos-docs/en/application-dev/file-management/app-sandbox-directory.md` — authoritative path mapping table.
- `~/Dev/ohos/ohos-docs/en/application-dev/dfx/hdc.md` — `hdc file send` / `file recv` reference, including the `-b bundlename` flag and its requirements.
