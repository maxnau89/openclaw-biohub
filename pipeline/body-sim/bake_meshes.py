"""Bake the male + female base GLB meshes for biohub's 3D body simulator.

Runs inside Blender:

    blender --background --python pipeline/body-sim/bake_meshes.py \
        -- --sex male --out dashboard/public/body-sim/male-base.glb

Inputs are pulled from a local `make-human-data/` cache populated by
the sister script `fetch_mh_data.sh` (downloads the CC0 base.obj and
the caucasian-young targets from the makehumancommunity/makehuman
repo on GitHub). See `pipeline/body-sim/README.md`.

The script:
  1. Imports the neutral MakeHuman base.obj (CC0), keeping only the
     `body` group (skipping the 250+ skeleton-joint helper meshes).
  2. Applies the caucasian-{sex}-young target (CC0) as the base shape.
  3. Adds eight GLB morph targets driven by FFMI and BF% at runtime —
     the full MakeHuman muscle×weight macro grid:
       - muscle_high / muscle_low — axis deltas from
         `universal-{sex}-young-{max|min}muscle-averageweight`
       - weight_high / weight_low — axis deltas from
         `universal-{sex}-young-averagemuscle-{max|min}weight`
       - muscle_{high|low}_weight_{high|low} — the four CORNER deltas
         from `universal-{sex}-young-{max|min}muscle-{max|min}weight`
     All deltas are computed relative to
     `universal-{sex}-young-averagemuscle-averageweight` so the
     base shape is the canonical center of the MakeHuman macro grid.

     The corners are essential: MakeHuman composes macros by bilinear
     interpolation over the grid, and a corner shape is NOT the sum of
     its two axis extremes (measured error: 60–138 % of the deformation
     magnitude — the source of surface rippling when the runtime added
     muscle_high + weight_high for strongly-modified bodies). The
     runtime reproduces MakeHuman's interpolation exactly by weighting
     each grid morph with the product of per-axis hat functions.
  4. Recomputes normals + smooth-shades.
  5. Decimates to a manageable triangle count.
  6. Normalizes height to 1.75 m and uprights the mesh (Z-up in
     Blender, which exports to Y-up in GLB).
  7. Exports as GLB with `export_morph=True` so Three.js can blend
     the morph targets via `mesh.morphTargetInfluences[]`.

Landmark vertex groups for the 7 Jackson-Pollock caliper sites are
NOT baked into the GLB — Blender's glTF exporter strips vertex groups
unless they're tied to an armature. Instead, the runtime
`MeshDeformer.ts` computes landmark-to-vertex weights at load time
from the same anatomical Y-fractions + side filters that this script
used to bake. This keeps the GLB minimal (POSITION + NORMAL only).

No external Python packages required (only Blender's bundled `bpy`).
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import bpy  # type: ignore  # available inside Blender
import bmesh  # type: ignore
from mathutils import Matrix, Vector  # type: ignore


TARGET_HEIGHT_M = 1.75   # final mesh height after scale
DECIMATE_RATIO = 0.5     # ~half the original tri count


# ─── Argument parsing ────────────────────────────────────────────────────────

def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse argv after the `--` Blender separator."""
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument('--sex', choices=['male', 'female'], required=True)
    p.add_argument('--out', required=True, help='Output GLB path')
    p.add_argument(
        '--data-dir',
        default=str(Path.home() / '.cache/biohub-body-sim'),
        help='Directory containing base.obj + male.target + female.target',
    )
    return p.parse_args(argv)


# ─── MakeHuman target parsing ───────────────────────────────────────────────

def parse_target_file(path: Path) -> dict[int, tuple[float, float, float]]:
    """Parse a MakeHuman .target file (text format).

    Lines starting with `#` or empty are skipped. Data lines are:
        <vertex_index> <dx> <dy> <dz>
    in MakeHuman's unit system (decimeters, Y-up).

    Returns: { vertex_index: (dx, dy, dz) }
    """
    out: dict[int, tuple[float, float, float]] = {}
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln or ln.startswith('#'):
                continue
            parts = ln.split()
            if len(parts) != 4:
                continue
            try:
                idx = int(parts[0])
                dx, dy, dz = float(parts[1]), float(parts[2]), float(parts[3])
                out[idx] = (dx, dy, dz)
            except ValueError:
                continue
    return out


