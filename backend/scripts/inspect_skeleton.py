"""Inspecciona el esqueleto en bruto (Módulo 1.1) extraído de un GLB.

Uso:
    python backend/scripts/inspect_skeleton.py samples/<modelo>.glb
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.skeletonization import (
    build_hierarchy,
    extract_skeleton_graph,
    merge_components,
    prune_redundant_joints,
    select_root,
)

# Umbral para marcar huesos "casi de longitud cero": Blender no admite
# huesos de longitud 0, así que cualquier arista por debajo de este
# porcentaje del tamaño del modelo (diagonal de su bounding box) necesitará
# tratamiento especial más adelante (fusionar con el padre, descartar, etc.
# — todavía no decidido, solo se detecta aquí).
_SHORT_BONE_THRESHOLD_PCT = 0.005


def main(mesh_path: str) -> None:
    graph = extract_skeleton_graph(mesh_path)

    n_nodes = graph.number_of_nodes()
    n_edges = graph.number_of_edges()
    components = list(nx.connected_components(graph))
    n_components = len(components)
    has_cycles = not nx.is_forest(graph)

    print("=== inspect_skeleton.py ===")
    print(f"Archivo: {mesh_path}")
    print(f"Nodos: {n_nodes}")
    print(f"Aristas: {n_edges}")
    print(f"Componentes conexas: {n_components}")
    print(f"¿Tiene ciclos?: {'sí' if has_cycles else 'no'}")

    components_by_size = sorted(components, key=len, reverse=True)
    print()
    print("--- Detalle por componente conexa (ordenadas de mayor a menor) ---")
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

    def min_point_distance(component_a: set, component_b: set) -> float:
        """Distancia mínima punto-a-punto (fuerza bruta) entre dos componentes."""
        positions_a = [graph.nodes[n]["pos"] for n in component_a]
        positions_b = [graph.nodes[n]["pos"] for n in component_b]
        best = math.inf
        for ax, ay, az in positions_a:
            for bx, by, bz in positions_b:
                d = math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)
                if d < best:
                    best = d
        return best

    # Distancia mínima (fuerza bruta, nodo a nodo) de cada componente que no
    # es la mayor hasta la componente mayor. Solo diagnóstico: no decide
    # ningún criterio de fusión, solo expone los datos.
    largest = components_by_size[0]
    others = components_by_size[1:]
    distances_to_largest = [
        (i + 1, len(component), min_point_distance(component, largest))
        for i, component in enumerate(others)
    ]
    distances_to_largest.sort(key=lambda row: row[2])

    print()
    print(
        "--- Distancia mínima de cada componente (excepto la mayor) a la "
        "componente mayor, ordenadas de menor a mayor ---"
    )
    for component_id, n_nodes_component, distance in distances_to_largest:
        print(
            f"Componente {component_id}: nodos={n_nodes_component}  "
            f"distancia_min={distance:.4f}"
        )

    # Distancia mínima punto-a-punto entre TODOS los pares de componentes
    # (no solo contra la mayor), usada como peso de un grafo completo entre
    # super-nodos (uno por componente). Solo diagnóstico: el MST resultante
    # muestra qué conexiones propondría este criterio, sin fusionar nada
    # todavía ni decidir raíz.
    n = len(components_by_size)
    component_graph = nx.Graph()
    component_graph.add_nodes_from(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            d = min_point_distance(components_by_size[i], components_by_size[j])
            component_graph.add_edge(i, j, weight=d)

    mst = nx.minimum_spanning_tree(component_graph, weight="weight")

    print()
    print(
        "--- Aristas del Árbol de Expansión Mínima (MST) entre componentes "
        "(grafo completo, peso = distancia mínima punto-a-punto) ---"
    )
    mst_edges = sorted(
        mst.edges(data=True), key=lambda e: e[2]["weight"]
    )
    for a, b, data in mst_edges:
        print(
            f"Componente {a} (nodos={len(components_by_size[a])})  <->  "
            f"Componente {b} (nodos={len(components_by_size[b])})  "
            f"distancia={data['weight']:.4f}"
        )

    # --- 1.2: fusión real de componentes + selección de raíz ---
    merged = merge_components(graph)
    root = select_root(merged)
    root_pos = merged.nodes[root]["pos"]
    root_degree = merged.degree[root]

    print()
    print("--- Fusión (1.2): árbol único + raíz (centroide de grafo) ---")
    print(f"Nodos tras fusión: {merged.number_of_nodes()}")
    print(f"Aristas tras fusión: {merged.number_of_edges()}")
    print(f"Componentes conexas tras fusión: {nx.number_connected_components(merged)}")
    print(f"¿Tiene ciclos tras fusión?: {'sí' if not nx.is_forest(merged) else 'no'}")
    print(f"Nodo raíz elegido: {root}")
    print(
        "Posición 3D de la raíz: "
        f"({root_pos[0]:.4f}, {root_pos[1]:.4f}, {root_pos[2]:.4f})"
    )
    print(f"Grado de la raíz (nº de vecinos directos): {root_degree}")

    # --- 1.3: poda de nodos redundantes + jerarquía padre-hijo ---
    pruned = prune_redundant_joints(merged, root)
    hierarchy = build_hierarchy(pruned, root)

    def depth_of(node: int) -> int:
        depth = 0
        while hierarchy[node] is not None:
            node = hierarchy[node]
            depth += 1
        return depth

    max_depth = max(depth_of(node) for node in pruned.nodes)

    positions = [pruned.nodes[n]["pos"] for n in pruned.nodes]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    bbox_diagonal = math.dist(
        (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
    )
    short_bone_threshold = _SHORT_BONE_THRESHOLD_PCT * bbox_diagonal

    bone_edges = []
    for child, parent in hierarchy.items():
        if parent is None:
            continue
        length = math.dist(pruned.nodes[parent]["pos"], pruned.nodes[child]["pos"])
        bone_edges.append((parent, child, length))

    short_edges = sorted(
        (e for e in bone_edges if e[2] < short_bone_threshold), key=lambda e: e[2]
    )

    print()
    print("--- Poda (1.3): nodos redundantes + jerarquía ---")
    print(f"Nodos antes de podar: {merged.number_of_nodes()}")
    print(f"Nodos después de podar: {pruned.number_of_nodes()}")
    print(f"Profundidad máxima de la jerarquía: {max_depth}")
    print(
        "Diagonal de la bounding box del modelo (tras podar): "
        f"{bbox_diagonal:.4f}"
    )
    print(
        "Umbral de longitud 'casi cero' "
        f"({_SHORT_BONE_THRESHOLD_PCT * 100:.2f}% de la diagonal): "
        f"{short_bone_threshold:.6f}"
    )
    if short_edges:
        print(f"Aristas padre-hijo por debajo del umbral ({len(short_edges)}):")
        for parent, child, length in short_edges:
            print(f"  padre={parent}  hijo={child}  longitud={length:.6f}")
    else:
        print("Aristas padre-hijo por debajo del umbral: ninguna")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python inspect_skeleton.py <modelo.glb>")
        sys.exit(1)
    main(sys.argv[1])
