# /// script
# requires-python = ">=3.9"
# dependencies = ["json5"]
# ///
"""Turn DevEco Studio's signing output into a SERVO_OHOS_SIGNING_CONFIG file.

DevEco writes the certificates, profile and keystore under ``<USER HOME>/.ohos/config``
and the matching ``app.signingConfigs`` array -- with absolute Windows paths and encrypted
passwords -- into the project's ``build-profile.json5``. This takes the uploaded pair and
emits a ``signing-configs.json`` whose ``certpath`` / ``profile`` / ``storeFile`` are
relative to the output file, which is what ``hvigorfile.ts`` expects.

Material files are matched by basename against the uploaded directory, so the Windows
paths inside build-profile.json5 do not have to mean anything here.

Run:  uv run install_signing.py --material-dir ohos-config \
          --build-profile build-profile.json5 --out ohos-config/signing-configs.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import json5

MATERIAL_SUBDIRS = ("fd", "ce", "ac")
PATH_KEYS = ("certpath", "profile", "storeFile")


def index_files(root: Path) -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for path in root.rglob("*"):
        if path.is_file():
            index.setdefault(path.name, []).append(path)
    return index


def resolve(name: str, index: dict[str, list[Path]], material_dir: Path) -> Path:
    matches = index.get(name)
    if not matches:
        sys.exit(f"{name}: not found under {material_dir} -- is the .ohos archive complete?")
    if len(matches) > 1:
        sys.exit(f"{name}: ambiguous, {len(matches)} copies under {material_dir}: {matches}")
    return matches[0]


def check_material_layout(store_file: Path) -> None:
    """hvigor decrypts the passwords with key material next to the keystore."""
    material = store_file.parent / "material"
    if not material.is_dir():
        sys.exit(
            f"{material} is missing.\n"
            f"hvigor decrypts the passwords from <dir of storeFile>/material/, so the keystore\n"
            f"has to stay inside the .ohos config directory it was generated in."
        )
    missing = [d for d in MATERIAL_SUBDIRS if not (material / d).is_dir()]
    if missing:
        sys.exit(f"{material}: missing subdirectories {missing}; the archive is incomplete.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--material-dir", required=True, type=Path,
                        help="the unpacked .ohos directory (contains config/ with material/)")
    parser.add_argument("--build-profile", required=True, type=Path,
                        help="build-profile.json5 from the DevEco project, holding app.signingConfigs")
    parser.add_argument("--out", required=True, type=Path, help="signing config file to write")
    args = parser.parse_args()

    profile = json5.loads(args.build_profile.read_text(encoding="utf-8"))
    configs = profile.get("app", {}).get("signingConfigs")
    if not configs:
        sys.exit(f"{args.build_profile} has no app.signingConfigs -- was the signature generated?")

    material_dir = args.material_dir.resolve()
    index = index_files(material_dir)
    out_dir = args.out.resolve().parent

    for config in configs:
        material = config.get("material")
        if not material:
            sys.exit(f"signing config {config.get('name')!r} has no material block")
        for key in PATH_KEYS:
            value = material.get(key)
            if not value:
                sys.exit(f"signing config {config.get('name')!r} has no {key}")
            resolved = resolve(Path(value.replace("\\", "/")).name, index, material_dir)
            if key == "storeFile":
                check_material_layout(resolved)
            material[key] = os.path.relpath(resolved, out_dir)
        for key in ("storePassword", "keyPassword"):
            if len(material.get(key, "")) < 32:
                print(f"warning: {config.get('name')!r} {key} looks like a plaintext password; "
                      f"hvigor expects the DevEco-encrypted form", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(configs, indent=2) + "\n", encoding="utf-8")
    names = ", ".join(repr(c.get("name")) for c in configs)
    print(f"wrote {args.out} with signing config(s): {names}")


if __name__ == "__main__":
    main()
