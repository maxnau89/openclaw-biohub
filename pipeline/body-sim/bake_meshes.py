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
  2. Applies the caucasian-{sex}-young target (CC0) as a morph.
  3. Recomputes normals + smooth-shades.
  4. Decimates to a manageable triangle count.
  5. Normalizes height to 1.75 m and uprights the mesh (Z-up in
     Blender, which exports to Y-up in GLB).
  6. Exports as GLB to the requested output path.

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
    a compact 0..N indexing. Returns the new mesh object."""
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
    return obj


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


def normalize_transform(obj) -> None:
    """Pre-orientation: MakeHuman OBJ is Y-up, so we treat the Y axis as
    anatomical height for translation + scale. The follow-up upright()
    step then rotates -90° about X so the body stands up in Blender's
    Z-up world (which becomes Y-up again after GLB export)."""
    mesh = obj.data
    ys = [v.co.y for v in mesh.vertices]
    y_min, y_max = min(ys), max(ys)
    h = y_max - y_min
    s = TARGET_HEIGHT_M / h
    # Translate so feet at Y=0, then uniform scale.
    for v in mesh.vertices:
        v.co.x = v.co.x * s
        v.co.y = (v.co.y - y_min) * s
        v.co.z = v.co.z * s


def upright(obj) -> None:
    """Rotate +90° about X so the body stands upright in Blender's
    Z-up world (head at +Z, feet at Z=0). The MakeHuman OBJ has the
    head at +Y; the +90° X rotation maps +Y → +Z. Bakes the rotation
    into the vertex data so the exported GLB has clean transforms."""
    rot = Matrix.Rotation(math.pi / 2, 4, 'X')
    for v in obj.data.vertices:
        co = rot @ Vector((v.co.x, v.co.y, v.co.z))
        v.co = co


def export_glb(obj, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format='GLB',
        use_selection=True,
        export_apply=True,
        export_yup=True,
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

    obj = build_body_mesh(base_obj, offsets)
    n_groups = len(obj.vertex_groups)
    print(f'  added {n_groups} landmark vertex groups')

    smooth_shade(obj)
    decimate(obj, DECIMATE_RATIO)
    print(f'  decimated to {len(obj.data.polygons)} faces')

    normalize_transform(obj)
    upright(obj)
    h = max(v.co.z for v in obj.data.vertices) - min(v.co.z for v in obj.data.vertices)
    print(f'  normalized + upright: height = {h:.3f} m')

    export_glb(obj, Path(args.out))
    print(f'  wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
