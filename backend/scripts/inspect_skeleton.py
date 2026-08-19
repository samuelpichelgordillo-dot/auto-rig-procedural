"""Inspecciona el esqueleto en bruto (Módulo 1.1) extraído de un GLB.

Uso:
    python backend/scripts/inspect_skeleton.py samples/<modelo>.glb
"""
from __future__ import annotations

import collections
import math
import sys
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.skeletonization import (
    build_hierarchy,
    collapse_short_edges,
    extract_skeleton_graph,
    merge_components,
    select_root,
    simplify_chains_rdp,
)

# Umbral para marcar huesos "casi de longitud cero": Blender no admite
# huesos de longitud 0, así que cualquier arista por debajo de este
# porcentaje del tamaño del modelo (diagonal de su bounding box) necesitará
# tratamiento especial más adelante (fusionar con el padre, descartar, etc.
# — todavía no decidido, solo se detecta aquí).
_SHORT_BONE_THRESHOLD_PCT = 0.005

# Tolerancia de Ramer-Douglas-Peucker para simplificar tramos rectos: un
# punto intermedio de un tramo sobrevive si se desvía más de este % de la
# diagonal del modelo respecto a la cuerda extremo-a-extremo del tramo.
# Mismo valor de partida que _SHORT_BONE_THRESHOLD_PCT, pero es un
# parámetro independiente y fácil de ajustar.
_RDP_TOLERANCE_PCT = 0.005


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

    # --- 1.3: colapso de aristas casi-cero + simplificación RDP por tramos + jerarquía ---
    positions_pre = [merged.nodes[n]["pos"] for n in merged.nodes]
    xs_pre = [p[0] for p in positions_pre]
    ys_pre = [p[1] for p in positions_pre]
    zs_pre = [p[2] for p in positions_pre]
    bbox_diagonal = math.dist(
        (min(xs_pre), min(ys_pre), min(zs_pre)),
        (max(xs_pre), max(ys_pre), max(zs_pre)),
    )
    short_bone_threshold = _SHORT_BONE_THRESHOLD_PCT * bbox_diagonal
    rdp_tolerance = _RDP_TOLERANCE_PCT * bbox_diagonal

    collapsed = collapse_short_edges(merged, root, short_bone_threshold)
    simplified = simplify_chains_rdp(collapsed, root, rdp_tolerance)
    hierarchy = build_hierarchy(simplified, root)

    def depth_of(node: int) -> int:
        depth = 0
        while hierarchy[node] is not None:
            node = hierarchy[node]
            depth += 1
        return depth

    max_depth = max(depth_of(node) for node in simplified.nodes)

    bone_edges = []
    for child, parent in hierarchy.items():
        if parent is None:
            continue
        length = math.dist(simplified.nodes[parent]["pos"], simplified.nodes[child]["pos"])
        bone_edges.append((parent, child, length))

    short_edges = sorted(
        (e for e in bone_edges if e[2] < short_bone_threshold), key=lambda e: e[2]
    )

    print()
    print("--- Poda (1.3): colapso de aristas casi-cero + simplificación RDP por tramos + jerarquía ---")
    print(f"Nodos antes de cualquier simplificación: {merged.number_of_nodes()}")
    print(
        "Diagonal de la bounding box del modelo (antes de simplificar): "
        f"{bbox_diagonal:.4f}"
    )
    print(
        "Umbral de longitud 'casi cero' "
        f"({_SHORT_BONE_THRESHOLD_PCT * 100:.2f}% de la diagonal): "
        f"{short_bone_threshold:.6f}"
    )
    print(
        "Tolerancia RDP "
        f"({_RDP_TOLERANCE_PCT * 100:.2f}% de la diagonal): "
        f"{rdp_tolerance:.6f}"
    )
    print(
        f"Nodos tras colapsar aristas casi-cero (cualquier grado): "
        f"{collapsed.number_of_nodes()}"
    )
    print(
        f"Nodos tras simplificar tramos con RDP: "
        f"{simplified.number_of_nodes()}"
    )
    print(f"Profundidad máxima de la jerarquía final: {max_depth}")
    if short_edges:
        print(
            f"Aristas padre-hijo restantes por debajo del umbral ({len(short_edges)}):"
        )
        for parent, child, length in short_edges:
            print(f"  padre={parent}  hijo={child}  longitud={length:.6f}")
    else:
        print("Aristas padre-hijo restantes por debajo del umbral: ninguna")

    # --- Diagnóstico de dónde se concentra la profundidad (solo lectura) ---
    deepest_node = max(simplified.nodes, key=depth_of)
    deepest_path = [deepest_node]
    while hierarchy[deepest_path[-1]] is not None:
        deepest_path.append(hierarchy[deepest_path[-1]])
    deepest_path.reverse()

    root_children = [node for node in simplified.nodes if hierarchy[node] == root]

    def branch_root_child(node: int) -> int:
        while hierarchy[node] != root:
            node = hierarchy[node]
        return node

    branch_max_depth: dict[int, int] = {child: 0 for child in root_children}
    for node in simplified.nodes:
        if node == root:
            continue
        child = branch_root_child(node)
        d = depth_of(node)
        if d > branch_max_depth[child]:
            branch_max_depth[child] = d

    print()
    print("--- Diagnóstico de profundidad (solo lectura) ---")
    print(f"Nodo más profundo: {deepest_node} (profundidad {max_depth})")
    print(f"Ruta raíz -> nodo más profundo ({len(deepest_path)} nodos):")
    print("  " + " -> ".join(str(n) for n in deepest_path))
    print()
    print(f"Hijos directos de la raíz ({len(root_children)}) y profundidad máxima de su sub-árbol:")
    for child in sorted(root_children, key=lambda c: -branch_max_depth[c]):
        print(f"  hijo={child}  profundidad_max_subárbol={branch_max_depth[child]}")

    # --- Solo para el bípedo: ruta simplificada raíz -> nodo 2 (la misma
    # pierna diagnosticada antes con el criterio de ángulo), para comparar
    # cuántos puntos sobreviven y en qué posiciones frente a los 30 nodos
    # de entonces. El id de nodo 2 es específico de ese modelo/ejecución de
    # skeletor — no tiene el mismo significado en cow/bat, así que no se
    # imprime para ellos.
    if "biped" in mesh_path and 2 in simplified.nodes:
        leg_path = [2]
        while hierarchy[leg_path[-1]] is not None:
            leg_path.append(hierarchy[leg_path[-1]])
        leg_path.reverse()

        print()
        print(
            f"--- Ruta simplificada raíz -> nodo 2 ({len(leg_path)} nodos, "
            "antes eran 30) ---"
        )
        for node in leg_path:
            pos = simplified.nodes[node]["pos"]
            degree = simplified.degree[node]
            print(
                f"  nodo={node}  grado={degree}  "
                f"pos=({pos[0]:.4f}, {pos[1]:.4f}, {pos[2]:.4f})"
            )

        # --- Diagnóstico de solo lectura: por qué RDP conservó cada punto
        # intermedio, y tamaño real de cada tramo (anclaje a anclaje) que
        # compone esta pierna. Reimplementa localmente la misma fórmula de
        # distancia perpendicular que usa simplify_chains_rdp, solo para
        # poder registrar el valor que disparó cada conservación (la
        # función real no expone ese dato). No cambia ningún parámetro.
        def point_to_line_distance(point, line_start, line_end):
            chord = tuple(e - s for e, s in zip(line_end, line_start))
            chord_len_sq = sum(c * c for c in chord)
            if chord_len_sq < 1e-24:
                return math.dist(point, line_start)
            to_point = tuple(p - s for p, s in zip(point, line_start))
            t = sum(a * b for a, b in zip(to_point, chord)) / chord_len_sq
            projection = tuple(s + t * c for s, c in zip(line_start, chord))
            return math.dist(point, projection)

        def rdp_with_trace(positions, tolerance):
            n = len(positions)
            keep = [False] * n
            keep[0] = True
            keep[-1] = True
            trigger_dist = {}

            def recurse(start, end):
                if end <= start + 1:
                    return
                max_dist = -1.0
                max_index = -1
                for i in range(start + 1, end):
                    d = point_to_line_distance(positions[i], positions[start], positions[end])
                    if d > max_dist:
                        max_dist = d
                        max_index = i
                if max_dist > tolerance:
                    keep[max_index] = True
                    trigger_dist[max_index] = max_dist
                    recurse(start, max_index)
                    recurse(max_index, end)

            recurse(0, n - 1)
            return keep, trigger_dist

        # Reconstruir la ruta raíz->nodo 2 SIN simplificar (sobre `collapsed`,
        # la entrada de simplify_chains_rdp) para recuperar los tramos
        # anclaje-a-anclaje originales que RDP procesó por separado.
        collapsed_hierarchy = build_hierarchy(collapsed, root)
        unsimplified_leg_path = [2]
        while collapsed_hierarchy[unsimplified_leg_path[-1]] is not None:
            unsimplified_leg_path.append(collapsed_hierarchy[unsimplified_leg_path[-1]])
        unsimplified_leg_path.reverse()

        def is_anchor_in_collapsed(node: int) -> bool:
            return node == root or collapsed.degree[node] != 2

        # Partir la ruta en tramos anclaje-a-anclaje.
        tramos = []
        current_tramo = [unsimplified_leg_path[0]]
        for node in unsimplified_leg_path[1:]:
            current_tramo.append(node)
            if is_anchor_in_collapsed(node):
                tramos.append(current_tramo)
                current_tramo = [node]

        print()
        print(
            "--- Diagnóstico RDP de solo lectura: tramos anclaje-a-anclaje de "
            "esta pierna ---"
        )
        largest_tramo = None
        largest_chord_length = -1.0
        for tramo in tramos:
            positions = [collapsed.nodes[n]["pos"] for n in tramo]
            chord_length = math.dist(positions[0], positions[-1])
            if chord_length > largest_chord_length:
                largest_chord_length = chord_length
                largest_tramo = tramo

            keep_mask, trigger_dist = rdp_with_trace(positions, rdp_tolerance)
            print(
                f"Tramo {tramo[0]} -> {tramo[-1]} "
                f"({len(tramo)} nodos, cuerda={chord_length:.4f}):"
            )
            for local_index, node in enumerate(tramo):
                if local_index in (0, len(tramo) - 1):
                    continue  # extremos: no son "puntos que sobrevivieron", son anclajes
                if keep_mask[local_index]:
                    d = trigger_dist[local_index]
                    print(
                        f"    nodo={node}  sobrevivió  "
                        f"desviación_perpendicular={d:.6f}"
                    )

        print()
        print(
            f"Tramo mayor (por longitud de cuerda extremo-a-extremo): "
            f"{largest_tramo[0]} -> {largest_tramo[-1]}"
        )
        print(f"Longitud de esa cuerda: {largest_chord_length:.4f}")
        print(f"Tolerancia RDP actual (absoluta): {rdp_tolerance:.6f}")
        print(
            "Tolerancia RDP como % de ESA cuerda local (no de la diagonal "
            f"global): {rdp_tolerance / largest_chord_length * 100:.4f}%"
        )

        # --- Diagnóstico de solo lectura: ramas laterales que cuelgan de
        # cada bifurcación (grado 3+) del camino de la pierna, en el grafo
        # ya simplificado. No implementa ninguna poda. ---
        def nearest_leaf_in_branch(graph, anchor, branch_neighbor):
            visited = {anchor, branch_neighbor}
            parent = {branch_neighbor: anchor}
            queue = collections.deque([branch_neighbor])
            while queue:
                node = queue.popleft()
                if graph.degree[node] == 1:
                    branch_path = [node]
                    while branch_path[-1] != branch_neighbor:
                        branch_path.append(parent[branch_path[-1]])
                    branch_path.reverse()
                    # La distancia se mide desde la propia bifurcación
                    # (anchor) hasta la hoja, así que se incluye la arista
                    # anchor->branch_neighbor aunque `anchor` no cuente
                    # como nodo de la rama.
                    full_path = [anchor] + branch_path
                    total_distance = sum(
                        math.dist(graph.nodes[full_path[i]]["pos"], graph.nodes[full_path[i + 1]]["pos"])
                        for i in range(len(full_path) - 1)
                    )
                    return branch_path, total_distance
                for neighbor in graph.neighbors(node):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        parent[neighbor] = node
                        queue.append(neighbor)
            return None, None

        branch_point_ids = [145, 222, 334, 72, 32, 71, 240, 191, 30, 66, 28]

        print()
        print(
            "--- Diagnóstico de solo lectura: ramas laterales en las "
            "bifurcaciones del camino de la pierna ---"
        )
        for node in branch_point_ids:
            if node not in leg_path:
                print(f"Nodo {node}: no está en la ruta simplificada, se omite")
                continue
            index = leg_path.index(node)
            path_neighbors = {leg_path[index - 1], leg_path[index + 1]}
            all_neighbors = set(simplified.neighbors(node))
            side_neighbors = sorted(all_neighbors - path_neighbors)

            print(
                f"Nodo {node} (grado={simplified.degree[node]}, "
                f"vecinos_en_camino={sorted(path_neighbors)}, "
                f"vecinos_laterales={side_neighbors}):"
            )
            for side_neighbor in side_neighbors:
                branch_path, total_distance = nearest_leaf_in_branch(
                    simplified, node, side_neighbor
                )
                if branch_path is None:
                    print(f"    rama por {side_neighbor}: no se encontró hoja (inesperado)")
                    continue
                print(
                    f"    rama por {side_neighbor}: "
                    f"{len(branch_path)} nodos hasta la hoja {branch_path[-1]}  "
                    f"distancia_total={total_distance:.4f}  "
                    f"ruta={' -> '.join(str(n) for n in branch_path)}"
                )


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Uso: python inspect_skeleton.py <modelo.glb>")
        sys.exit(1)
    main(sys.argv[1])
