# Launching Servo on OHOS and passing servoshell flags

How to start the `org.servo.servo` bundle from `hdc` and forward command-line arguments to `servoshell` — needed any time you want to enable tracing, change the log filter, set the screen size, etc., on a device build.

## Basic launch

```bash
hdc shell "aa start -a EntryAbility -b org.servo.servo"                        # default URL (servo.org)
hdc shell "aa start -a EntryAbility -b org.servo.servo -U https://example.com" # set the start URL
```

`aa start` is the OHOS application-launcher CLI; `-a` is the Ability name (servo's entry ability is `EntryAbility`), `-b` is the bundle name. The optional `-U <uri>` is the standard OHOS "want URI" — `EntryAbility.onCreate` reads it from `want.uri` and passes it to `servoshell.initServo` as the start URL.

`aa start` only **launches** the bundle; it does not bring an already-running instance to the foreground with new arguments. If a previous Servo process is already alive, force-stop it first or your new flags will be ignored:

```bash
hdc shell "aa force-stop -b org.servo.servo"
hdc shell "aa start  -a EntryAbility -b org.servo.servo --psn=--tracing-filter=trace"
```

## Passing servoshell flags via `--ps` / `--psn`

OHOS `aa start` does not have a generic "argv passthrough" — instead it carries arbitrary key/value pairs in the *want parameters*. Two forms are relevant:

| Form | Purpose | Example |
|---|---|---|
| `--psn=<flag>` | **Preferred for boolean / `=value` flags.** A single token — the `=` between `--psn` and `--<flag>` is mandatory. | `--psn=--tracing-filter=trace` |
| `--ps=<key> <value>` | Two tokens — the value is a separate `aa` argument. The `=` between `--ps` and `--<key>` is again mandatory; the value follows separated by a space. | `--ps=--screen-size 505x413` |

**The leading `--` on the servoshell flag is required.** OHOS pre-populates `want.parameters` with a set of default entries that the OS itself adds, and Servo's translation step (below) needs to forward only the keys that are servoshell flags. It uses `--` as the discriminator: any `want.parameters` key starting with `--` is treated as a flag and forwarded to `servoshell`; everything else is dropped silently. There is a guard list (`WRONG_COMMAND_ARRAY` in `EntryAbility.ets` — currently `tracing`, `devtools`, `force_ipc`, `multiprocess`, `webdriver`) that emits a loud hilog `error` if it sees a common flag name without the `--` prefix:

```
Servo EntryAbility: You probably meant to add -- infront of your argument, i.e., --psn=--tracing vs --psn=tracing. You used …
```

If you have set `--tracing-filter=…` and see no traces appearing, grep hilog for that warning first.

Examples:

```bash
# Trace everything in servo + servoshell:
hdc shell "aa start -a EntryAbility -b org.servo.servo --psn=--tracing-filter=trace"

# Override the in-process log filter (see mobile-stdout-not-visible.md):
hdc shell 'aa start -a EntryAbility -b org.servo.servo --psn=--log-filter=servoshell::egl::log=debug,script=trace,warn'

# Set window size and start URL together:
hdc shell "aa start -a EntryAbility -b org.servo.servo -U https://example.com --ps=--screen-size 505x413"

# Combine multiple flags (each gets its own --ps / --psn token):
hdc shell "aa start -a EntryAbility -b org.servo.servo --psn=--tracing-filter=trace --psn=--multiprocess"
```

## How the flags reach servoshell (the translation step)

OHOS gives the ability a `Want` object whose `parameters` is a string-keyed map. `support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets` walks that map at startup, keeps the keys whose name starts with `--`, joins them (and their values) with the ASCII Unit Separator (`\u{001f}`), and passes the result as `InitOpts.commandlineArgs` into the napi entry point `servoshell.initServo`. servoshell's Rust side splits on `\u{001f}` and feeds the resulting argv to its normal `bpaf` parser, the same one used on desktop.

Two consequences worth knowing:

1. **Unknown servoshell flags abort the launch.** servoshell currently exits with an error on unknown CLI options, so a typo (`--psn=--tracingg-filter=trace`) crashes the bundle in the same "load failed" way described in `ohos-api-level-mismatch.md`. This is also why the translation step filters by the `--` prefix in the first place: OHOS automatically pre-populates `want.parameters` with a number of default entries supplied by the OS (not by the user's `aa start` invocation), and `EntryAbility.ets` needs to forward only the keys that look like servoshell flags. Using `--` as the discriminator keeps user-supplied `--ps`/`--psn` flags and drops everything the OS adds, which would otherwise trip servoshell's unknown-option exit.
2. **Verify what servoshell actually received.** The translation step logs the joined argv at `debug` under tag `Servo EntryAbility`:

   ```bash
   hdc shell "hilog -x" | grep -E 'Servo EntryAbility.*Servoshell parameters'
   # → Servoshell parameters: --tracing-filter=trace --multiprocess
   ```

   If the line is missing entirely, your `--ps`/`--psn` form was malformed and `aa` discarded the parameter before the bundle ever saw it.

## Common pitfalls

- **`aa start` returns `start ability successfully.` even when servo is already running.** The exit code does not tell you whether your flags took effect. Always `aa force-stop` first when you've changed flags.
- **Spaces around `=`.** `--psn = --tracing-filter=trace` (with surrounding spaces) is not equivalent to `--psn=--tracing-filter=trace`; the former parses as three separate `aa` tokens and your flag is dropped.
- **Quoting.** Wrap the entire `aa start …` invocation in `"…"` or `'…'` for `hdc shell` so the shell on the host doesn't split the `--ps=--key value` pair before `hdc` forwards it.
- **`WRONG_COMMAND_ARRAY` only covers a fixed list.** If you mistype a flag name that isn't in that list (e.g. `--psn=tracing-filter=trace` — missing leading `--`), there is no warning; the parameter is silently dropped.

## Reference

- `support/openharmony/entry/src/main/ets/entryability/EntryAbility.ets` — the translation step (`onCreate`).
- OHOS `aa` tool reference: <https://docs.openharmony.cn/pages/v5.0/en/application-dev/tools/aa-tool.md> (also at `~/Dev/ohos/ohos-docs/en/application-dev/tools/aa-tool.md`).
