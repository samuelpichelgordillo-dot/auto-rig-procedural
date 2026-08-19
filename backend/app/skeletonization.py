"""Módulo 1 — esqueletización de mallas.

1.1: esqueletización en bruto (posiblemente con varias componentes
     desconectadas).
1.2: fusión de componentes en un único árbol + selección de raíz.
1.3: simplificación de tramos rectos (Ramer-Douglas-Peucker por tramo,
     entre bifurcaciones/hojas/raíz) + jerarquía padre-hijo.
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
# step_size=1 se probó como posible arreglo a una arista larga y diagonal
# en el tronco de cow_unrigged (raíz->cadera, 4.41 de longitud), pero solo
# la redujo a 3.38 sin resolver el problema de fondo, y aumentó bastante
# el ruido/profundidad en biped y bat (que con step_size=2 funcionaban
# bien). Revertido a 2. Investigar en su lugar si se puede densificar
# selectivamente solo donde hace falta (ver notas de investigación sobre
# skeletor.pre.contract / mesh_map en el histórico de commits).
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


def collapse_short_edges(tree: nx.Graph, root: int, threshold: float) -> nx.Graph:
    """Colapsa cualquier arista de longitud < ``threshold``, sin importar el
    grado de sus extremos: fusiona ambos nodos en uno y reconecta los
    vecinos del nodo absorbido al superviviente.

    A diferencia de ``prune_redundant_joints`` (que solo toca nodos de
    grado 2 casi colineales), esto colapsa aristas cortas entre nodos de
    cualquier grado — pensado para geometría solapada/duplicada donde el
    esqueletizador genera dos nodos casi coincidentes en vez de una
    bifurcación real (p. ej. dos capas de malla en la misma zona).

    La raíz nunca se elimina: si una arista corta toca a la raíz, el otro
    extremo se fusiona hacia ella (conservando la posición de la raíz). En
    cualquier otro caso el nodo superviviente es el de id menor (elección
    arbitraria pero determinista) y conserva su propia posición sin
    promediar con la del nodo absorbido.

    Como la entrada es un árbol, colapsar una arista siempre produce otro
    árbol: dos nodos de un árbol nunca comparten más de un vecino en
    común, así que no puede aparecer ningún ciclo ni arista duplicada.
    """
    collapsed = tree.copy()
    changed = True
    while changed:
        changed = False
        for u, v in list(collapsed.edges):
            length = math.dist(collapsed.nodes[u]["pos"], collapsed.nodes[v]["pos"])
            if length < threshold:
                survivor = root if root in (u, v) else min(u, v)
                absorbed = v if survivor == u else u
                for neighbor in list(collapsed.neighbors(absorbed)):
                    if neighbor != survivor:
                        collapsed.add_edge(survivor, neighbor)
                collapsed.remove_node(absorbed)
                changed = True
                break  # el grafo cambió: reiniciar el escaneo
    return collapsed


def _point_to_line_distance(
    point: tuple[float, float, float],
    line_start: tuple[float, float, float],
    line_end: tuple[float, float, float],
) -> float:
    """Distancia perpendicular de ``point`` a la recta (infinita) que pasa
    por ``line_start`` y ``line_end``. Si el tramo tiene longitud ~0 (los
    dos extremos coinciden), se usa la distancia directa a ``line_start``.
    """
    chord = tuple(e - s for e, s in zip(line_end, line_start))
    chord_len_sq = sum(c * c for c in chord)
    if chord_len_sq < 1e-24:
        return math.dist(point, line_start)

    to_point = tuple(p - s for p, s in zip(point, line_start))
    t = sum(a * b for a, b in zip(to_point, chord)) / chord_len_sq
    projection = tuple(s + t * c for s, c in zip(line_start, chord))
    return math.dist(point, projection)


def _rdp_keep_mask(
    positions: list[tuple[float, float, float]], tolerance: float
) -> list[bool]:
    """Algoritmo Ramer-Douglas-Peucker sobre una polilínea 3D.

    Devuelve, para cada punto de ``positions``, si sobrevive a la
    simplificación. Los dos extremos siempre sobreviven.
    """
    n = len(positions)
    keep = [False] * n
    if n == 0:
        return keep
    keep[0] = True
    keep[-1] = True
    if n <= 2:
        return keep

    def recurse(start: int, end: int) -> None:
        if end <= start + 1:
            return
        max_dist = -1.0
        max_index = -1
        for i in range(start + 1, end):
            d = _point_to_line_distance(positions[i], positions[start], positions[end])
            if d > max_dist:
                max_dist = d
                max_index = i
        if max_dist > tolerance:
            keep[max_index] = True
            recurse(start, max_index)
            recurse(max_index, end)

    recurse(0, n - 1)
    return keep


def simplify_chains_rdp(tree: nx.Graph, root: int, tolerance: float) -> nx.Graph:
    """Simplifica los tramos rectos del árbol con Ramer-Douglas-Peucker.

    Sustituye el criterio anterior (evaluar el ángulo nodo a nodo en cada
    nodo de grado 2) por uno que opera sobre el TRAMO completo entre dos
    "puntos de anclaje": bifurcaciones (grado 3+), hojas (grado 1) o la
    raíz. Dentro de cada tramo, RDP conserva los puntos que se desvían más
    de ``tolerance`` (distancia perpendicular a la cuerda extremo-a-extremo
    del tramo) y descarta el resto — a diferencia del criterio por ángulo,
    esto detecta curvas suaves repartidas en varios nodos (donde cada
    ángulo individual puede estar muy por debajo de cualquier umbral
    razonable, pero el tramo en conjunto sigue siendo casi recto).

    No se tocan nunca los puntos de anclaje (bifurcaciones, hojas, raíz):
    solo se descartan nodos intermedios de grado 2 dentro de un tramo.
    """

    def is_anchor(node: int) -> bool:
        return node == root or tree.degree[node] != 2

    simplified = nx.Graph()
    simplified.add_nodes_from((n, dict(tree.nodes[n])) for n in tree.nodes if is_anchor(n))

    visited = {root}
    stack = [root]
    while stack:
        current = stack.pop()
        for neighbor in tree.neighbors(current):
            if neighbor in visited:
                continue

            # Recorrer el tramo desde `current` hasta el siguiente anclaje.
            chain = [current, neighbor]
            visited.add(neighbor)
            previous, node = current, neighbor
            while not is_anchor(node):
                next_node = next(n for n in tree.neighbors(node) if n != previous)
                chain.append(next_node)
                visited.add(next_node)
                previous, node = node, next_node
            stack.append(node)

            positions = [tree.nodes[n]["pos"] for n in chain]
            keep_mask = _rdp_keep_mask(positions, tolerance)
            kept_nodes = [n for n, keep in zip(chain, keep_mask) if keep]

            for kept_node in kept_nodes:
                if kept_node not in simplified:
                    simplified.add_node(kept_node, **tree.nodes[kept_node])
            for a, b in zip(kept_nodes, kept_nodes[1:]):
                simplified.add_edge(a, b)

    return simplified


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
