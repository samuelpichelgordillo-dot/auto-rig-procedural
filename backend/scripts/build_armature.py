"""Genera el Armature real de un modelo, lo parentea a la malla con
auto-weight por difusión de calor nativo de Blender
(``bpy.ops.object.parent_set(type='ARMATURE_AUTO')``) y exporta el
resultado como un GLB nuevo.

Script de PRODUCCIÓN (sin prefijo ``_`` — a diferencia de
``_export_skeleton_json.py`` / ``_render_armature_debug.py``, que son
utilidades de un solo uso / depuración, este forma parte del pipeline
final). Es el primer paso del Módulo 2 (skinning): Armature + parentado
con auto-weight en bruto. El post-proceso de pesos (máx. 4
influencias/vértice, normalizado, suavizado) y su test de deformación son
la siguiente tarea, una vez se vea cómo salen estos pesos en bruto.

Arquitectura: mismo patrón dual-modo que ``backend/scripts/inspect_glb.py``
— el pipeline de esqueletización (trimesh/skeletor/networkx) corre en el
Python del sistema; Blender headless no tiene esos paquetes instalados.
Así que este mismo script se reinvoca a sí mismo como subproceso de
Blender, pasándole el esqueleto ya calculado (posiciones ya convertidas a
ejes Blender + jerarquía) vía un JSON temporal — el mismo patrón de
handoff que ya usaban ``_export_skeleton_json.py`` +
``_render_armature_debug.py`` por separado, unificado aquí en un solo
script y un solo comando para quien lo use. Se eligió el wrapper (en vez
de pedir ``blender --background --python ... --`` directamente) para que
el comando de uso sea idéntico al de ``inspect_glb.py`` y no dependa de
que quien lo ejecute sepa que por dentro hay dos intérpretes distintos.

Uso:
    python backend/scripts/build_armature.py samples/<modelo>.glb <salida.glb>
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


def create_armature(
    node_positions: dict[int, tuple[float, float, float]],
    edges: list[list[int]],
):
    """Crea un Armature real en la escena activa con la jerarquía dada.

    Debe llamarse dentro de Blender (importa ``bpy`` internamente). Deja
    el Armature en modo OBJECT al terminar y lo devuelve. Factorizada aquí
    (en vez de en ``_render_armature_debug.py``, que la importa desde
    este módulo) para no duplicar la construcción de edit bones entre el
    script de depuración y el de producción.
    """
    import bpy

    armature_data = bpy.data.armatures.new("SkeletonArmature")
    armature_obj = bpy.data.objects.new("SkeletonArmature", armature_data)
    bpy.context.collection.objects.link(armature_obj)
    armature_data.display_type = "OCTAHEDRAL"
    armature_obj.show_in_front = True

    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.mode_set(mode="EDIT")

    edit_bones = armature_data.edit_bones
    bone_by_child = {}
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
    return armature_obj


def _run_inside_blender(glb_path: str, json_path: str, out_path: str) -> None:
    """Se ejecuta dentro del intérprete de Blender (bpy disponible)."""
    import bpy

    with open(json_path, encoding="utf-8") as f:
        skeleton_data = json.load(f)
    node_positions = {
        int(node_id): tuple(position)
        for node_id, position in skeleton_data["nodes"].items()
    }
    edges = skeleton_data["edges"]

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=glb_path)

    mesh_objects = [o for o in bpy.data.objects if o.type == "MESH"]
    if not mesh_objects:
        raise RuntimeError(
            f"{glb_path}: no se encontró ningún objeto MESH tras importar"
        )

    # Fusionar vértices duplicados por posición en cada malla, igual razón
    # que en skeletonization.py._load_and_prepare_mesh: los exportadores
    # glTF duplican vértices por cara (normales/UVs distintos por cara
    # plana), lo que deja la malla partida en muchas islas desconectadas.
    # Detectado durante el desarrollo de este script: con la malla sin
    # fusionar, "Bone Heat Weighting" de Blender crea los vertex groups
    # pero no asigna NINGÚN peso a NINGÚN vértice (0 de 1616 en cow) — la
    # difusión de calor necesita conectividad real de superficie para
    # propagarse, y una isla de 1 sola cara no tiene por dónde difundir.
    # Tras fusionar sí funciona (comprobado: 400/400 vértices en cow).
    for mesh_obj in mesh_objects:
        bpy.context.view_layer.objects.active = mesh_obj
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.object.mode_set(mode="OBJECT")

    armature_obj = create_armature(node_positions, edges)

    # Parentar con auto-weight (difusión de calor nativa de Blender):
    # selecciona las mallas + el armature, con el armature como objeto
    # activo (parent_set toma el objeto activo como el nuevo padre).
    bpy.ops.object.select_all(action="DESELECT")
    for mesh_obj in mesh_objects:
        mesh_obj.select_set(True)
    armature_obj.select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")

    out_dir = Path(out_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=out_path, export_format="GLB")
    print(f"Exportado (rigged): {out_path}")


def _run_as_wrapper(glb_path: str, out_path: str) -> int:
    """Se ejecuta con Python normal: calcula el esqueleto y reinvoca a
    Blender headless como subproceso, pasándole el resultado vía JSON.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from backend.app.skeletonization import build_skeleton_tree, gltf_to_blender

    tree, root, hierarchy = build_skeleton_tree(glb_path)
    nodes = {
        str(node): gltf_to_blender(tree.nodes[node]["pos"]) for node in tree.nodes
    }
    edges = [
        [parent, child] for child, parent in hierarchy.items() if parent is not None
    ]
    data = {"root": root, "nodes": nodes, "edges": edges}

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp_file:
        json.dump(data, tmp_file)
        json_path = tmp_file.name

    try:
        script_path = Path(__file__).resolve()
        cmd = [
            "blender",
            "--background",
            "--python",
            str(script_path),
            "--",
            str(Path(glb_path).resolve()),
            json_path,
            str(Path(out_path).resolve()),
        ]
        result = subprocess.run(cmd)
        return result.returncode
    finally:
        Path(json_path).unlink(missing_ok=True)


if __name__ == "__main__":
    if "--" in sys.argv:
        # Ejecutándose dentro de Blender: los argumentos tras "--" son los nuestros.
        args = sys.argv[sys.argv.index("--") + 1 :]
        if len(args) != 3:
            print(
                "Uso interno: blender --background --python build_armature.py "
                "-- <modelo.glb> <esqueleto.json> <salida.glb>"
            )
            sys.exit(1)
        _run_inside_blender(args[0], args[1], args[2])
    else:
        # Ejecutándose con Python normal: calcular el esqueleto y reinvocar Blender.
        if len(sys.argv) != 3:
            print("Uso: python build_armature.py <modelo.glb> <salida.glb>")
            sys.exit(1)
        sys.exit(_run_as_wrapper(sys.argv[1], sys.argv[2]))
