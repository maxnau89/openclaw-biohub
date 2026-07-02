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

# Macro targets: the FULL 3×3 muscle×weight grid at young age.
# MakeHuman composes macro shapes by bilinear interpolation over this grid —
# the corner targets (e.g. maxmuscle-maxweight) are NOT the sum of the two
# axis extremes (measured error: 60–138 % of the deformation magnitude).
# We bake all 8 non-center grid points as morph targets so the dashboard can
# reproduce MakeHuman's exact interpolation from the user's FFMI and BF%.
TARGETS="$BASE/targets/macrodetails"
for sex in male female; do
  for axis in averagemuscle-averageweight \
              maxmuscle-averageweight     minmuscle-averageweight \
              averagemuscle-maxweight     averagemuscle-minweight \
              maxmuscle-maxweight         maxmuscle-minweight \
              minmuscle-maxweight         minmuscle-minweight; do
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

# Both sexes: abdominal "belly" morphs to give MakeHuman's weight macro
# (which is uniform body-fat distribution) something resembling a real
# belly overhang at high BF and visible abdominal-tone lines at low BF.
# pregnant-incr is the source of anterior abdominal mass; tone-incr adds
# the muscle-relief lines.
STOMACH="$BASE/targets/stomach"
curl -sSLfo "$CACHE/belly-high.target" "$STOMACH/stomach-pregnant-incr.target"
curl -sSLfo "$CACHE/belly-low.target"  "$STOMACH/stomach-tone-incr.target"

echo "Cached MakeHuman data:"
ls -lh "$CACHE/"
