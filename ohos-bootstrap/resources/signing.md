# HAP signing material: generating it on Windows, installing it in the container

Most devices refuse to install an unsigned HAP. `hvigor` signs during
`assembleHap`, using a `signingConfigs` entry that points at a certificate, a
provisioning profile and a keystore. Generating those requires DevEco Studio,
which only runs on Windows and macOS — so on a Linux box or in a container this
is always a hand-off from a human.

## Step 1 (user, in DevEco Studio) — generate the material

Signing material is bound to **two** things, and both force a regeneration:

- the **bundle name** — one run per app;
- the **device**, for HarmonyOS debug profiles — the `.p7b` embeds an allowlist
  of device UDIDs, so a phone that was not registered when the profile was
  issued cannot install the HAP. A new device means a new profile, even for the
  same app. (OpenHarmony `default` material using the public debug keys has no
  such list; this is a HarmonyOS `hos` constraint.)

Because of the second one, DevEco has to **see the device** while generating:
plug it into the machine running the IDE and confirm `hdc list targets` there
first. The UDID it registers is readable with:

```shell
hdc shell bm get --udid
```

For this workspace there are two apps:

| Project | Bundle name |
|---|---|
| `servo/support/openharmony` (servoshell) | `org.servo.servo` |
| `servo/ports/arkweb/test-app` (ArkWeb test app) | `org.openharmonyrs.arkwebtest` |

For each one:

1. Open the project directory in DevEco Studio.
2. `File > Project Structure > Signing Configs`.
3. Tick **Automatically generate signature**. Sign in with a Huawei account when
   asked — the profile is issued by the developer service.
4. Wait for it to report success, then `OK`.

If DevEco refuses to open the project (an hvigor version it dislikes, a missing
`local.properties`), generating the material in a throwaway app with the *same
bundle name* works just as well — only the bundle name in `AppScope/app.json5`
matters.

> A note that saves an hour: `default` (OpenHarmony) and `hos` (HarmonyOS) are
> different signing types with different material. An OpenHarmony board such as
> the DAYU200 takes the `default` flavor; a HarmonyOS phone (Mate series) needs
> `hos`. Generating one does not give you the other.

### What DevEco writes, and where

- `<USER HOME>\.ohos\config\` — the certificate (`.cer`), the provisioning
  profile (`.p7b`), the keystore (`.p12`), the CSR, and a `material\` directory
  holding the key material used to encrypt the passwords.
- The project's `build-profile.json5` — an `app.signingConfigs` array with
  **absolute Windows paths** and the passwords in encrypted form.

Both halves are needed. The passwords in `build-profile.json5` are useless
without `config\material\`, and vice versa.

## Step 2 (user) — hand it over

Ask for exactly two things:

```powershell
# in PowerShell
Compress-Archive -Path $env:USERPROFILE\.ohos -DestinationPath $env:USERPROFILE\ohos-signing.zip
```

and the project's `build-profile.json5` (one per app). Upload both into the
agent's workspace — over the file share if one is mounted
(@ohos-bootstrap/resources/windows-share.md), otherwise any upload path.

These are development signing credentials. They are not production keys, but
they are still credentials: keep them out of git. In this workspace they live in
`ohos-config/`, which is untracked.

## Step 3 (agent) — install it in the container

```shell
unzip ohos-signing.zip -d /workspaces/servo-workspace/       # yields ohos-config/config/...
uv run skills/ohos-bootstrap/resources/install_signing.py \
    --material-dir ohos-config \
    --build-profile /path/to/uploaded/build-profile.json5 \
    --out ohos-config/signing-configs.json
```

The script rewrites the Windows paths to paths **relative to the output file**,
keeps the encrypted passwords as-is, and checks the layout rule below.

Then export the path — in this container it is already set in
`devcontainer.json`:

```shell
export SERVO_OHOS_SIGNING_CONFIG=/workspaces/servo-workspace/ohos-config/signing-configs.json
```

### The layout rule that breaks signing quietly

hvigor decrypts each password by reading key material from the directory
**next to the keystore**:

```js
// hvigor-ohos-plugin/src/tasks/sign/command-builder-impl/common-sign-command-builder.js
DecipherUtil.decryptPwd(path.resolve(this._signingConfig.material.storeFile, ".."), ...)
// -> reads <that dir>/material/{fd,ce,ac}
```

So `storeFile` must stay inside `config/`, with `config/material/` beside it.
Flattening the archive, or copying just the `.p12` somewhere tidy, produces a
signing failure that blames the password rather than the layout.

## Step 4 — how the config reaches hvigor

Nothing secret is committed. `support/openharmony/hvigorfile.ts` reads
`$SERVO_OHOS_SIGNING_CONFIG` in `afterNodeEvaluate`, resolves the three material
paths relative to that file, and assigns the array onto the build profile:

```ts
const signingConfigsPath = process.env["SERVO_OHOS_SIGNING_CONFIG"];
...
buildProfileOpt['app']['signingConfigs'] = signingConfigs;
```

`ports/arkweb/test-app/hvigorfile.ts` does the same, reading
`$ARKWEB_TEST_SIGNING_CONFIG` — separate because the two apps have different
bundle names and therefore different material. Without it the test app falls
back to the public OpenHarmony debug keys checked in under `test-app/signing/`,
which are fine on an OpenHarmony board and useless on a HarmonyOS phone.

Picking the config at build time:

```shell
./mach package --ohos --flavor=default     # signingConfig "default", OpenHarmony board
./mach package --ohos --flavor=harmonyos   # signingConfig "hos", HarmonyOS phone
```

## Failure modes

| Symptom | Cause |
|---|---|
| install fails on a *new* phone with material that works on an old one | the debug profile's device allowlist — regenerate with the new device attached |
| `Signing config not found in enviroment. hvigor will fallback to build-profile.json5.` | `SERVO_OHOS_SIGNING_CONFIG` unset — this is hvigorfile's own message, and the build then produces an unsigned HAP |
| password / decipher error during `signHap` | `storeFile` not next to `material/`, or only half the material was copied |
| `SignHap` rejects the password | the config has a *plaintext* password; hvigor expects the DevEco-encrypted form |
| install fails with a signature or bundle error | material generated for a different bundle name |
| `license not accepted` | `compatibleSdkVersion` / `compileSdkVersion` pinned below the installed SDK, not a signing problem at all |