# ─── Main pipeline ───────────────────────────────────────────────────────────

def clear_scene() -> None:
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()


def parse_obj_body_group(obj_path: Path) -> tuple[list[tuple[float, float, float]], list[list[int]]]:
    """Parse a MakeHuman base.obj, keeping only faces in the `body` group.

    Returns:
      - vertices: list of (x, y, z), using the OBJ's global vertex indices
        (0-based). Indices NOT referenced by any body face will remain in
        the list as orphan vertices; we strip them in a follow-up pass.
      - faces: list of lists of vertex indices (0-based).

    MakeHuman's base.obj is a single OBJ file with ~250 `g <name>` blocks
    (`body`, `helper-tights`, `joint-pelvis`, `joint-l-eye`, etc.). We only
    care about `body`. We need to keep the original global vertex indices
    because the morph target files reference them.
    """
    vertices: list[tuple[float, float, float]] = []
    faces: list[list[int]] = []
    current_group: str | None = None

    with open(obj_path) as f:
        for ln in f:
            if not ln or ln.startswith('#'):
                continue
            parts = ln.split()
            if not parts:
                continue
            tag = parts[0]
            if tag == 'v':
                vertices.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif tag == 'g':
                current_group = parts[1] if len(parts) > 1 else ''
            elif tag == 'f' and current_group == 'body':
                # OBJ face indices are 1-based and may have v/vt/vn slashes.
                face = [int(p.split('/')[0]) - 1 for p in parts[1:]]
                faces.append(face)
    return vertices, faces


def build_body_mesh(
    obj_path: Path,
    target_offsets: dict[int, tuple[float, float, float]],
):
    """Parse the OBJ, apply target offsets, build a Blender mesh
    containing only the `body` group faces with vertices remapped to
    a compact 0..N indexing. Returns the new mesh object plus a
    dict mapping original global vertex indices to the new compact
    indices — needed so callers can map macro-target deltas onto
    shape keys after the fact."""
    raw_verts, body_faces = parse_obj_body_group(obj_path)
    print(f'  parsed OBJ: {len(raw_verts)} global verts, '
          f'{len(body_faces)} body faces')

    # Apply target offsets in original indexing
    morphed: list[list[float]] = [[x, y, z] for x, y, z in raw_verts]
    applied = 0
    for idx, (dx, dy, dz) in target_offsets.items():
        if idx < len(morphed):
            morphed[idx][0] += dx
            morphed[idx][1] += dy
            morphed[idx][2] += dz
            applied += 1
    print(f'  applied {applied}/{len(target_offsets)} target offsets')

    # Collect only vertices referenced by body faces
    referenced = sorted({v for face in body_faces for v in face})
    new_idx = {old: new for new, old in enumerate(referenced)}
    compact_verts = [tuple(morphed[i]) for i in referenced]
    compact_faces = [[new_idx[v] for v in face] for face in body_faces]
    print(f'  body subset: {len(compact_verts)} verts, '
          f'{len(compact_faces)} faces')

    # Build a Blender mesh
    mesh = bpy.data.meshes.new('body')
    mesh.from_pydata(compact_verts, [], compact_faces)
    mesh.update()
    obj = bpy.data.objects.new('body', mesh)
    bpy.context.scene.collection.objects.link(obj)

    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    return obj, new_idx


def add_morph_target(
    obj,
    name: str,
    delta_global: dict[int, tuple[float, float, float]],
    new_idx: dict[int, int],
) -> None:
    """Attach a morph target (Blender shape key) to `obj`.

    `delta_global` is keyed by ORIGINAL global MakeHuman vertex indices
    (the same numbering the .target files use). `new_idx` is the map
    from those global indices to the compact 0..N indices that survived
    `build_body_mesh`'s body-group filter.

    Blender shape keys store *absolute* vertex positions, so we add the
    delta on top of the Basis position. The exporter then writes the
    morph target as a relative delta in glTF.
    """
    # First call lazily creates the Basis shape key (same positions as
    # the rest pose). Subsequent calls create named shape keys that
    # start out as copies of Basis and which we mutate below.
    if obj.data.shape_keys is None:
        obj.shape_key_add(name='Basis')
    sk = obj.shape_key_add(name=name)
    sk.value = 0.0  # influence is set by the runtime; bake-time = neutral
    n_applied = 0
    for g_idx, (dx, dy, dz) in delta_global.items():
        if g_idx not in new_idx:
            continue   # vertex isn't in the `body` subset (e.g. eye/joint helpers)
        i = new_idx[g_idx]
        co = sk.data[i].co
        sk.data[i].co = (co.x + dx, co.y + dy, co.z + dz)
        n_applied += 1
    print(f'    morph {name!r}: {n_applied} delta vertices')


