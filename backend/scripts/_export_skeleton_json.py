"""Exporta a JSON el árbol de esqueleto final (Módulo 1 completo) de un GLB,
con las posiciones ya convertidas de ejes glTF (Y-up) a Blender (Z-up):

    Blender_X = gltf_X
    Blender_Y = -gltf_Z
    Blender_Z = gltf_Y

Utilidad de un solo uso para el sub-paso 1.4 (generación de Armature en
Blender): el pipeline de esqueletización (trimesh/skeletor/networkx) corre
en el Python del sistema, no en el Python embebido de Blender, así que el
resultado se serializa aquí y lo consume un script aparte que sí corre
dentro de `blender --background` (_render_armature_debug.py). La
conversión de ejes se aplica aquí, antes de que ese script cree ningún
hueso, tal como pide el sub-paso 1.4.

Usa build_skeleton_tree con sus parámetros por defecto (los mismos ya
verificados en backend/tests/test_skeleton.py), para que el Armature
resultante corresponda al esqueleto ya verificado.

Uso:
    python backend/scripts/_export_skeleton_json.py samples/<modelo>.glb <salida.json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.skeletonization import build_skeleton_tree, gltf_to_blender


def main(mesh_path: str, out_path: str) -> None:
    tree, root, hierarchy = build_skeleton_tree(mesh_path)

    nodes = {
        str(node): gltf_to_blender(tree.nodes[node]["pos"]) for node in tree.nodes
    }
    edges = [
        [parent, child] for child, parent in hierarchy.items() if parent is not None
    ]

    data = {"root": root, "nodes": nodes, "edges": edges}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Exportado: {out_path} ({len(nodes)} nodos, {len(edges)} aristas)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python _export_skeleton_json.py <modelo.glb> <salida.json>")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
