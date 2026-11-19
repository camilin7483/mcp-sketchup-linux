#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' 'Uso: ./install_sketchup_arch.sh [ruta/al/instalador.exe]' \
    'Prepara el puente local y abre SketchUp Make 2017 con Wine.' \
    'WINEPREFIX y SKETCHUP_EXE permiten seleccionar otra instalación.'
}

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  usage
  exit 0
fi
if (( $# > 1 )); then
  usage >&2
  exit 2
fi
if ! command -v wine >/dev/null; then
  printf '%s\n' 'Instala Wine con el gestor de paquetes de tu distribución.' >&2
  exit 1
fi
export WINEPREFIX="${WINEPREFIX:-$HOME/.local/share/wineprefixes/sketchup}"
export WINEARCH=win64
if (( $# == 1 )); then
  if [[ ! -f $1 ]]; then
    printf '%s\n' 'Indica un instalador de SketchUp válido.' >&2
    exit 1
  fi
  mkdir -p "$(dirname "$WINEPREFIX")"
  wine "$(realpath -- "$1")"
fi

app="${SKETCHUP_EXE:-$WINEPREFIX/drive_c/Program Files/SketchUp/SketchUp 2017/SketchUp.exe}"
if [[ ! -f $app ]]; then
  printf '%s\n' 'SketchUp Make 2017 no aparece en el prefijo. Pasa la ruta de su instalador o configura SKETCHUP_EXE.' >&2
  exit 1
fi

source_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugin_dir="$(dirname "$app")/Plugins"
bridge="$plugin_dir/su_mcp_bridge.rb"
if [[ -e $bridge ]] && ! cmp -s "$bridge" "$source_dir/sketchup_plugin/su_mcp_bridge.rb"; then
  printf '%s\n' 'Ya existe una versión distinta del puente en Plugins. Haz una copia antes de sustituirla.' >&2
  exit 1
fi
if [[ ! -e $bridge ]]; then
  install -D -m 0644 "$source_dir/sketchup_plugin/su_mcp_bridge.rb" "$bridge"
fi
exec wine "$app"
