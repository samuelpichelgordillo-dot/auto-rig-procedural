"""Módulo 1 — esqueletización de mallas.

1.1: esqueletización en bruto (posiblemente con varias componentes
     desconectadas).
1.2: fusión de componentes en un único árbol + selección de raíz.
1.3: poda de nodos redundantes (casi colineales) + jerarquía padre-hijo.
Generación del Armature de Blender y conversión de ejes glTF→Blender: 1.4,
todavía no implementado aquí.
"""
from __future__ import annotations

import collections
import math

import networkx as nx
import skeletor
import trimesh

# step_size de skeletor.skeletonize.by_wavefront: agrupa `step_size` anillos
# geodésicos consecutivos en un único nodo. A diferencia de un umbral de
# distancia en unidades del mundo (como `sampling_dist` en
# by_vertex_clusters), es adimensional y da una reducción de nodos
# comparable en mallas de escalas muy distintas (probado sobre los 3
# samples: cow ~9 unidades, biped ~1.8, bat ~3 — sin ajuste por modelo).
_WAVEFRONT_STEP_SIZE = 2


def extract_skeleton_graph(mesh_path: str) -> nx.Graph:
    """Carga una malla y devuelve su esqueleto en bruto como grafo.

    Cada nodo tiene un atributo ``pos`` con su posición 3D (x, y, z).
    El resultado es, para cada componente conexa de la malla, un árbol
    (sin ciclos) — la clasificación de raíz/extremidades y la generación
    del Armature se hacen en un paso posterior (Módulo 1.2).
    """
    mesh = trimesh.load(mesh_path, force="mesh")

    # Los exportadores glTF duplican vértices por cara (normales/UVs
    # distintos por cara plana), así que la malla "en crudo" está partida
    # en cientos de fragmentos de 1 sola cara. Fusionar vértices por
    # posición reconstruye la conectividad real de la superficie, algo
    # imprescindible para que la contracción/skeletonización tenga sentido.
    mesh.merge_vertices()

    skeleton = skeletor.skeletonize.by_wavefront(
        mesh, waves=1, step_size=_WAVEFRONT_STEP_SIZE, progress=False
    )

    graph = nx.Graph()
    for node_id, position in enumerate(skeleton.vertices):
        graph.add_node(node_id, pos=tuple(float(c) for c in position))
    graph.add_edges_from((int(a), int(b)) for a, b in skeleton.edges)

    return graph


def _closest_pair(
    graph: nx.Graph, component_a: list[int], component_b: list[int]
) -> tuple[float, int, int]:
    """Distancia mínima punto-a-punto (fuerza bruta) entre dos componentes.

    Devuelve (distancia, nodo_en_a, nodo_en_b) del par más cercano.
    """
    best_distance = math.inf
    best_pair = (None, None)
    for node_a in component_a:
        pos_a = graph.nodes[node_a]["pos"]
        for node_b in component_b:
            pos_b = graph.nodes[node_b]["pos"]
            distance = math.dist(pos_a, pos_b)
            if distance < best_distance:
                best_distance = distance
                best_pair = (node_a, node_b)
    return best_distance, best_pair[0], best_pair[1]


def merge_components(graph: nx.Graph) -> nx.Graph:
    """Fusiona las componentes conexas de ``graph`` en un único árbol conexo.

    Trata cada componente como un super-nodo, calcula el MST entre
    componentes (peso = distancia mínima punto-a-punto entre sus nodos —
    igual criterio que el diagnóstico de ``inspect_skeleton.py``) y añade,
    por cada arista de ese MST, la arista real entre el par de nodos que
    logra esa distancia mínima. Como cada componente ya es un árbol y el
    MST conecta las componentes sin ciclos entre sí, el resultado es un
    único árbol (no se introduce ningún ciclo).

    Si ``graph`` ya es conexo, se devuelve una copia sin modificar.
    """
    components = [list(c) for c in nx.connected_components(graph)]
    merged = graph.copy()

    if len(components) <= 1:
        return merged

    n = len(components)
    component_graph = nx.Graph()
    component_graph.add_nodes_from(range(n))
    closest_node_pair = {}
    for i in range(n):
        for j in range(i + 1, n):
            distance, node_a, node_b = _closest_pair(
                graph, components[i], components[j]
            )
            component_graph.add_edge(i, j, weight=distance)
            closest_node_pair[(i, j)] = (node_a, node_b)

    component_mst = nx.minimum_spanning_tree(component_graph, weight="weight")

    for i, j in component_mst.edges():
        node_a, node_b = closest_node_pair.get((i, j)) or closest_node_pair[(j, i)]
        weight = component_graph[i][j]["weight"]
        merged.add_edge(node_a, node_b, weight=weight)

    return merged


