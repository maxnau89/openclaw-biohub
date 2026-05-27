#!/usr/bin/env bash
#
# Fetch the CC0 MakeHuman base mesh + sex morph targets needed to bake
# biohub's body-sim meshes. Output lands in ~/.cache/biohub-body-sim/
# (or $1 if provided).
#
# All three files were explicitly released as CC0 by the MakeHuman
# community in 2020 — see the license headers in each file.
set -euo pipefail

CACHE="${1:-$HOME/.cache/biohub-body-sim}"
mkdir -p "$CACHE"

BASE='https://raw.githubusercontent.com/makehumancommunity/makehuman/master/makehuman/data'

curl -sSLfo "$CACHE/base.obj"      "$BASE/3dobjs/base.obj"
curl -sSLfo "$CACHE/male.target"   "$BASE/targets/macrodetails/caucasian-male-young.target"
curl -sSLfo "$CACHE/female.target" "$BASE/targets/macrodetails/caucasian-female-young.target"

echo "Cached MakeHuman data:"
ls -lh "$CACHE/"
