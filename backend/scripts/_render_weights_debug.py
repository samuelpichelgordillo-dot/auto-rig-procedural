"""Inspección visual de los pesos de auto-weight (difusión de calor) ya
generados por build_armature.py sobre un GLB rigged, para decidir si hace
falta post-proceso (Módulo 2, tarea pendiente tras el checkpoint del
2026-08-19: "Armature real + parentado auto-weight + export").

Utilidad de depuración de un solo uso (prefijo ``_``, igual criterio que
``_render_armature_debug.py`` / ``_render_rigged_debug.py``): no calcula
nada nuevo, solo lee los vertex groups que build_armature.py ya dejó en el
GLB y los pinta.

Genera dos tipos de render por modelo, vista frontal + lateral (mismo
encuadre que los scripts anteriores):

  a) Segmentación por hueso dominante: cada vértice se colorea según el
     vertex group (hueso) con mayor peso en ese vértice, con una paleta
     categórica fija de 20 colores (aprox. 'tab20' de matplotlib) asignada
     por orden alfabético de nombre de hueso — determinista entre
     ejecuciones, sin depender de matplotlib como dependencia nueva.

  b) Mapa de calor (azul=peso 0, rojo=peso 1, interpolación lineal) de 1-2
     huesos concretos por modelo, elegidos a mano inspeccionando la
     jerarquía de cada esqueleto (ver HEATMAP_BONES más abajo y su
     justificación). Un marcador cian pequeño señala la posición del hueso
     resaltado. Los vértices sin ese vertex group cuentan como peso 0.

Cómo se eligieron los huesos de (b) — inspeccionando
``_export_skeleton_json.py`` + recorrido manual del árbol resultante
(posiciones ya en ejes Blender, Z-up) para cada modelo. Criterio (revisado,
ver nota de corrección más abajo): el hueso debe TERMINAR en un nodo de
GRADO 2 (punto de paso simple, sin bifurcación propia) situado a medio
camino, por distancia geométrica acumulada, de una cadena larga entre dos
bifurcaciones reales — nunca un nodo cuya propia bifurcación termine en 1-2
saltos en una hoja aislada, esa es la firma de un dedo/dedo del pie o de
ruido de malla, no de una articulación real:

  - cow: cadena 3(bifurcación real, grado 3: rama corta a hoja 9 + rama a
    29) -> 29(grado 2) -> 15(hoja, pie). Único nodo interior de grado 2 de
    toda la pata, al 66.5% de la distancia acumulada 3->15. Hueso
    "bone_3_29", codo/rodilla de la pata delantera. Sin cambios respecto a
    la primera versión de este script — confirmado correcto.
  - biped, brazo derecho: hombro(180, grado3, bifurcación real hacia otra
    cadena) -> 106(grado2) -> 57(grado3, rama espuria de 1 salto a hoja 23)
    -> 107(grado3, rama espuria de 1 salto a hoja 147) -> 206(grado2) ->
    58(grado3, rama espuria a hoja 184) -> 109 -> 151(grado4, bifurcación
    real hacia los dedos). De los dos únicos nodos de grado 2 sin rama
    espuria (106 al 17%, 206 al 74% de la distancia 180->151), se eligió
    "bone_107_206" (articulación en 206) por ser el más cercano al punto
    medio real y quedar fuera del racimo de nodos densificados junto a la
    mano.
  - biped, pierna izquierda: cadera(72, grado3, bifurcación real hacia la
    otra pierna) -> 32 -> 5(grado2) -> 71(grado4, DOS ramas espurias de 1
    salto a hojas 130/132 — firma de dedo, no articulación) -> 118(grado2)
    -> 192 -> 240 -> 267 -> 191 -> 116 -> 30(grado5, bifurcación real hacia
    los dedos del pie). Se eligió "bone_71_118" (articulación en 118, al
    47.5% de la distancia acumulada 72->30): grado 2 limpio, sin rama
    espuria propia, el más cercano al punto medio geométrico de toda la
    cadena cadera->tobillo.
  - bat: cadena 13(raíz, grado6) -> 18 -> 33 -> 34 -> 24 -> 27(hoja, punta
    del ala). Toda la cadena es de grado 2 salvo la raíz y la hoja, sin
    ramas espurias — pero el primer tramo 13->18 (37% de la distancia total
    13->27) es sobre todo el trayecto torso->hombro, no ala propiamente
    dicha. Calculando el punto medio SOLO de la parte que sale del cuerpo
    (18->27, ala real): 33 está al 13%, 34 al 27%, 24 al 45% — el más
    cercano al 50%. Se eligió "bone_34_24" (articulación en 24) en vez de
    "bone_33_34". Se comprobó también si existía una segunda cadena de ala
    más larga bajo la raíz (nodo 16, grado5): sus subcadenas más largas
    tienen solo 2-3 saltos hasta hoja, consistentes con estructuras
    faciales (orejas/nariz), no con un ala — 18->33->34->24->27 es la única
    cadena de extremidad larga disponible.

Nota de corrección (2026-08-20, mismo día): la primera versión de este
script elegía "bone_57_107" (codo biped), "bone_5_71" (rodilla biped) y
"bone_33_34" (ala bat). Verificación estructural (grado de cada nodo +
detección de ramas espurias de 1 salto a hoja aislada) mostró que 107 y 71
son justo los nodos CONTAMINADOS por esas ramas espurias (dedo/dedo del pie
en biped, o simplemente el extremo proximal del ala en bat, no su punto
medio) — el criterio original ("punto de inflexión visual" / posición
aproximada) no filtraba bifurcaciones espurias ni medía distancia
geométrica real a lo largo de la cadena. Los tres se sustituyeron por los
nodos de arriba, todos de grado 2 y verificados por distancia acumulada.

Uso:
    blender --background --python backend/scripts/_render_weights_debug.py -- \\
        samples/_debug/cow_rigged.glb samples/_debug cow_rigged
"""
from __future__ import annotations

