"""Módulo 4 — micro-movimientos: identificación de apéndices (orejas,
cola, dedos) sobre nodos NO clasificados como pata de apoyo.

Heurístico geométrico verificado contra los 3 samples conocidos
(cow/biped/bat), en la misma línea que `limb_classification.py` — NO es
una garantía general: un modelo con proporciones muy distintas (cola muy
corta, alas muy pequeñas, orejas muy grandes, una mano con solo 2 dedos)
podría confundir alguno de estos criterios. Documentado explícitamente
en cada función qué se comprobó y qué no.

**Re-derivación propia de los "hallazgos" antes de escribir esta pieza**
(el director había investigado esto en su propio sandbox, mismo repo,
mismos GLB — pero no estaba checkpointeado en CLAUDE.md, así que se
verificó desde cero en vez de darlo por bueno):

- cow: dos hojas no-pata en `x=-0.986/x=+0.986` (mismo `y=4.792`,
  `z=3.955`) SÍ son un par casi-espejo exacto → orejas. Una cadena de 4
  huesos (`[11, 32, 4, 23, 2]`) en el lado opuesto del cuerpo
  (`z=-1.64`, altura baja `y=1.673`) es, de las cadenas restantes, la
  más larga con margen claro (6.022 vs 3.842 de la segunda, ratio
  1.57x) → cola.
- biped: 3 hubs no-pata con ≥3 hijos no-pata y cadenas cortas
  (nodos 45, 262, 264) — pero el nodo 45 (`pos≈(0,1.68,0)`, casi en el
  eje central del cuerpo) resultó ser un falso positivo (probablemente
  boca/mandíbula, NO una mano — está a solo 0.31 de distancia de
  camino de la raíz, mientras que 262/264 están a 0.93-0.99, un salto
  de casi 3x). Filtro añadido (ver `classify_appendages`) para excluirlo
  sin excluir manos reales. **262 y 264 son la MISMA mano** (izquierda,
  x≈-0.8 ambos, a solo 0.07 de distancia entre sí — 264 es
  probablemente el pulgar u otro dedo con una bifurcación extra que
  `_simple_chain` no fusiona con el resto). La mano DERECHA (dedos con
  `x` positivo, ~0.8-0.91, verificados: nodos 112/259 bajo hub 150,
  280/281 bajo hub 151, 301/303 bajo hub 182, más 184 y 255 sueltos con
  1 solo hijo cada uno) NO se agrupa bajo ningún hub con ≥3 hijos
  directos — sus dedos se reparten en varios hubs anidados de 1-2 hijos
  cada uno (asimetría real del propio pipeline de esqueletización,
  misma naturaleza que otras asimetrías izquierda/derecha ya
  documentadas en checkpoints de Módulo 1/3). Resultado: `fingers` solo
  captura la mano izquierda — cumple el requisito de la tarea ("al
  menos una mano, no asumas cuántas"), pero es una limitación real y
  documentada, no una garantía de encontrar todas las manos de
  cualquier modelo futuro.
- bat: el par de hojas en posiciones aparentemente espejo (nodos 25/26,
  `x=∓0.96`, `y≈4.27`, `z≈0.69`) SÍ suben >2 unidades verticales desde
  la raíz del esqueleto (2.19/2.16, frente a un alcance de pata de solo
  0.365) — confirmado que son puntas de ala, no orejas. El filtro de
  desplazamiento (ver más abajo) las excluye correctamente.

**Hallazgo 2, encontrado durante la implementación (no en la
investigación previa)**: buscar pares "casi espejo en X" entre TODAS
las hojas candidatas del modelo (sin más restricción) funciona en cow
porque, fuera de las 4 patas, apenas hay estructura no-pata (orejas +
cola + 1-2 detalles sueltos). En biped NO funciona — un biped completo
es simétrico izquierda-derecha en casi CUALQUIER detalle de malla
(mandíbula, nudillos, dedos sueltos no agrupados en el hub de la mano),
así que una búsqueda de espejo sin restricción encontró **26 pares
espurios** en la primera versión de este código (verificado, no
hipotético). La corrección: restringir la búsqueda de pares a hojas que
comparten el MISMO hub — dos ramas de UNA bifurcación bilateral
concreta (verificado: las orejas de cow comparten hub=2 exactamente),
no cualquier par de estructuras que caigan en posiciones especulares
por la simetría general del cuerpo. Limitación conocida: si la
asimetría del propio pipeline de esqueletización (ya documentada en
checkpoints de Módulo 1) separase las dos ramas de un par bilateral
real en dos hubs ligeramente distintos, este criterio no las
encontraría — no ocurre en los 3 samples, pero no es una garantía
general.

**Corrección de escala respecto a la sugerencia inicial de la tarea**:
se sugería usar `gait_cycle.max_chain_bone_length` (longitud de arco de
la pata, siguiendo el hueso doblado) como referencia de escala para el
filtro de desplazamiento de orejas. Verificado que NO discrimina: en
bat, la punta de ala menos extrema tiene un desplazamiento de 0.738,
que es *menor* en proporción a `max_chain_bone_length` (ratio 0.451)
que las propias orejas de cow (ratio 0.507-0.602) — ningún umbral único
podría admitir las orejas de cow y rechazar las alas de bat con esa
referencia. Cambiado a la distancia en línea recta `chain_root_position
-> foot_leaf_position` ("reach", ya usada en `gait_cycle.py` y
`test_gait_cycle.py`) — comparación coherente porque el propio
desplazamiento del apéndice también se mide en línea recta (hoja menos
punto de unión), no como longitud de arco. Con "reach" sí hay un hueco
claro: orejas de cow en 0.66-0.69x, alas de bat en 2.02-3.38x — el
1.5x sugerido por la tarea separa ambos grupos con margen.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np

from backend.app.limb_classification import DEFAULT_GROUND_THRESHOLD_PCT, LimbChain

# --- fingers ---
DEFAULT_FINGER_MIN_NON_LIMB_CHILDREN = 3
# "Longitud" de una cadena candidata a dedo = nº de ARISTAS (huesos), no
# de nodos — verificado con la mano real de biped (hub 262): sus 5
# cadenas tienen 1-2 aristas cada una, hub 264 (parte de la misma mano,
# nido de bifurcación adicional) 1-2 aristas también.
DEFAULT_FINGER_MAX_CHAIN_EDGES = 3
# Filtro añadido tras encontrar un falso positivo real (nodo 45 de
# biped, ver docstring del módulo): un hub de dedos de verdad debe estar
# "lejos" de la raíz del esqueleto (al final de un brazo/muñeca), no
# cerca del eje central del cuerpo. Distancia en línea recta hub->raíz,
# relativa a la diagonal del bounding box (mismo criterio de escala que
# `limb_classification.DEFAULT_GROUND_THRESHOLD_PCT`). Calibrado: el
# falso positivo da 0.0785, las dos manos reales de biped dan 0.30-0.32
# — 0.15 separa ambos con margen.
DEFAULT_FINGER_MIN_DISTAL_FRACTION = 0.15

# --- ears ---
# Tolerancia para "casi espejo en X" / "Y parecido" / "Z parecido",
# relativa a la diagonal del bounding box. Las orejas de cow coinciden
# EXACTAMENTE (diferencia 0.000 en las 3 componentes) así que este valor
# no se pudo calibrar contra un segundo ejemplo real — deliberadamente
# generoso para no depender de una simetría perfecta en otros modelos,
# pero lo bastante pequeño para no emparejar estructuras distintas por
# accidente (verificado que no genera pares espurios en los 3 samples).
DEFAULT_EAR_MIRROR_TOLERANCE_FRACTION = 0.05
# Ver docstring del módulo: escala = reach (línea recta chain_root ->
# foot_leaf) de la pata de MAYOR alcance del propio modelo, no
# `max_chain_bone_length`.
DEFAULT_EAR_MAX_DISPLACEMENT_TO_REACH_RATIO = 1.5
# Longitud física de cadena (suma de aristas) del candidato más largo
# entre el más corto de un par candidato a oreja. Las orejas de cow
# distan un 1.52x entre sí (2.535 vs 3.842) pese a ser una simetría
# real del modelo — el propio pipeline de esqueletización no es
# perfectamente simétrico rama a rama (ver checkpoints de Módulo 1), así
# que este umbral debe tener margen sobre eso. 2.0 separa esa pareja
# real de la única pareja-espejo espuria encontrada en bat (nodos 1/10,
# ratio ~3.0, ya excluida además por el filtro de desplazamiento).
DEFAULT_EAR_MAX_LENGTH_RATIO = 2.0

# --- tail ---
DEFAULT_TAIL_MIN_OUTLIER_RATIO = 1.3


def limb_chain_nodes(limbs: list[LimbChain], hierarchy: dict[int, "int | None"]) -> set[int]:
    """Todos los nodos de TODAS las patas de `limbs`, cada una recorrida
    de `foot_leaf` a `chain_root` acumulando nodos por el camino — el
    mismo bucle que ya se reimplementaba ad-hoc en varios scripts de
    depuración de Módulo 3 (`_plot_constrained_pose_debug.py` y otros
    usan el equivalente vía `ik_solver.chain_bone_names`; esta función
    da directamente el conjunto de NODOS, sin pasar por nombres de
    hueso, que es lo que necesita este módulo).

    Nota: usa `foot_leaf` (el representante único que ya anima
    `solve_ik_ccd`/`solve_gait_cycle_pose`), NO todos los
    `ground_leaves` de la pata — mismo criterio que el resto del
    proyecto (`ik_solver.chain_bone_names`), así que los OTROS dedos del
    pie de una pata con varios `ground_leaves` (p. ej. biped,
    `chain_root=5` tiene 8 `ground_leaves` pero solo 1 `foot_leaf`)
    quedan FUERA de este conjunto y aparecen como hojas no-pata más
    abajo — `classify_appendages` los excluye por separado, filtrando
    por altura cercana al suelo (son restos del mismo pie, no apéndices
    nuevos), no confundiéndolos con dedos de mano.
    """
    nodes: set[int] = set()
    for limb in limbs:
        node = limb.foot_leaf
        while True:
            nodes.add(node)
            if node == limb.chain_root:
                break
            node = hierarchy[node]
    return nodes


def _bbox_stats(tree: nx.Graph) -> tuple[float, float]:
    positions = [tree.nodes[n]["pos"] for n in tree.nodes]
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    diagonal = math.dist((min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)))
    return min(ys), diagonal


def _simple_chain(
    tree: nx.Graph, hierarchy: dict[int, "int | None"], non_limb: set[int], leaf: int
) -> list[int]:
    """Sube desde `leaf` (hoja no-pata, grado 1) por sus ancestros
    no-pata hasta el primer nodo con >=2 hijos no-pata, o hasta que el
    padre deje de ser no-pata (raíz de patas incluida, o la propia raíz
    del esqueleto). Devuelve la cadena hoja-a-hub, ambos extremos
    incluidos."""
    chain = [leaf]
    node = leaf
    while True:
        parent = hierarchy[node]
        if parent is None or parent not in non_limb:
            break
        chain.append(parent)
        non_limb_children = [
            c for c in tree.neighbors(parent) if c in non_limb and hierarchy.get(c) == parent
        ]
        if len(non_limb_children) >= 2:
            break
        node = parent
    return chain


def _chain_physical_length(tree: nx.Graph, chain: list[int]) -> float:
    return sum(
        math.dist(tree.nodes[chain[i]]["pos"], tree.nodes[chain[i + 1]]["pos"])
        for i in range(len(chain) - 1)
    )


def classify_appendages(
    tree: nx.Graph,
    root: int,
    hierarchy: dict[int, "int | None"],
    limbs: list[LimbChain],
) -> dict[str, list[list[int]]]:
    """Clasifica los apéndices no-pata de un esqueleto en
    `{"ears": [...], "tail": [...], "fingers": [...]}` — cada valor es
    una lista de cadenas (hoja-a-hub, ambos extremos incluidos);
    CUALQUIERA de las 3 claves puede quedar vacía (nunca se inventa un
    candidato débil solo por rellenar, ver umbrales de cada paso).

    **Paso 0 — exclusión de restos de dedos del pie**: cualquier hoja
    no-pata cuya altura Y esté dentro de `DEFAULT_GROUND_THRESHOLD_PCT`
    (reutilizado de `limb_classification.py`, mismo criterio de "cerca
    del suelo") de la Y mínima del modelo se excluye de TODA
    clasificación de apéndices, antes de construir ninguna cadena.
    Hallazgo real que motivó este paso: biped tiene patas con varios
    `ground_leaves` pero solo 1 `foot_leaf` por pata (ver
    `limb_chain_nodes`) — los otros dedos del mismo pie (hasta 7 nodos
    por pata en biped) aparecen como "hojas no-pata" sin este filtro, y
    varios pares son casi-espejo exacto en X entre el pie izquierdo y el
    derecho (p. ej. nodos 2/179, diferencia 0.000 en las 3 coordenadas)
    — sin este filtro se clasificarían como 6 pares de "orejas" en los
    pies, claramente incorrecto. Verificado que este filtro NO excluye
    ningún apéndice real de los 3 modelos (orejas/cola de cow y manos de
    biped están muy por encima de este umbral de altura).

    **Paso 1 — cadenas simples**: para cada hoja no-pata superviviente
    del paso 0, `_simple_chain` sube por ancestros no-pata hasta la
    primera bifurcación no-pata real (o hasta que el padre deja de ser
    no-pata).

    **Paso 2 — dedos**: se agrupan las cadenas por su `hub` (último
    nodo). Cualquier hub con >=`DEFAULT_FINGER_MIN_NON_LIMB_CHILDREN`
    cadenas, TODAS con <=`DEFAULT_FINGER_MAX_CHAIN_EDGES` aristas, Y a
    una distancia en línea recta del `root` >=
    `DEFAULT_FINGER_MIN_DISTAL_FRACTION` de la diagonal del modelo (ver
    docstring del módulo — filtro añadido tras encontrar un falso
    positivo real cerca del eje central del cuerpo en biped), se
    clasifica como grupo de "fingers" — TODAS sus cadenas se añaden.
    Los nodos de estas cadenas se retiran del resto del proceso.

    **Paso 3 — orejas**: entre las cadenas restantes, se filtran las que
    tengan un desplazamiento (distancia hoja-hub en línea recta) por
    encima de `DEFAULT_EAR_MAX_DISPLACEMENT_TO_REACH_RATIO` veces el
    `reach` (línea recta chain_root->foot_leaf) de la pata de MAYOR
    alcance del propio modelo — filtro que excluye estructuras
    demasiado grandes para ser una oreja (alas, p. ej.). Entre las
    supervivientes, se buscan PARES QUE COMPARTEN EL MISMO HUB (ver
    "Hallazgo 2" del docstring del módulo — restricción añadida tras
    encontrar 26 pares espurios en biped buscando espejo sin esta
    restricción, por la simetría general del cuerpo): X casi opuesta
    (mismo valor absoluto dentro de `DEFAULT_EAR_MIRROR_TOLERANCE_FRACTION`
    de la diagonal, signos opuestos), Y y Z parecidos (misma tolerancia),
    y longitud física de cadena parecida (ratio <=
    `DEFAULT_EAR_MAX_LENGTH_RATIO`). Búsqueda voraz dentro de cada grupo
    de hub: el primer par que cumple se marca como oreja y ambos nodos
    se retiran del pool; no se reutiliza ningún nodo en dos pares.

    **Paso 4 — cola**: entre las cadenas que quedan (ni dedos ni
    orejas — el filtro de desplazamiento del paso 3 NO se aplica aquí,
    una cola puede ser perfectamente larga), se ordena por longitud
    física de cadena. Si hay >=2 candidatas y la más larga supera a la
    segunda por >= `DEFAULT_TAIL_MIN_OUTLIER_RATIO`, esa es la cola. Si
    solo queda 1 candidata (nada con quien compararla), se acepta
    igualmente como cola — no hay ambigüedad posible con un solo
    candidato. Si no hay ninguna candidata, o hay >=2 sin un ganador
    claro, `tail` queda vacío — mejor vacío que una cola inventada.
    """
    y_min, diagonal = _bbox_stats(tree)
    ground_cutoff = y_min + DEFAULT_GROUND_THRESHOLD_PCT * diagonal

    limb_nodes = limb_chain_nodes(limbs, hierarchy)
    non_limb = set(tree.nodes) - limb_nodes

    candidate_leaves = [
        n
        for n in non_limb
        if tree.degree(n) == 1 and tree.nodes[n]["pos"][1] > ground_cutoff
    ]

    chains_by_leaf = {leaf: _simple_chain(tree, hierarchy, non_limb, leaf) for leaf in candidate_leaves}

    chains_by_hub: dict[int, list[int]] = {}
    for leaf, chain in chains_by_leaf.items():
        chains_by_hub.setdefault(chain[-1], []).append(leaf)

    root_pos = np.array(tree.nodes[root]["pos"], dtype=np.float64)

    fingers: list[list[int]] = []
    used_leaves: set[int] = set()
    for hub, leaves_here in chains_by_hub.items():
        if len(leaves_here) < DEFAULT_FINGER_MIN_NON_LIMB_CHILDREN:
            continue
        chains_here = [chains_by_leaf[leaf] for leaf in leaves_here]
        if any(len(c) - 1 > DEFAULT_FINGER_MAX_CHAIN_EDGES for c in chains_here):
            continue
        hub_pos = np.array(tree.nodes[hub]["pos"], dtype=np.float64)
        distal_fraction = float(np.linalg.norm(hub_pos - root_pos)) / diagonal
        if distal_fraction < DEFAULT_FINGER_MIN_DISTAL_FRACTION:
            continue
        fingers.extend(chains_here)
        used_leaves.update(leaves_here)

    remaining_after_fingers = [leaf for leaf in candidate_leaves if leaf not in used_leaves]

    max_reach = max(
        (
            float(
                np.linalg.norm(
                    np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
                    - np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
                )
            )
            for limb in limbs
        ),
        default=0.0,
    )

    def displacement(leaf: int) -> float:
        chain = chains_by_leaf[leaf]
        leaf_pos = np.array(tree.nodes[chain[0]]["pos"], dtype=np.float64)
        hub_pos = np.array(tree.nodes[chain[-1]]["pos"], dtype=np.float64)
        return float(np.linalg.norm(leaf_pos - hub_pos))

    ear_eligible = [
        leaf
        for leaf in remaining_after_fingers
        if max_reach <= 0 or displacement(leaf) / max_reach <= DEFAULT_EAR_MAX_DISPLACEMENT_TO_REACH_RATIO
    ]

    # Restringido a pares que comparten el MISMO hub (ver docstring del
    # módulo, "hallazgo 2" de esta tarea): dos ramas de una misma
    # bifurcación bilateral, no cualquier par de estructuras que por
    # casualidad caigan en posiciones especulares en un cuerpo ya de por
    # sí simétrico izquierda-derecha (un biped completo lo es en casi
    # todos sus detalles, no solo en las orejas).
    eligible_by_hub: dict[int, list[int]] = {}
    for leaf in ear_eligible:
        eligible_by_hub.setdefault(chains_by_leaf[leaf][-1], []).append(leaf)

    ears: list[list[int]] = []
    ear_used: set[int] = set()
    mirror_tol = DEFAULT_EAR_MIRROR_TOLERANCE_FRACTION * diagonal
    for hub_leaves in eligible_by_hub.values():
        if len(hub_leaves) < 2:
            continue
        for i, leaf_a in enumerate(hub_leaves):
            if leaf_a in ear_used:
                continue
            pos_a = tree.nodes[leaf_a]["pos"]
            len_a = _chain_physical_length(tree, chains_by_leaf[leaf_a])
            for leaf_b in hub_leaves[i + 1 :]:
                if leaf_b in ear_used:
                    continue
                pos_b = tree.nodes[leaf_b]["pos"]
                if pos_a[0] == 0.0 or pos_b[0] == 0.0 or (pos_a[0] > 0) == (pos_b[0] > 0):
                    continue  # deben tener signos opuestos en X (no ambos en el eje central)
                if abs(abs(pos_a[0]) - abs(pos_b[0])) > mirror_tol:
                    continue
                if abs(pos_a[1] - pos_b[1]) > mirror_tol or abs(pos_a[2] - pos_b[2]) > mirror_tol:
                    continue
                len_b = _chain_physical_length(tree, chains_by_leaf[leaf_b])
                shorter, longer = sorted([len_a, len_b])
                if shorter <= 0 or longer / shorter > DEFAULT_EAR_MAX_LENGTH_RATIO:
                    continue
                ears.append(chains_by_leaf[leaf_a])
                ears.append(chains_by_leaf[leaf_b])
                ear_used.add(leaf_a)
                ear_used.add(leaf_b)
                break

    remaining_after_ears = [leaf for leaf in remaining_after_fingers if leaf not in ear_used]

    tail: list[list[int]] = []
    if remaining_after_ears:
        lengths = [
            (leaf, _chain_physical_length(tree, chains_by_leaf[leaf])) for leaf in remaining_after_ears
        ]
        lengths.sort(key=lambda item: item[1], reverse=True)
        if len(lengths) == 1:
            tail = [chains_by_leaf[lengths[0][0]]]
        else:
            longest_leaf, longest_len = lengths[0]
            _, second_len = lengths[1]
            if second_len <= 0 or longest_len / second_len >= DEFAULT_TAIL_MIN_OUTLIER_RATIO:
                tail = [chains_by_leaf[longest_leaf]]

    return {"ears": ears, "tail": tail, "fingers": fingers}
