"""Inspecciona el esqueleto extraído de un GLB (Módulo 1 completo).

Uso:
    python backend/scripts/inspect_skeleton.py samples/<modelo>.glb
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.skeletonization import build_skeleton_tree, extract_skeleton_graph

_SHORT_EDGE_THRESHOLD_PCT = 0.005


def main(mesh_path: str) -> None:
    graph = extract_skeleton_graph(mesh_path)

    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    components = list(nx.connected_components(graph))
    n_components = len(components)
    has_cycles = not nx.is_forest(graph)

    print("=== inspect_skeleton.py ===")
    print(f"Archivo: {mesh_path}")
    print(f"Nodos (en bruto): {n_nodes}")
    print(f"Aristas (en bruto): {n_edges}")
    print(f"Componentes conexas (en bruto): {n_components}")
    print(f"¿Tiene ciclos?: {'sí' if has_cycles else 'no'}")

    components_by_size = sorted(components, key=len, reverse=True)
    print()
    print("--- Detalle por componente conexa en bruto (mayor a menor) ---")
    for i, component in enumerate(components_by_size):
        positions = [graph.nodes[n]["pos"] for n in component]
        xs = [p[0] for p in positions]
        ys = [p[1] for p in positions]
        zs = [p[2] for p in positions]
        centroid = (sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        bbox_min = (min(xs), min(ys), min(zs))
        bbox_max = (max(xs), max(ys), max(zs))

        print(f"Componente {i}:")
        print(f"  Nodos: {len(component)}")
        print(
            "  Centroide: "
            f"({centroid[0]:.4f}, {centroid[1]:.4f}, {centroid[2]:.4f})"
        )
        print(
            "  Bounding box: "
            f"min=({bbox_min[0]:.4f}, {bbox_min[1]:.4f}, {bbox_min[2]:.4f}) "
            f"max=({bbox_max[0]:.4f}, {bbox_max[1]:.4f}, {bbox_max[2]:.4f})"
        )

    # --- Pipeline completo (1.1 -> 1.3): extract -> densify -> merge ->
    # root -> punto fijo collapse/RDP -> hierarchy, todo encapsulado en
    # build_skeleton_tree (ver backend/app/skeletonization.py) ---
    tree, root, hierarchy = build_skeleton_tree(mesh_path)

    def depth_of(node: int) -> int:
        depth = 0
        while hierarchy[node] is not None:
            node = hierarchy[node]
            depth += 1
        return depth

    max_depth = max(depth_of(node) for node in tree.nodes)

    positions = [tree.nodes[n]["pos"] for n in tree.nodes]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    diagonal = math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    short_threshold = _SHORT_EDGE_THRESHOLD_PCT * diagonal

    short_edges = []
    for child, parent in hierarchy.items():
        if parent is None:
            continue
        length = math.dist(tree.nodes[parent]["pos"], tree.nodes[child]["pos"])
        if length < short_threshold:
            short_edges.append((parent, child, length))
    short_edges.sort(key=lambda e: e[2])

    root_pos = tree.nodes[root]["pos"]

    print()
    print("--- Árbol final (build_skeleton_tree) ---")
    print(f"Nodos finales: {tree.number_of_nodes()}")
    print(f"Aristas finales: {tree.number_of_edges()}")
    print(f"Componentes conexas: {nx.number_connected_components(tree)}")
    print(f"¿Tiene ciclos?: {'sí' if not nx.is_forest(tree) else 'no'}")
    print(f"Nodo raíz: {root}")
    print(
        "Posición 3D de la raíz: "
        f"({root_pos[0]:.4f}, {root_pos[1]:.4f}, {root_pos[2]:.4f})"
    )
    print(f"Grado de la raíz: {tree.degree[root]}")
    print(f"Profundidad máxima de la jerarquía: {max_depth}")
    print(f"Umbral de longitud mínima (0.5% de la diagonal): {short_threshold:.6f}")
    if short_edges:
        print(f"Aristas por debajo del umbral ({len(short_edges)}):")
        for parent, child, length in short_edges:
            print(f"  padre={parent}  hijo={child}  longitud={length:.6f}")
    else:
        print("Aristas por debajo del umbral: ninguna")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python inspect_skeleton.py <modelo.glb>")
        sys.exit(1)
    main(sys.argv[1])
