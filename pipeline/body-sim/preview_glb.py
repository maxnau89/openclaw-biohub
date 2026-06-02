"""Render a quick PNG preview of a GLB file using Blender headless.

    blender --background --python preview_glb.py -- --in male-base.glb --out male.png
"""
from __future__ import annotations

import argparse
import math
import sys

import bpy  # type: ignore
from mathutils import Vector  # type: ignore


def parse_args(argv: list[str]) -> argparse.Namespace:
    if '--' in argv:
        argv = argv[argv.index('--') + 1:]
    else:
        argv = []
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='inp', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--res', type=int, default=600)
    return p.parse_args(argv)


def main() -> int:
    args = parse_args(sys.argv)

    # Clear default scene
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Import GLB
    bpy.ops.import_scene.gltf(filepath=args.inp)

    # Find the mesh
    mesh_obj = next((o for o in bpy.context.scene.objects if o.type == 'MESH'), None)
    if not mesh_obj:
        print('error: no mesh in GLB', file=sys.stderr)
        return 1

    # Camera: front-on, eye-level. Blender world is Z-up.
    cam_data = bpy.data.cameras.new('Cam')
    cam_data.lens = 50
    cam = bpy.data.objects.new('Cam', cam_data)
    bpy.context.scene.collection.objects.link(cam)
    cam_pos = Vector((0.0, -4.0, 0.95))  # 4 m in front (–Y), eye-level
    look_at = Vector((0.0, 0.0, 0.95))
    cam.location = cam_pos
    direction = (look_at - cam_pos).normalized()
    cam.rotation_euler = direction.to_track_quat('-Z', 'Y').to_euler()
    bpy.context.scene.camera = cam

    # Three-point light (Z-up coords: X=lateral, Y=front/back, Z=up)
    for x, y, z, energy, name in [
        (3, -3, 2.5, 700, 'Key'),
        (-3, -2, 2.0, 300, 'Fill'),
        (0, 3, 2.5, 250, 'Rim'),
    ]:
        ld = bpy.data.lights.new(name=name, type='POINT')
        ld.energy = energy
        lo = bpy.data.objects.new(name, ld)
        lo.location = (x, y, z)
        bpy.context.scene.collection.objects.link(lo)

    # Skin tone material
    mat = bpy.data.materials.new('Skin')
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get('Principled BSDF')
    if bsdf:
        bsdf.inputs['Base Color'].default_value = (0.86, 0.65, 0.55, 1.0)
        if 'Roughness' in bsdf.inputs:
            bsdf.inputs['Roughness'].default_value = 0.55
    if mesh_obj.data.materials:
        mesh_obj.data.materials[0] = mat
    else:
        mesh_obj.data.materials.append(mat)

    # Render config
    sc = bpy.context.scene
    sc.render.engine = 'BLENDER_EEVEE'
    sc.render.image_settings.file_format = 'PNG'
    sc.render.resolution_x = args.res
    sc.render.resolution_y = int(args.res * 1.4)  # portrait
    sc.render.resolution_percentage = 100
    sc.render.filepath = args.out

    # Floor disc for grounding
    bpy.ops.mesh.primitive_plane_add(size=4, location=(0, 0, 0))
    floor = bpy.context.active_object
    floor_mat = bpy.data.materials.new('Floor')
    floor_mat.use_nodes = True
    floor_bsdf = floor_mat.node_tree.nodes.get('Principled BSDF')
    if floor_bsdf:
        floor_bsdf.inputs['Base Color'].default_value = (0.08, 0.10, 0.13, 1.0)
        if 'Roughness' in floor_bsdf.inputs:
            floor_bsdf.inputs['Roughness'].default_value = 0.95
    floor.data.materials.append(floor_mat)

    bpy.ops.render.render(write_still=True)
    print(f'wrote {args.out}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