def select_root(tree: nx.Graph) -> int:
    """Elige la raíz como el centroide del árbol (teoría de grafos).

    El centroide de un árbol es el nodo cuya eliminación minimiza el
    tamaño del mayor sub-árbol resultante. A diferencia del centroide
    espacial (promedio de posiciones 3D), que puede caer fuera del propio
    grafo o en una extremidad si esta concentra muchos nodos, el centroide
    de grafo siempre es un nodo real y tiende a caer cerca del "centro de
    masa topológico" del esqueleto (torso), que es lo que buscamos como
    raíz de la jerarquía del futuro Armature.

    Requiere que ``tree`` sea conexo (llamar a ``merge_components`` antes
    si no lo es).
    """
    n = tree.number_of_nodes()
    if n == 0:
        raise ValueError("El árbol no tiene nodos")
    if n == 1:
        return next(iter(tree.nodes))

    start = next(iter(tree.nodes))
    parent: dict[int, int | None] = {start: None}
    order = [start]
    queue = collections.deque([start])
    while queue:
        current = queue.popleft()
        for neighbor in tree.neighbors(current):
            if neighbor not in parent:
                parent[neighbor] = current
                order.append(neighbor)
                queue.append(neighbor)

    # Tamaño de cada sub-árbol "hacia abajo" (post-order: hojas primero).
    subtree_size = {node: 1 for node in tree.nodes}
    for node in reversed(order):
        node_parent = parent[node]
        if node_parent is not None:
            subtree_size[node_parent] += subtree_size[node]

    best_node = start
    best_max_branch = None
    for node in tree.nodes:
        # Componente "hacia el padre" al quitar `node` (0 si node es la raíz
        # provisional usada para el BFS, ya que no tiene padre).
        max_branch = n - subtree_size[node]
        for neighbor in tree.neighbors(node):
            if parent.get(neighbor) == node:
                max_branch = max(max_branch, subtree_size[neighbor])

        if best_max_branch is None or max_branch < best_max_branch:
            best_max_branch = max_branch
            best_node = node

    return best_node


def _angle_degrees(vector_a: tuple[float, float, float], vector_b: tuple[float, float, float]) -> float | None:
    """Ángulo en grados entre dos vectores 3D, o None si alguno es ~nulo."""
    norm_a = math.sqrt(sum(c * c for c in vector_a))
    norm_b = math.sqrt(sum(c * c for c in vector_b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return None
    dot = sum(a * b for a, b in zip(vector_a, vector_b))
    cos_theta = max(-1.0, min(1.0, dot / (norm_a * norm_b)))
    return math.degrees(math.acos(cos_theta))


def prune_redundant_joints(
    tree: nx.Graph, root: int, angle_threshold_deg: float = 170.0
) -> nx.Graph:
    """Colapsa nodos de grado 2 casi colineales con sus dos vecinos.

    Un nodo de grado 2 es "redundante" si el ángulo entre el vector hacia
    cada uno de sus dos vecinos es mayor o igual que ``angle_threshold_deg``
    (es decir, el camino pasa casi en línea recta por él: no aporta
    articulación real, solo densidad de muestreo del esqueletizador). Se
    elimina el nodo y se conecta directamente a sus dos vecinos.

    No se tocan nodos de grado 1 (extremos), de grado 3+ (bifurcaciones) ni
    la raíz — la raíz se conserva siempre aunque tenga grado 2, porque es
    el punto de partida fijo de la jerarquía.

    El proceso es iterativo: tras cada colapso, los vecinos afectados
    quedan con una nueva arista (con una nueva geometría), así que hace
    falta re-evaluar la colinealidad en varias pasadas para colapsar
    cadenas largas de nodos redundantes.
    """
    pruned = tree.copy()
    changed = True
    while changed:
        changed = False
        for node in list(pruned.nodes):
            if node == root or pruned.degree[node] != 2:
                continue
            neighbor_a, neighbor_b = list(pruned.neighbors(node))
            pos_node = pruned.nodes[node]["pos"]
            pos_a = pruned.nodes[neighbor_a]["pos"]
            pos_b = pruned.nodes[neighbor_b]["pos"]
            vector_to_a = tuple(a - n for a, n in zip(pos_a, pos_node))
            vector_to_b = tuple(b - n for b, n in zip(pos_b, pos_node))
            angle = _angle_degrees(vector_to_a, vector_to_b)
            if angle is not None and angle >= angle_threshold_deg:
                pruned.remove_node(node)
                pruned.add_edge(neighbor_a, neighbor_b)
                changed = True
                break  # el grafo cambió: reiniciar el escaneo
    return pruned


def build_hierarchy(tree: nx.Graph, root: int) -> dict[int, int | None]:
    """Jerarquía padre-hijo obtenida por BFS desde ``root``.

    Devuelve un diccionario ``{nodo: padre}`` con ``hierarchy[root] = None``.
    """
    parent: dict[int, int | None] = {root: None}
    queue = collections.deque([root])
    while queue:
        current = queue.popleft()
        for neighbor in tree.neighbors(current):
            if neighbor not in parent:
                parent[neighbor] = current
                queue.append(neighbor)
    return parent
