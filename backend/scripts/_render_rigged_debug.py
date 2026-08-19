"""Renderiza vistas frontal y lateral de un GLB ya rigged por
build_armature.py — Armature real + malla parenteada con auto-weight —
en pose por defecto, para inspección visual del Módulo 2 (skinning en
bruto).

A diferencia de _render_armature_debug.py (que construye un Armature de
depuración desde un JSON de esqueleto, sobre una malla SIN riggear), este
script no calcula nada: se limita a importar un GLB que build_armature.py
ya dejó con Armature + skin reales, y solo añade la visualización auxiliar
de huesos + malla semi-transparente para que el render final los muestre
(misma técnica y misma razón que _render_armature_debug.py — ver su
docstring para la explicación completa de por qué hace falta geometría
auxiliar en vez de confiar en el `display_type` del Armature).

Uso:
    blender --background --python backend/scripts/_render_rigged_debug.py -- \\
        samples/_debug/cow_rigged.glb samples/_debug cow_rigged
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy
import mathutils

args = sys.argv[sys.argv.index("--") + 1:]
if len(args) != 3:
    print(
        "Uso: blender --background --python _render_rigged_debug.py -- "
        "<modelo_rigged.glb> <dir_salida> <prefijo_nombre>"
    )
    sys.exit(1)

glb_path, out_dir_arg, name_prefix = args
out_dir = Path(out_dir_arg)
out_dir.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_path)

armature_objs = [o for o in bpy.data.objects if o.type == "ARMATURE"]
if not armature_objs:
    raise RuntimeError(f"{glb_path}: no se encontró ningún objeto ARMATURE tras importar")
armature_obj = armature_objs[0]
armature_obj.data.display_type = "OCTAHEDRAL"
armature_obj.show_in_front = True

# Posiciones mundo de cada hueso (head/tail), leídas directamente del
# Armature ya presente en el GLB — no hace falta recalcular nada.
bone_segments: list[tuple[mathutils.Vector, mathutils.Vector]] = []
for bone in armature_obj.data.bones:
    head_world = armature_obj.matrix_world @ bone.head_local
    tail_world = armature_obj.matrix_world @ bone.tail_local
    bone_segments.append((head_world, tail_world))

# --- Malla(s) semi-transparente(s) (misma técnica que
# _render_armature_debug.py, misma razón: los huesos siguen el eje medial
# interno de la malla y quedarían ocultos con la malla opaca; los
# materiales originales de estos samples renderizan negro puro incluso
# opacos, así que se sustituyen por uno propio en vez de solo bajar su
# alpha) — se excluye el widget de pose ("Icosphere"/custom_shape) del
# filtro, igual que en inspect_glb.py desde el Módulo 0.
bone_widget_objects = {
    pose_bone.custom_shape
    for pose_bone in armature_obj.pose.bones
    if pose_bone.custom_shape is not None
}

debug_material = bpy.data.materials.new(name="DebugBodyMaterial")
debug_material.use_nodes = True
debug_material.surface_render_method = "BLENDED"
debug_bsdf = debug_material.node_tree.nodes.get("Principled BSDF")
debug_bsdf.inputs["Base Color"].default_value = (0.6, 0.6, 0.6, 1.0)
debug_bsdf.inputs["Alpha"].default_value = 0.25

mesh_objects = []
for obj in bpy.data.objects:
    if obj.type != "MESH" or obj in bone_widget_objects:
        continue
    obj.data.materials.clear()
    obj.data.materials.append(debug_material)
    mesh_objects.append(obj)

# --- Geometría auxiliar SOLO para que los huesos aparezcan en el render
# final (bpy.ops.render.render no incluye el display del Armature) ---
bone_material = bpy.data.materials.new(name="BoneDebugMaterial")
bone_material.use_nodes = True
emission = bone_material.node_tree.nodes.new("ShaderNodeEmission")
emission.inputs["Color"].default_value = (1.0, 0.15, 0.15, 1.0)
emission.inputs["Strength"].default_value = 2.0
output_node = bone_material.node_tree.nodes["Material Output"]
bone_material.node_tree.links.new(emission.outputs["Emission"], output_node.inputs["Surface"])

bone_visuals = bpy.data.collections.new("BoneVisuals")
bpy.context.scene.collection.children.link(bone_visuals)

for head, tail in bone_segments:
    direction = tail - head
    length = direction.length
    if length < 1e-6:
        continue

    bpy.ops.mesh.primitive_cone_add(
        radius1=max(length * 0.08, 0.005), radius2=0.0, depth=length, location=(0, 0, 0)
    )
    cone = bpy.context.active_object
    cone.rotation_mode = "QUATERNION"
    cone.rotation_quaternion = direction.to_track_quat("Z", "Y")
    cone.location = head + direction * 0.5
    cone.data.materials.append(bone_material)

    for collection in list(cone.users_collection):
        collection.objects.unlink(cone)
    bone_visuals.objects.link(cone)

# --- Luz + cámaras (frontal y lateral), encuadrando el esqueleto ---
bpy.ops.object.light_add(type="SUN", location=(2, -3, 5))
bpy.context.active_object.data.energy = 3.0

all_points = [p for segment in bone_segments for p in segment]
xs = [p.x for p in all_points]
ys = [p.y for p in all_points]
zs = [p.z for p in all_points]
center = mathutils.Vector(
    ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
)
size = max(max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
distance = size * 2.2


def make_camera(name: str, location: mathutils.Vector) -> "bpy.types.Object":
    cam_data = bpy.data.cameras.new(name)
    cam_obj = bpy.data.objects.new(name, cam_data)
    bpy.context.collection.objects.link(cam_obj)
    cam_obj.location = location
    direction = center - location
    cam_obj.rotation_mode = "QUATERNION"
    cam_obj.rotation_quaternion = direction.to_track_quat("-Z", "Y")
    return cam_obj


front_camera = make_camera("FrontCamera", center + mathutils.Vector((0, -distance, 0)))
side_camera = make_camera("SideCamera", center + mathutils.Vector((distance, 0, 0)))

scene = bpy.context.scene
scene.render.engine = "BLENDER_EEVEE_NEXT"
scene.render.resolution_x = 1024
scene.render.resolution_y = 1024
scene.render.image_settings.file_format = "PNG"

for camera_obj, view_name in [(front_camera, "front"), (side_camera, "side")]:
    scene.camera = camera_obj
    out_path = out_dir / f"{name_prefix}_{view_name}.png"
    scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)
    print(f"Render guardado: {out_path}")
