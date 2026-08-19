"""Genera un Armature real en Blender a partir del esqueleto exportado a
JSON (ver _export_skeleton_json.py) y renderiza vistas frontal y lateral
de la malla + huesos superpuestos, para inspección visual (sub-paso 1.4).

Uso:
    blender --background --python backend/scripts/_render_armature_debug.py -- \\
        samples/biped_unrigged.glb /tmp/biped_skeleton.json samples/_debug biped_unrigged

Nota técnica importante: los huesos de un Armature (display 'OCTAHEDRAL',
'STICK', etc.) son un overlay del editor/viewport, no geometría real de la
escena — `bpy.ops.render.render` (el render final, vía EEVEE/Cycles) NO
los incluye en la imagen aunque el Armature exista y tenga el
`display_type` configurado. Esto se comprobó al escribir este script: un
primer render sin geometría auxiliar mostraba solo la malla, sin huesos.

Para que los huesos SÍ aparezcan en el PNG final vía `bpy.ops.render.render`
(tal como se pidió, sin depender de un viewport interactivo ni de
`bpy.ops.render.opengl`, que requiere una ventana real y falla en
--background), este script añade, además del Armature real (que queda
listo para un futuro paso de skinning), geometría auxiliar puramente
visual: un cono fino por hueso con material de emisión, agrupada en su
propia colección (BoneVisuals) para poder excluirla fácilmente de
cualquier uso posterior del Armature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import bpy
import mathutils

args = sys.argv[sys.argv.index("--") + 1:]
if len(args) != 4:
    print(
        "Uso: blender --background --python _render_armature_debug.py -- "
        "<modelo.glb> <esqueleto.json> <dir_salida> <prefijo_nombre>"
    )
    sys.exit(1)

glb_path, json_path, out_dir_arg, name_prefix = args
out_dir = Path(out_dir_arg)
out_dir.mkdir(parents=True, exist_ok=True)

with open(json_path, encoding="utf-8") as f:
    skeleton_data = json.load(f)

node_positions = {int(k): tuple(v) for k, v in skeleton_data["nodes"].items()}
edges = skeleton_data["edges"]  # lista de [parent_id, child_id]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb_path)

# --- 1. Armature real, con la jerarquía calculada en 1.1-1.3 ---
armature_data = bpy.data.armatures.new("SkeletonArmature")
armature_obj = bpy.data.objects.new("SkeletonArmature", armature_data)
bpy.context.collection.objects.link(armature_obj)
armature_data.display_type = "OCTAHEDRAL"
armature_obj.show_in_front = True

bpy.context.view_layer.objects.active = armature_obj
bpy.ops.object.mode_set(mode="EDIT")

edit_bones = armature_data.edit_bones
bone_by_child: dict[int, "bpy.types.EditBone"] = {}
for parent_id, child_id in edges:
    bone = edit_bones.new(f"bone_{parent_id}_{child_id}")
    bone.head = node_positions[parent_id]
    bone.tail = node_positions[child_id]
    bone_by_child[child_id] = bone

for parent_id, child_id in edges:
    bone = bone_by_child[child_id]
    if parent_id in bone_by_child:
        bone.parent = bone_by_child[parent_id]
        bone.use_connect = True

bpy.ops.object.mode_set(mode="OBJECT")

# --- 1b. Malla del cuerpo semi-transparente: el esqueleto sigue el eje
#    medial interno de la malla, así que con la malla opaca casi todos los
#    huesos quedarían ocultos dentro del cuerpo (comprobado: un primer
#    render con la malla opaca solo dejaba ver huesos en dedos y siluetas).
#    Se baja el alpha de cada material importado para poder ver el
#    esqueleto a través del cuerpo.
for obj in bpy.data.objects:
    if obj.type != "MESH":
        continue
    for material in obj.data.materials:
        if material is None or not material.use_nodes:
            continue
        material.surface_render_method = "BLENDED"
        principled = material.node_tree.nodes.get("Principled BSDF")
        if principled is not None and "Alpha" in principled.inputs:
            principled.inputs["Alpha"].default_value = 0.25

# --- 2. Geometría auxiliar SOLO para que los huesos aparezcan en el render
#    final (ver nota técnica en el docstring del módulo) ---
bone_material = bpy.data.materials.new(name="BoneDebugMaterial")
bone_material.use_nodes = True
emission = bone_material.node_tree.nodes.new("ShaderNodeEmission")
emission.inputs["Color"].default_value = (1.0, 0.15, 0.15, 1.0)
emission.inputs["Strength"].default_value = 2.0
output_node = bone_material.node_tree.nodes["Material Output"]
bone_material.node_tree.links.new(emission.outputs["Emission"], output_node.inputs["Surface"])

bone_visuals = bpy.data.collections.new("BoneVisuals")
bpy.context.scene.collection.children.link(bone_visuals)

for parent_id, child_id in edges:
    head = mathutils.Vector(node_positions[parent_id])
    tail = mathutils.Vector(node_positions[child_id])
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

# --- 3. Luz + cámaras (frontal y lateral), encuadrando el esqueleto ---
bpy.ops.object.light_add(type="SUN", location=(2, -3, 5))
bpy.context.active_object.data.energy = 3.0

all_points = list(node_positions.values())
xs = [p[0] for p in all_points]
ys = [p[1] for p in all_points]
zs = [p[2] for p in all_points]
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
    out_path = out_dir / f"{name_prefix}_armature_{view_name}.png"
    scene.render.filepath = str(out_path)
    bpy.ops.render.render(write_still=True)
    print(f"Render guardado: {out_path}")
