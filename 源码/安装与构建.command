#!/bin/bash
set -euo pipefail

source_dir="$(cd "$(dirname "$0")" && pwd)"
project_dir="$(dirname "$source_dir")"
app_dir="$project_dir/AprilTag方块.app"
runtime_dir="$HOME/Library/Application Support/AprilTagCube/runtime"
export PATH="$HOME/.local/bin:$HOME/.local/share/tools/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [[ $# -gt 1 || ($# -eq 1 && "$1" != "--portable") ]]; then
    echo "用法：$0 [--portable]"
    exit 2
fi
portable="${1:-}"

if [[ -n "$portable" ]] || ! "$runtime_dir/bin/python" -c 'import OCP.BRep' >/dev/null 2>&1; then
    if ! command -v uv >/dev/null 2>&1; then
        echo "请先安装 uv，再运行此脚本。"
        exit 1
    fi
    if [[ -z "$portable" ]]; then
        uv venv --python 3.13 "$runtime_dir"
        uv pip install --python "$runtime_dir/bin/python" "cadquery-ocp-novtk==8.0.1.1.0"
    fi
fi

build_dir="$(mktemp -d)"
trap 'rm -rf "$build_dir"' EXIT
build_app="$build_dir/AprilTag方块.app"
contents="$build_app/Contents"
mkdir -p "$contents/MacOS" "$contents/Resources"
MACOSX_DEPLOYMENT_TARGET=14.0 /usr/bin/swiftc -parse-as-library -O -swift-version 5 "$source_dir/App.swift" -o "$contents/MacOS/AprilTagCube"
cp "$source_dir/Info.plist" "$contents/Info.plist"
cp "$source_dir/families.json" "$source_dir/exporter.py" "$source_dir/AprilTag-LICENSE.txt" "$source_dir/AppIcon.icns" "$contents/Resources/"

if [[ -n "$portable" ]]; then
    app_dir="$project_dir/dist/macos/AprilTag方块.app"
    uv python install 3.13.16 --install-dir "$build_dir/python" --no-bin --no-progress
    bundled_runtime="$contents/Resources/runtime"
    /usr/bin/ditto "$build_dir/python/cpython-3.13.16-macos-"*-none "$bundled_runtime"
    uv pip install --python "$bundled_runtime/bin/python3.13" \
        --target "$bundled_runtime/lib/python3.13/site-packages" "cadquery-ocp-novtk==8.0.1.1.0"
    "$bundled_runtime/bin/python3.13" -I -B -c 'import OCP.BRep'
fi

/usr/bin/codesign --force --sign - "$build_app"
/usr/bin/ditto "$build_app" "$app_dir"
echo "已生成 $app_dir"
