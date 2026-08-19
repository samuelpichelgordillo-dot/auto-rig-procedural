"""Exporta a JSON el árbol de esqueleto final (Módulo 1.1-1.3) de un GLB,
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

Reproduce exactamente el mismo pipeline y los mismos parámetros
(umbral de arista larga a densificar: 10% de la diagonal; umbral de
arista casi-cero y tolerancia RDP: 0.5% de la diagonal) que
backend/scripts/inspect_skeleton.py, para que el Armature resultante
corresponda al esqueleto ya diagnosticado en los pasos anteriores.

Uso:
    python backend/scripts/_export_skeleton_json.py samples/<modelo>.glb <salida.json>
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.skeletonization import (
    build_hierarchy,
    collapse_short_edges,
    densify_long_edges,
    extract_skeleton_graph,
    merge_components,
    select_root,
    simplify_chains_rdp,
)

_LONG_EDGE_THRESHOLD_PCT = 0.10
_SHORT_EDGE_THRESHOLD_PCT = 0.005
_RDP_TOLERANCE_PCT = 0.005


def gltf_to_blender(position: tuple[float, float, float]) -> tuple[float, float, float]:
    x, y, z = position
    return (x, -z, y)


def main(mesh_path: str, out_path: str) -> None:
    graph = extract_skeleton_graph(mesh_path)
    densified = densify_long_edges(
        graph, mesh_path, threshold_pct=_LONG_EDGE_THRESHOLD_PCT
    )
    merged = merge_components(densified)
    root = select_root(merged)

    positions = [merged.nodes[n]["pos"] for n in merged.nodes]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    bbox_diagonal = math.dist(
        (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
    )
    short_threshold = _SHORT_EDGE_THRESHOLD_PCT * bbox_diagonal
    rdp_tolerance = _RDP_TOLERANCE_PCT * bbox_diagonal

    collapsed = collapse_short_edges(merged, root, short_threshold)
    simplified = simplify_chains_rdp(collapsed, root, rdp_tolerance)
    hierarchy = build_hierarchy(simplified, root)

    nodes = {
        str(node): gltf_to_blender(simplified.nodes[node]["pos"])
        for node in simplified.nodes
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