import sys
from pathlib import Path

import bpy
import mathutils

# Paleta categórica fija (~tab20), en RGB [0,1]. Asignada por orden
# alfabético de nombre de hueso para que sea determinista sin depender de
# matplotlib.
_TAB20 = [
    (0.121, 0.466, 0.705), (0.682, 0.780, 0.909), (1.000, 0.498, 0.055),
    (1.000, 0.733, 0.470), (0.173, 0.627, 0.173), (0.596, 0.875, 0.541),
    (0.839, 0.153, 0.157), (1.000, 0.596, 0.588), (0.580, 0.404, 0.741),
    (0.773, 0.690, 0.835), (0.549, 0.337, 0.294), (0.769, 0.611, 0.580),
    (0.890, 0.467, 0.761), (0.969, 0.714, 0.824), (0.498, 0.498, 0.498),
    (0.780, 0.780, 0.780), (0.737, 0.741, 0.133), (0.858, 0.859, 0.553),
    (0.090, 0.745, 0.812), (0.619, 0.854, 0.898),
]

# Ver docstring del módulo para la justificación de cada hueso elegido
# (revisados el 2026-08-20 tras verificación estructural — ver nota de
# corrección más arriba).
HEATMAP_BONES: dict[str, list[tuple[str, str]]] = {
    "cow": [("bone_3_29", "codo_pata_delantera")],
    "biped": [("bone_107_206", "codo"), ("bone_71_118", "rodilla")],
    "bat": [("bone_34_24", "articulacion_ala")],
}


def _bone_color(name: str, sorted_names: list[str]) -> tuple[float, float, float]:
    return _TAB20[sorted_names.index(name) % len(_TAB20)]


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _weight_color(weight: float) -> tuple[float, float, float]:
    weight = max(0.0, min(1.0, weight))
    return (_lerp(0.0, 1.0, weight), 0.0, _lerp(1.0, 0.0, weight))


def _make_vertex_color_material(attr_name: str) -> "bpy.types.Material":
    mat = bpy.data.materials.new(name=f"Weights_{attr_name}")
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    attr_node = nt.nodes.new("ShaderNodeVertexColor")
    attr_node.layer_name = attr_name
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = 1.0
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(attr_node.outputs["Color"], emission.inputs["Color"])
    nt.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    return mat


def _set_vertex_colors(
    mesh_obj: "bpy.types.Object", attr_name: str, colors_by_vertex: list[tuple[float, float, float]]
) -> None:
    mesh = mesh_obj.data
    existing = mesh.color_attributes.get(attr_name)
    if existing is not None:
        mesh.color_attributes.remove(existing)
    color_attr = mesh.color_attributes.new(name=attr_name, type="FLOAT_COLOR", domain="POINT")
    for i, (r, g, b) in enumerate(colors_by_vertex):
        color_attr.data[i].color = (r, g, b, 1.0)
    mesh.attributes.active_color_index = mesh.attributes.find(attr_name)


def _dominant_bone_colors(
    mesh_obj: "bpy.types.Object", sorted_bone_names: list[str]
) -> list[tuple[float, float, float]]:
    group_index_to_name = {g.index: g.name for g in mesh_obj.vertex_groups}
    colors = []
    for vertex in mesh_obj.data.vertices:
        if not vertex.groups:
            colors.append((0.5, 0.5, 0.5))
            continue
        best = max(vertex.groups, key=lambda g: g.weight)
        bone_name = group_index_to_name.get(best.group)
        if bone_name is None:
            colors.append((0.5, 0.5, 0.5))
        else:
            colors.append(_bone_color(bone_name, sorted_bone_names))
    return colors


def _heatmap_colors(mesh_obj: "bpy.types.Object", bone_name: str) -> list[tuple[float, float, float]] | None:
    vg = mesh_obj.vertex_groups.get(bone_name)
    if vg is None:
        return None
    colors = []
    for vertex in mesh_obj.data.vertices:
        weight = 0.0
        for g in vertex.groups:
            if g.group == vg.index:
                weight = g.weight
                break
        colors.append(_weight_color(weight))
    return colors


