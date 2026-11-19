#!/bin/bash
# Empaqueta su_mcp_bridge.rb como .rbz (zip) para Extension Manager
set -e
cd "$(dirname "$0")"
mkdir -p dist
rm -f dist/su_mcp_bridge.rbz
# rbz es un zip con el .rb en root y/o carpeta
# Estructura mínima: su_mcp_bridge.rb
cd sketchup_plugin
zip -r ../dist/su_mcp_bridge.rbz su_mcp_bridge.rb
cd ..
echo "RBZ creado: dist/su_mcp_bridge.rbz ($(du -h dist/su_mcp_bridge.rbz | cut -f1))"
unzip -l dist/su_mcp_bridge.rbz
