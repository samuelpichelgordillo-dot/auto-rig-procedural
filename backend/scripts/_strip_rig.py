"""Elimina armature/skin/animaciones de un modelo, dejando solo malla + materiales.

Uso, para descartar el rig de un modelo descargado (p.ej. un pack CC0 de
Quaternius que viene con armature/animaciones) y quedarnos con una malla
"limpia" apta para que nuestro propio pipeline de auto-rigging (Módulo 1)
genere el esqueleto desde cero. Acepta como entrada GLB/glTF o FBX (los
packs de Quaternius no siempre incluyen GLB, solo FBX/OBJ/blend):

    blender --background --python backend/scripts/_strip_rig.py -- \\
        samples/_original/Cow.fbx samples/cow_unrigged.glb

No forma parte del pipeline final (es una utilidad de preparación de
samples/, igual que _generate_sample_glb.py); no se ejecuta desde
inspect_glb.py ni desde el backend.
"""
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
if len(args) != 2:
    print("Uso: blender --background --python _strip_rig.py -- <entrada.glb|.fbx> <salida.glb>")
    sys.exit(1)

in_path, out_path = args

bpy.ops.wm.read_factory_settings(use_empty=True)

suffix = Path(in_path).suffix.lower()
if suffix == ".fbx":
    bpy.ops.import_scene.fbx(filepath=in_path)
elif suffix in (".glb", ".gltf"):
    bpy.ops.import_scene.gltf(filepath=in_path)
else:
    print(f"Formato de entrada no soportado: {suffix}")
    sys.exit(1)

# 1. Quitar cualquier animación (acciones, drivers) para que no se exporte
#    ningún AnimationClip/AnimationSampler.
for obj in bpy.data.objects:
    obj.animation_data_clear()
for action in list(bpy.data.actions):
    bpy.data.actions.remove(action)

mesh_objects = [o for o in bpy.data.objects if o.type == "MESH"]
armature_objects = [o for o in bpy.data.objects if o.type == "ARMATURE"]

# 2. Quitar modifiers de tipo ARMATURE y vertex groups (pesos de skinning)
#    de cada malla, y desvincular su parent si es el armature.
for mesh_obj in mesh_objects:
    for modifier in [m for m in mesh_obj.modifiers if m.type == "ARMATURE"]:
        mesh_obj.modifiers.remove(modifier)
    for group in list(mesh_obj.vertex_groups):
        mesh_obj.vertex_groups.remove(group)
    if mesh_obj.parent is not None and mesh_obj.parent.type == "ARMATURE":
        matrix_world = mesh_obj.matrix_world.copy()
        mesh_obj.parent = None
        mesh_obj.matrix_world = matrix_world

# 3. Eliminar los objetos ARMATURE (incluye los widgets de pose_bone.custom_shape,
#    que son objetos MESH separados: se listan explícitamente para no dejarlos huérfanos).
bone_widget_objects = {
    pb.custom_shape
    for armature in armature_objects
    for pb in armature.pose.bones
    if pb.custom_shape is not None
}
for widget in bone_widget_objects:
    bpy.data.objects.remove(widget, do_unlink=True)
for armature_obj in armature_objects:
    bpy.data.objects.remove(armature_obj, do_unlink=True)
for armature_data in list(bpy.data.armatures):
    bpy.data.armatures.remove(armature_data)

bpy.ops.export_scene.gltf(filepath=out_path, export_format="GLB")
print(f"Generado (sin rig): {out_path}")