def _clear_materials(mesh_objects: list["bpy.types.Object"]) -> None:
    for obj in mesh_objects:
        obj.data.materials.clear()


def _setup_camera_and_light(bone_segments) -> None:
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
    scene.camera = front_camera
    scene["_front_camera_name"] = front_camera.name
    scene["_side_camera_name"] = side_camera.name


def _render_views(out_dir: Path, name_prefix: str) -> None:
    scene = bpy.context.scene
    front_camera = bpy.data.objects[scene["_front_camera_name"]]
    side_camera = bpy.data.objects[scene["_side_camera_name"]]
    for camera_obj, view_name in [(front_camera, "front"), (side_camera, "side")]:
        scene.camera = camera_obj
        out_path = out_dir / f"{name_prefix}_{view_name}.png"
        scene.render.filepath = str(out_path)
        bpy.ops.render.render(write_still=True)
        print(f"Render guardado: {out_path}")


def _add_joint_marker(armature_obj: "bpy.types.Object", bone_name: str) -> None:
    bone = armature_obj.data.bones.get(bone_name)
    if bone is None:
        print(f"AVISO: hueso '{bone_name}' no encontrado en el Armature, sin marcador")
        return
    head_world = armature_obj.matrix_world @ bone.head_local
    tail_world = armature_obj.matrix_world @ bone.tail_local
    midpoint = (head_world + tail_world) / 2
    radius = (tail_world - head_world).length * 0.3 or 0.02

    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=midpoint)
    marker = bpy.context.active_object
    marker_mat = bpy.data.materials.new(name="JointMarker")
    marker_mat.use_nodes = True
    nt = marker_mat.node_tree
    nt.nodes.clear()
    emission = nt.nodes.new("ShaderNodeEmission")
    emission.inputs["Color"].default_value = (0.0, 1.0, 1.0, 1.0)
    emission.inputs["Strength"].default_value = 3.0
    output = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(emission.outputs["Emission"], output.inputs["Surface"])
    marker.data.materials.append(marker_mat)


def main(glb_path: str, out_dir_arg: str, name_prefix: str) -> None:
    out_dir = Path(out_dir_arg)
    out_dir.mkdir(parents=True, exist_ok=True)

    model_key = name_prefix.split("_")[0]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb_path)

    armature_objs = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    if not armature_objs:
        raise RuntimeError(f"{glb_path}: no se encontró ningún objeto ARMATURE tras importar")
    armature_obj = armature_objs[0]

    bone_segments = []
    for bone in armature_obj.data.bones:
        head_world = armature_obj.matrix_world @ bone.head_local
        tail_world = armature_obj.matrix_world @ bone.tail_local
        bone_segments.append((head_world, tail_world))

    bone_widget_objects = {
        pose_bone.custom_shape
        for pose_bone in armature_obj.pose.bones
        if pose_bone.custom_shape is not None
    }
    mesh_objects = [
        o for o in bpy.data.objects if o.type == "MESH" and o not in bone_widget_objects
    ]
    if not mesh_objects:
        raise RuntimeError(f"{glb_path}: no se encontró ninguna malla riggeada tras importar")

    all_bone_names = sorted({b.name for b in armature_obj.data.bones})

    # --- (a) Segmentación por hueso dominante ---
    _clear_materials(mesh_objects)
    for obj in mesh_objects:
        colors = _dominant_bone_colors(obj, all_bone_names)
        _set_vertex_colors(obj, "SegColor", colors)
        obj.data.materials.append(_make_vertex_color_material("SegColor"))

    _setup_camera_and_light(bone_segments)
    _render_views(out_dir, f"{name_prefix}_weights_segmentation")

    # --- (b) Mapas de calor por hueso elegido ---
    for bone_name, label in HEATMAP_BONES.get(model_key, []):
        _clear_materials(mesh_objects)
        found_in_any_mesh = False
        for obj in mesh_objects:
            colors = _heatmap_colors(obj, bone_name)
            if colors is None:
                colors = [(0.0, 0.0, 1.0)] * len(obj.data.vertices)
            else:
                found_in_any_mesh = True
            _set_vertex_colors(obj, "HeatColor", colors)
            obj.data.materials.append(_make_vertex_color_material("HeatColor"))

        if not found_in_any_mesh:
            print(f"AVISO: hueso '{bone_name}' sin vertex group en ninguna malla de {glb_path}")

        for existing_marker in [o for o in bpy.data.objects if o.name.startswith("Sphere")]:
            bpy.data.objects.remove(existing_marker, do_unlink=True)
        _add_joint_marker(armature_obj, bone_name)

        _render_views(out_dir, f"{name_prefix}_weights_heatmap_{label}")


if __name__ == "__main__":
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 3:
        print(
            "Uso: blender --background --python _render_weights_debug.py -- "
            "<modelo_rigged.glb> <dir_salida> <prefijo_nombre>"
        )
        sys.exit(1)
    main(args[0], args[1], args[2])
