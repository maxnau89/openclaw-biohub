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

# Macro targets for muscle (min/avg/max) and weight (min/avg/max) at young age.
# We bake the deltas between avg-avg and the four corners (muscle±, weight±)
# as morph targets in the GLB so the dashboard can interpolate live based on
# the user's FFMI and BF%.
TARGETS="$BASE/targets/macrodetails"
for sex in male female; do
  for axis in averagemuscle-averageweight \
              maxmuscle-averageweight     minmuscle-averageweight \
              averagemuscle-maxweight     averagemuscle-minweight; do
    curl -sSLfo "$CACHE/${sex}-${axis}.target" \
      "$TARGETS/universal-${sex}-young-${axis}.target"
  done
done

# Female-only: breast cup-size morphs at the macro center
# (averagemuscle-averageweight-averagefirmness). Used to drive breast
# volume from BF% in the dashboard since MakeHuman's `weight` macro
# barely touches chest tissue.
BREAST="$BASE/targets/breast"
for cup in maxcup mincup; do
  curl -sSLfo "$CACHE/female-breast-${cup}.target" \
    "$BREAST/female-young-averagemuscle-averageweight-${cup}-averagefirmness.target"
done

echo "Cached MakeHuman data:"
ls -lh "$CACHE/"
