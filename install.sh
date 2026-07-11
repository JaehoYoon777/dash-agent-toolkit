#!/usr/bin/env bash
# Install every toolkit skill user-level: skills/<name> -> ~/.claude/skills/<name>.
# Mirrors each skill (rsync -a --delete; cp -r fallback wipes dest first) so
# updates AND deletions propagate. Idempotent -- re-run after every `git pull`.
set -eu

repo_root="$(cd "$(dirname "$0")" && pwd)"
src="$repo_root/skills"
dst_root="${HOME}/.claude/skills"

if [ ! -d "$src" ]; then
    echo "error: skills/ not found next to install.sh (expected $src). Run from a full clone." >&2
    exit 1
fi

mkdir -p "$dst_root"

count=0
for skill_dir in "$src"/*/; do
    [ -d "$skill_dir" ] || continue
    name="$(basename "$skill_dir")"
    dst="$dst_root/$name"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a --delete --exclude='__pycache__/' --exclude='*.pyc' "$skill_dir" "$dst/"
    else
        rm -rf "$dst"
        cp -r "$skill_dir" "$dst"
        find "$dst" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
        find "$dst" -type f -name '*.pyc' -delete 2>/dev/null || true
    fi
    echo "installed: $name -> $dst"
    count=$((count + 1))
done

if [ "$count" -eq 0 ]; then
    echo "error: no skill directories under $src" >&2
    exit 1
fi

echo "done: $count skill(s) in $dst_root -- Claude Code discovers them in every repo."
