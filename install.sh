#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
skills_dir="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}"

install_skill() {
    local name="$1"
    local src="$repo_dir/$name"
    local dst="$skills_dir/$name"

    if [[ ! -d "$src" ]]; then
        echo "error: source skill not found: $src" >&2
        return 1
    fi
    if [[ ! -f "$src/SKILL.md" ]]; then
        echo "error: $src has no SKILL.md" >&2
        return 1
    fi

    mkdir -p "$skills_dir"

    if [[ -L "$dst" ]]; then
        local current
        current="$(readlink "$dst")"
        if [[ "$current" == "$src" ]]; then
            echo "ok: $name already linked"
            return 0
        fi
        echo "updating symlink: $dst -> $src (was $current)"
        rm "$dst"
    elif [[ -e "$dst" ]]; then
        echo "error: $dst exists and is not a symlink; refusing to overwrite" >&2
        return 1
    fi

    ln -s "$src" "$dst"
    echo "installed: $name -> $dst"
}

install_skill hdc
install_skill ohos-performance-testing
install_skill ohos-rust
install_skill ohos-uitest
install_skill servo
install_skill unsafe-rust-soundness
install_skill whatwg-spec
