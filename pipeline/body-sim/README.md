# Body-sim mesh bake pipeline

biohub's 3D body composition simulator ships two pre-baked base
meshes (`male-base.glb` + `female-base.glb`) under
`dashboard/public/body-sim/`. They're derived from the
[MakeHuman Community](https://github.com/makehumancommunity/makehuman)
neutral base mesh + the `caucasian-{sex}-young` macro target — both
explicitly released as **CC0** by the MakeHuman project in 2020 (see
the headers of `base.obj` and the `.target` files for the full
license text).

## Requirements

Just **Blender 5.x** (we develop against 5.1.2). Install once:

```bash
brew install --cask blender   # macOS
# or: sudo apt install blender  # Linux
```

No MakeHuman install needed — we only consume MakeHuman's CC0 data
files, not its GUI.

## Bake

```bash
# Step 1: fetch the CC0 source files (base.obj + male.target + female.target)
pipeline/body-sim/fetch_mh_data.sh

# Step 2: bake the male + female GLBs
blender --background --python pipeline/body-sim/bake_meshes.py -- \
    --sex male --out dashboard/public/body-sim/male-base.glb
blender --background --python pipeline/body-sim/bake_meshes.py -- \
    --sex female --out dashboard/public/body-sim/female-base.glb
```

Expected output: two `.glb` files, ~240 KB each, ~9 k triangles each,
height = 1.75 m, head at +Y, feet at Y=0.

To preview the meshes after a bake:

```bash
blender --background --python pipeline/body-sim/preview_glb.py -- \
    --in dashboard/public/body-sim/male-base.glb --out /tmp/male-preview.png
```

## What the bake script does

1. Parses `base.obj` and **keeps only the `body` group** — the OBJ
   ships with ~250 helper meshes (`helper-tights`, `joint-pelvis`,
   `joint-l-eye`, etc.) that aren't part of the body and would
   render as a long skirt/spike if we left them in.
2. Applies the `.target` file's per-vertex offsets to produce a
   recognizable male/female silhouette (the MakeHuman macro morph).
3. Smooth-shades, decimates to ~9 k triangles, normalizes the height
   to 1.75 m, and rotates upright so the body stands in Blender's
   Z-up world.
4. Exports as GLB with Y-up orientation (the glTF convention, which
   Three.js consumes directly).

## What the bake script does NOT do

- **No vertex groups in the GLB.** Blender's glTF exporter strips
  vertex groups unless they're tied to an armature. The runtime
  `MeshDeformer.ts` instead computes landmark-to-vertex weights at
  mesh-load time, using the same anatomical Y-fractions + side
  filters this script used to use.
- **No texture / skin shader.** The GLB only carries POSITION +
  NORMAL. The runtime `BodyModel3D.tsx` applies a neutral skin
  material in Three.js. This keeps the GLB minimal (~240 KB).
- **No skeleton / rig.** The body is a static mesh; deformation
  happens via vertex displacement in the runtime, not via skinning.

## License

- `base.obj` and the `.target` files: **CC0** (MakeHuman Community,
  released 2020). The license headers in those files are the
  primary source of truth.
- The Blender bake script and resulting GLBs: **MIT** (this repo's
  license).
