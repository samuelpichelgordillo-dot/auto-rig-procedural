"""Módulo 3 — clasificación de extremidades tipo "pata de apoyo".

Paso previo a cualquier cinemática (ciclos de marcha, IK): sobre el árbol
de esqueleto ya construido por ``build_skeleton_tree`` (Módulo 1),
identifica qué cadenas son candidatas a "pata" (necesitamos saberlo para
decidir qué huesos mover en fase y qué punta debe tocar el suelo) y dónde
pivota cada una respecto al tronco (cadera/hombro).

Nada de senos/cosenos ni IK aquí — solo clasificación geométrica estática
sobre la bind pose.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx

# Umbral relativo a la diagonal del bounding box, mismo criterio que el
# resto del pipeline (`densify_long_edges` usa 0.10, `collapse_short_edges`
# / `simplify_chains_rdp` usan 0.005) — nunca una unidad absoluta nueva.
# Elegido inspeccionando la distribución real de altura de TODOS los nodos
# (no solo las hojas) en los 3 samples, para separar "zona del pie/tobillo"
# de "zona de la espinilla/rodilla hacia arriba": el nodo interior más alto
# que sigue siendo genuinamente parte del pie/tobillo está a rel=0.058
# (biped, nodo intermedio entre el tobillo y un dedo pegado a él), y el
# siguiente nodo por encima de eso — ya claramente parte de la espinilla,
# no del pie — está a rel=0.087, con el "codo/rodilla" de referencia
# (Módulo 2) recién a rel=0.178. En cow y bat el hueco es aún mayor
# (siguiente nodo no-pie a rel≥0.10). 0.07 separa ambos grupos con margen
# en los 3 modelos sin necesidad de ajuste por modelo.
DEFAULT_GROUND_THRESHOLD_PCT = 0.07


@dataclass(frozen=True)
class LimbChain:
    """Una cadena candidata a "pata de apoyo"."""

    chain_root: int
    """Nodo donde la cadena se separa del tronco principal (cadera/hombro
    — el pivote que necesitará el ciclo de marcha)."""

    foot_leaf: int
    """Hoja representativa de contacto con el suelo: la de menor Y entre
    todas las agrupadas bajo este `chain_root` (si hay varias, p. ej.
    varios dedos del mismo pie)."""

    ground_leaves: tuple[int, ...]
    """Todas las hojas cercanas al suelo agrupadas bajo este `chain_root`
    (un pie con varios dedos produce varias hojas, una sola pata)."""


def _bbox_min_y_and_diagonal(tree: nx.Graph) -> tuple[float, float]:
    positions = [tree.nodes[n]["pos"] for n in tree.nodes]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    diagonal = math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return min(ys), diagonal


def _children_map(hierarchy: dict[int, "int | None"]) -> dict[int, list[int]]:
    children: dict[int, list[int]] = {}
    for node, parent in hierarchy.items():
        if parent is not None:
            children.setdefault(parent, []).append(node)
    return children


def _reaches_ground_map(
    root: int, children: dict[int, list[int]], ground_leaves: set[int]
) -> dict[int, bool]:
    """Para cada nodo, si algún descendiente suyo (o él mismo) está en
    ``ground_leaves``. Recorrido post-order desde la raíz."""
    reaches: dict[int, bool] = {}

    def visit(node: int) -> bool:
        result = node in ground_leaves
        for child in children.get(node, []):
            if visit(child):
                result = True
        reaches[node] = result
        return result

    visit(root)
    return reaches


def classify_support_limbs(
    tree: nx.Graph,
    root: int,
    hierarchy: dict[int, "int | None"],
    ground_threshold_pct: float = DEFAULT_GROUND_THRESHOLD_PCT,
) -> list[LimbChain]:
    """Identifica las cadenas candidatas a "pata de apoyo" del árbol.

    Criterio (ver también el docstring de ``DEFAULT_GROUND_THRESHOLD_PCT``
    para la calibración del umbral):

    1. Una hoja es "de suelo" si su altura (coordenada Y, ejes glTF) está
       a ``ground_threshold_pct`` de la diagonal del bounding box o menos
       por encima del Y mínimo global del modelo.
    2. Desde cada hoja de suelo, se sube por la jerarquía (padre a padre).
       En cada paso, de nodo `hijo` a `padre`, se comprueba si `padre`
       tiene algún OTRO hijo (hermano de `hijo`) cuyo subárbol también
       contenga una hoja de suelo — es decir, si `padre` es un punto
       donde de verdad divergen DOS patas distintas, no solo ruido de
       malla en la propia pata (una rama espuria de 1-2 saltos que
       también roza el suelo, p. ej. un dedo adicional pegado al tobillo
       en vez de al pie principal — visto en biped). Además `padre` debe
       NO estar cerca del suelo él mismo (si lo está, es solo el punto
       donde el propio pie se subdivide en dedos, no una bifurcación real
       de cadera/hombro). Se para en el primer `padre` que cumple ambas
       condiciones, o al llegar a la raíz del esqueleto (siempre se
       trata como tope, tenga o no otra rama que llegue al suelo — un
       modelo con una sola pata en todo el árbol es un caso degenerado
       que no aparece en los 3 samples, pero no debe romper el bucle).
       El ``chain_root`` resultante es el `hijo` en el último paso (el
       nodo justo por debajo de esa bifurcación real, en el lado de esta
       pata) — el hueso concreto de cadera/hombro de ESTA pata, no el
       nodo de cadera compartido por ambas.
    3. Varias hojas de suelo pueden compartir el mismo ``chain_root``
       (p. ej. los dedos de un mismo pie) — se agrupan en una única
       ``LimbChain``.

    Por qué esto excluye brazos (biped) y alas (bat) sin necesidad de
    ningún caso especial: en las 3 muestras, los modelos están en T-pose
    (o equivalente) — manos y puntas de ala quedan muy por encima del Y
    mínimo global (brazos de biped: rel≥0.53; ala de bat: rel≥0.33, ver
    docstring del umbral), así que sus hojas nunca entran en el paso 1 en
    absoluto. No hace falta excluirlos por nombre ni por posición en la
    jerarquía — el criterio geométrico ya los deja fuera.

    Nota sobre la calibración de ``DEFAULT_GROUND_THRESHOLD_PCT``: con un
    umbral de 0.05 (probado primero, calibrado solo mirando hojas) biped
    daba 3 grupos en vez de 2 — un dedo extra pegado al tobillo por un
    camino distinto al del resto del pie (nodo intermedio a rel=0.058,
    justo por encima de 0.05) quedaba fuera de "cerca del suelo" y su
    padre común con el resto del pie (rel=0.055) se interpretaba como una
    bifurcación real de cadera en vez de una subdivisión del propio pie.
    Subir el umbral a 0.07 (calibrado mirando la altura de TODOS los
    nodos, no solo las hojas — ver docstring de la constante) mete ese
    nodo dentro de "zona de pie" y resuelve el falso positivo sin afectar
    a cow ni a bat (sus siguientes nodos no-pie están mucho más lejos).
    """
    y_min, diagonal = _bbox_min_y_and_diagonal(tree)
    ground_threshold = ground_threshold_pct * diagonal

    def is_near_ground(node: int) -> bool:
        return tree.nodes[node]["pos"][1] - y_min <= ground_threshold

    ground_leaves = {
        n for n in tree.nodes if n != root and tree.degree[n] == 1 and is_near_ground(n)
    }

    children = _children_map(hierarchy)
    reaches_ground = _reaches_ground_map(root, children, ground_leaves)

    groups: dict[int, list[int]] = {}
    for leaf in ground_leaves:
        child = leaf
        parent = hierarchy[child]
        while True:
            siblings = [c for c in children.get(parent, []) if c != child]
            sibling_is_another_limb = any(reaches_ground[s] for s in siblings)
            if parent == root or (not is_near_ground(parent) and sibling_is_another_limb):
                chain_root = child
                break
            child, parent = parent, hierarchy[parent]
        groups.setdefault(chain_root, []).append(leaf)

    limb_chains = []
    for chain_root, leaves in groups.items():
        foot_leaf = min(leaves, key=lambda n: tree.nodes[n]["pos"][1])
        limb_chains.append(
            LimbChain(
                chain_root=chain_root,
                foot_leaf=foot_leaf,
                ground_leaves=tuple(sorted(leaves)),
            )
        )
    return limb_chains