def compute_bipolar_delta(
    pole: dict[int, tuple[float, float, float]],
    center: dict[int, tuple[float, float, float]],
) -> dict[int, tuple[float, float, float]]:
    """Returns `pole − center` per vertex index. Both inputs are sparse
    dicts (only listed vertex indices have a delta from the OBJ base)."""
    keys = set(pole.keys()) | set(center.keys())
    out: dict[int, tuple[float, float, float]] = {}
    for k in keys:
        px, py, pz = pole.get(k, (0.0, 0.0, 0.0))
        cx, cy, cz = center.get(k, (0.0, 0.0, 0.0))
        dx, dy, dz = px - cx, py - cy, pz - cz
        # Skip near-zero deltas so the shape-key data stays sparse and the
        # GLB stays small.
        if abs(dx) + abs(dy) + abs(dz) > 1e-5:
            out[k] = (dx, dy, dz)
    return out


def smooth_shade(obj) -> None:
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.shade_smooth()
    # Recompute normals consistently outward
    mesh = obj.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()


def decimate(obj, ratio: float) -> None:
    bpy.context.view_layer.objects.active = obj
    mod = obj.modifiers.new(name='Decimate', type='DECIMATE')
    mod.ratio = ratio
    bpy.ops.object.modifier_apply(modifier=mod.name)


def normalize_and_upright(obj) -> None:
    """Translate so feet at Y=0, scale to TARGET_HEIGHT_M, then rotate
    +90° about X so the body stands upright in Blender's Z-up world
    (head at +Z, feet at Z=0). After GLB export with `export_yup=True`,
    Blender converts back to Y-up — head at +Y in the final GLB.

    Uses object-level transform + transform_apply so Blender propagates
    the same TRS through every shape key automatically. Mutating
    `obj.data.vertices` in-place would skip the shape keys and produce
    wildly wrong morph deltas in the exported GLB.
    """
    mesh = obj.data
    ys = [v.co.y for v in mesh.vertices]
    y_min, y_max = min(ys), max(ys)
    h = y_max - y_min
    s = TARGET_HEIGHT_M / h
    # Transform order in Blender's transform_apply: scale, then rotate,
    # then translate. The MakeHuman OBJ's anatomical-up was +Y; after the
    # +π/2 X rotation, that becomes +Z. So the *translation* to put feet
    # at Z=0 has to be in Z, not Y.
    obj.scale = (s, s, s)
    obj.rotation_euler = (math.pi / 2, 0.0, 0.0)
    obj.location = (0.0, 0.0, -y_min * s)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def export_glb(obj, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    # `export_apply=False` is required when shape keys are present, otherwise
    # Blender refuses to bake the modifiers (and decimate isn't in use here
    # anyway). Morph normals stay computed so the GPU re-shades cleanly when
    # the runtime blends targets.
    has_morphs = obj.data.shape_keys is not None
    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format='GLB',
        use_selection=True,
        export_apply=not has_morphs,
        export_yup=True,
        export_morph=has_morphs,
        export_morph_normal=has_morphs,
        export_attributes=True,
    )


