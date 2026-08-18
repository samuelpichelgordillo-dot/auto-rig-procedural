"""Inspecciona un GLB usando Blender headless.

Uso:
    blender --background --python backend/scripts/inspect_glb.py -- samples/modelo.glb

o, vía el wrapper de Python (invoca a blender como subproceso):
    python backend/scripts/inspect_glb.py samples/modelo.glb
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _run_inside_blender(glb_path: str) -> None:
    """Se ejecuta dentro del intérprete de Blender (bpy disponible)."""
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb_path)

    armature_objects = [o for o in bpy.data.objects if o.type == "ARMATURE"]

    # El importador de glTF de Blender crea, para cada hueso, un objeto MESH
    # auxiliar (p.ej. "Icosphere") usado únicamente como widget visual de pose
    # (pose_bone.custom_shape). No forma parte de la geometría del modelo, así
    # que se excluye de los conteos.
    bone_widget_objects = {
        pb.custom_shape
        for armature in armature_objects
        for pb in armature.pose.bones
        if pb.custom_shape is not None
    }
    mesh_objects = [
        o for o in bpy.data.objects if o.type == "MESH" and o not in bone_widget_objects
    ]

    vertex_count = sum(len(o.data.vertices) for o in mesh_objects)

    bone_names: list[str] = []
    for armature in armature_objects:
        bone_names.extend(bone.name for bone in armature.data.bones)

    min_corner = [float("inf")] * 3
    max_corner = [float("-inf")] * 3
    for obj in mesh_objects:
        for corner in obj.bound_box:
            world_corner = obj.matrix_world @ __import__("mathutils").Vector(corner)
            for i in range(3):
                min_corner[i] = min(min_corner[i], world_corner[i])
                max_corner[i] = max(max_corner[i], world_corner[i])

    material_count = len(bpy.data.materials)

    print("=== inspect_glb.py ===")
    print(f"Archivo: {glb_path}")
    print(f"Vértices: {vertex_count}")
    print(f"Huesos existentes: {len(bone_names)}")
    if bone_names:
        print(f"  Nombres: {', '.join(bone_names)}")
    if mesh_objects:
        print(
            "Bounding box: "
            f"min=({min_corner[0]:.4f}, {min_corner[1]:.4f}, {min_corner[2]:.4f}) "
            f"max=({max_corner[0]:.4f}, {max_corner[1]:.4f}, {max_corner[2]:.4f})"
        )
    else:
        print("Bounding box: sin geometría (no hay objetos MESH)")
    print(f"Materiales: {material_count}")


def _run_as_wrapper(glb_path: str) -> int:
    """Se ejecuta con Python normal: invoca a Blender headless como subproceso."""
    script_path = Path(__file__).resolve()
    blender_exe = "blender"
    cmd = [
        blender_exe,
        "--background",
        "--python",
        str(script_path),
        "--",
        glb_path,
    ]
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    if "--" in sys.argv:
        # Ejecutándose dentro de Blender: los argumentos tras "--" son los nuestros.
        args = sys.argv[sys.argv.index("--") + 1:]
        if not args:
            print("Uso: blender --background --python inspect_glb.py -- <modelo.glb>")
            sys.exit(1)
        _run_inside_blender(args[0])
    else:
        # Ejecutándose con Python normal: reinvocar bajo Blender.
        if len(sys.argv) < 2:
            print("Uso: python inspect_glb.py <modelo.glb>")
            sys.exit(1)
        glb_arg = str(Path(sys.argv[1]).resolve())
        sys.exit(_run_as_wrapper(glb_arg))