def main() -> int:
    args = parse_args(sys.argv)
    data_dir = Path(args.data_dir).expanduser()
    base_obj = data_dir / 'base.obj'
    target_file = data_dir / f'{args.sex}.target'
    if not base_obj.exists():
        print(f'error: base.obj not found at {base_obj}', file=sys.stderr)
        return 1
    if not target_file.exists():
        print(f'error: target file not found at {target_file}', file=sys.stderr)
        return 1

    print(f'biohub body-sim bake — sex={args.sex} → {args.out}')

    clear_scene()
    offsets = parse_target_file(target_file)
    print(f'  parsed {len(offsets)} vertex offsets from {target_file.name}')

    obj, new_idx = build_body_mesh(base_obj, offsets)

    # ── Morph targets: full muscle×weight macro grid ─────────────────────
    # All 9 macro target files have the same vertex domain as base.obj. We
    # express each of the 8 non-center grid points as a delta from the
    # canonical center (avgmuscle-avgweight). The runtime weights each
    # morph with the product of per-axis hat functions (MakeHuman's own
    # bilinear composition) — the hat weights always sum to ≤ 1, so no
    # morph ever extrapolates beyond its baked shape.
    macro_paths = {
        'center':       data_dir / f'{args.sex}-averagemuscle-averageweight.target',
        'muscle_high':  data_dir / f'{args.sex}-maxmuscle-averageweight.target',
        'muscle_low':   data_dir / f'{args.sex}-minmuscle-averageweight.target',
        'weight_high':  data_dir / f'{args.sex}-averagemuscle-maxweight.target',
        'weight_low':   data_dir / f'{args.sex}-averagemuscle-minweight.target',
        'muscle_high_weight_high': data_dir / f'{args.sex}-maxmuscle-maxweight.target',
        'muscle_high_weight_low':  data_dir / f'{args.sex}-maxmuscle-minweight.target',
        'muscle_low_weight_high':  data_dir / f'{args.sex}-minmuscle-maxweight.target',
        'muscle_low_weight_low':   data_dir / f'{args.sex}-minmuscle-minweight.target',
    }
    macros = {}
    for name, p in macro_paths.items():
        if not p.exists():
            print(f'  warn: macro target missing — {p.name}; skipping morph {name!r}')
            continue
        macros[name] = parse_target_file(p)
    if 'center' in macros:
        for pole in (
            'muscle_high', 'muscle_low', 'weight_high', 'weight_low',
            'muscle_high_weight_high', 'muscle_high_weight_low',
            'muscle_low_weight_high', 'muscle_low_weight_low',
        ):
            if pole not in macros:
                continue
            delta = compute_bipolar_delta(macros[pole], macros['center'])
            add_morph_target(obj, pole, delta, new_idx)

    # ── Female-only: breast cup volume morphs ────────────────────────────
    # MakeHuman's weight macro covers very little chest tissue, so women
    # don't visibly change breast size as BF% varies. These two extra
    # morphs (sourced from the dedicated `breast/` target dir) get driven
    # by BF % in the dashboard alongside `weight_high` / `weight_low`.
    if args.sex == 'female':
        for pole in ('breast_high', 'breast_low'):
            src_name = 'female-breast-' + ('maxcup' if pole.endswith('high') else 'mincup') + '.target'
            src_path = data_dir / src_name
            if not src_path.exists():
                print(f'  warn: {src_name} missing; skipping {pole!r}')
                continue
            # The breast targets are already deltas from the macro center
            # (averagemuscle-averageweight-averagecup-averagefirmness), so
            # we don't subtract anything — feed them as-is.
            delta = parse_target_file(src_path)
            add_morph_target(obj, pole, delta, new_idx)

    # ── Both sexes: belly morphs (anterior abdominal mass / abs tone) ──
    # MakeHuman's `weight` macro distributes fat uniformly across the
    # body, which doesn't produce a visible belly overhang at high BF or
    # visible abs at low BF. These two extra morphs come from the
    # dedicated `stomach/` target dir and add the missing relief.
    #   belly_high <- stomach-pregnant-incr (anterior abdominal mass)
    #   belly_low  <- stomach-tone-incr (muscle definition / 6-pack)
    for pole, src_file in (
        ('belly_high', 'belly-high.target'),
        ('belly_low',  'belly-low.target'),
    ):
        src_path = data_dir / src_file
        if not src_path.exists():
            print(f'  warn: {src_file} missing; skipping {pole!r}')
            continue
        add_morph_target(obj, pole, parse_target_file(src_path), new_idx)

    smooth_shade(obj)
    # Decimation is skipped — Blender doesn't allow Decimate modifier on
    # meshes with shape keys. The full ~13k-vert body is small enough
    # (<1 MB GLB even with 4 morph targets, since deltas are sparse).

    normalize_and_upright(obj)
    bb = obj.bound_box
    h = max(p[2] for p in bb) - min(p[2] for p in bb)
    print(f'  normalized + upright: height = {h:.3f} m')

    export_glb(obj, Path(args.out))
    print(f'  wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
