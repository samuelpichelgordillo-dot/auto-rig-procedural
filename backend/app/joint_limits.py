"""Módulo 3 — límites articulares: ejes de bisagra por articulación.

Cimiento antes de aplicar límites de ángulo de verdad dentro de
`ik_solver.solve_ik_ccd`: para cada articulación (hueso) de una
`LimbChain`, calcula su eje de bisagra NATURAL en bind pose — el eje
alrededor del cual esa articulación concreta se dobla de forma anatómica
(rodilla, tobillo, dedo...), no un eje global compartido por toda la
pata. Esta tarea NO aplica ningún límite de ángulo todavía y NO toca
`solve_ik_ccd` — eso depende de tener primero ejes verificados que
tengan sentido.

**Dos diseños descartados, con datos reales, antes de llegar al de
abajo** (no reintentar):

1. Un `side_axis` único compartido por toda la pata (análogo al de
   `gait_cycle.assign_limb_phase_offsets`): la alineación con el eje
   local real de cada articulación varía entre 10° y 89° en biped — un
   solo eje para toda la cadena no sirve, cada bisagra tiene su propia
   orientación.
2. Un plano de mejor ajuste (SVD) sobre TODOS los nodos de la cadena:
   funciona en cow (patas cortas, casi planas), pero falla en biped
   porque su cadena incluye falanges de un dedo del pie que no bisagran
   en el mismo plano que la rodilla — forzar un único plano por cadena
   ignora que distintos tramos de una misma pata pueden doblarse en
   planos distintos.

El diseño que sí funciona: un eje POR ARTICULACIÓN, derivado localmente
del ángulo entrante/saliente en esa articulación concreta (ver
`compute_hinge_axes`).
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np

from backend.app.ik_solver import chain_bone_names, name_to_node_index
from backend.app.limb_classification import LimbChain
from backend.app.skinning_quality import SkinData, compute_global_matrices, trs_to_matrix

DEFAULT_DEGENERATE_ANGLE_THRESHOLD_DEG = 10.0


def compute_hinge_axes(
    limb: LimbChain,
    hierarchy: dict[int, "int | None"],
    tree: nx.Graph,
    degenerate_angle_threshold_deg: float = DEFAULT_DEGENERATE_ANGLE_THRESHOLD_DEG,
) -> dict[str, np.ndarray]:
    """Eje de bisagra (mundo, bind pose) para cada hueso de la cadena de
    `limb`. Devuelve `bone_name -> eje unitario`; puede devolver MENOS
    entradas que huesos tiene la cadena — mejor omitir un hueso que
    inventarle un eje sin base geométrica real.

    Para un hueso "bone_P_C" (P = cabeza, C = cola — ver
    `ik_solver.chain_bone_names`), el eje de bisagra natural es la
    normal al plano que forman el segmento ENTRANTE (del abuelo GP al
    padre P) y el SALIENTE (de P a C): `cross(incoming, outgoing)`. Esa
    normal es, por construcción, el eje alrededor del cual una rotación
    en el plano incoming-outgoing lleva de uno a otro — exactamente el
    eje de flexión de una bisagra real (rodilla, codo, dedo...) en su
    postura de reposo.

    **Caso 1 — articulación excluida a propósito (cadera/hombro pegada
    a la raíz del esqueleto)**: si `GP = hierarchy[P]` es `None` (P, el
    padre de este hueso, ES la raíz del propio esqueleto — pasa con la
    cadena_root de cow y con la pata bat `chain_root=17`; con
    `chain_root=15` de bat, de un solo hueso, pasa para su ÚNICO hueso,
    así que esa pata entera queda sin ninguna entrada), no hay abuelo
    del que derivar un "entrante" — esta es la articulación MÁS
    proximal de la pata (cadera/hombro), anatómicamente más "bola" que
    "bisagra" (se mueve en más de un plano de forma natural), así que
    no le corresponde un único eje aquí. Se excluye del resultado a
    propósito, no es un caso que "falte cubrir".

    **Caso 2 — geometría casi degenerada (cadena casi estirada en bind
    pose)**: si el ángulo entre `incoming` y `outgoing` está fuera de
    `[degenerate_angle_threshold_deg, 180° - degenerate_angle_threshold_deg]`
    (casi recto, entrante y saliente casi colineales), `cross(incoming,
    outgoing)` es numéricamente inestable (su norma tiende a 0, y con
    ella la dirección del eje normalizado queda mal definida — un ruido
    de punto flotante minúsculo en las posiciones cambia el eje
    resultante drásticamente). Verificado con datos reales de biped: 3
    huesos con ángulos de 3.7°, 8.3° y 9.7° — casi completamente
    estirados. Estos huesos se marcan "pendientes de heredar" en vez de
    calcularles un eje directamente.

    **Herencia para huesos pendientes**: se recorre `chain_bone_names`
    (mismo orden pie-a-raíz) buscando hacia ambos lados, en pasos
    crecientes, el hueso RESUELTO más cercano dentro de la MISMA cadena,
    y se hereda su eje — asume que la orientación de bisagra no cambia
    bruscamente entre huesos vecinos de una misma pata, razonable para
    una cadena anatómica continua. Si un hueso no tiene NINGÚN vecino
    resuelto en toda la cadena (cadena entera degenerada, sin ningún
    doblez real en bind pose), se omite del resultado — no aparece en
    los 3 samples actuales, pero podría darse en un futuro modelo con
    una pata perfectamente recta; documentado como límite conocido en
    vez de inventar un eje arbitrario para ese caso.
    """
    bone_names = chain_bone_names(limb, hierarchy)

    resolved: dict[str, np.ndarray] = {}
    pending: list[str] = []

    for bone_name in bone_names:
        _, parent_str, child_str = bone_name.split("_")
        head_node = int(parent_str)
        tail_node = int(child_str)
        grandparent_node = hierarchy[head_node]

        if grandparent_node is None:
            continue  # Caso 1: cadera/hombro pegada a la raíz, se excluye a propósito.

        pos_head = np.array(tree.nodes[head_node]["pos"], dtype=np.float64)
        pos_tail = np.array(tree.nodes[tail_node]["pos"], dtype=np.float64)
        pos_grandparent = np.array(tree.nodes[grandparent_node]["pos"], dtype=np.float64)

        outgoing = pos_tail - pos_head
        incoming = pos_head - pos_grandparent

        outgoing_norm = np.linalg.norm(outgoing)
        incoming_norm = np.linalg.norm(incoming)
        cos_angle = np.clip(
            float(np.dot(incoming, outgoing)) / (incoming_norm * outgoing_norm), -1.0, 1.0
        )
        angle_deg = math.degrees(math.acos(cos_angle))

        if (
            angle_deg < degenerate_angle_threshold_deg
            or angle_deg > 180.0 - degenerate_angle_threshold_deg
        ):
            pending.append(bone_name)  # Caso 2: geometría casi degenerada.
            continue

        axis = np.cross(incoming, outgoing)
        resolved[bone_name] = axis / np.linalg.norm(axis)

    result = dict(resolved)
    for bone_name in pending:
        index = bone_names.index(bone_name)
        inherited = None
        for offset in range(1, len(bone_names)):
            left = index - offset
            right = index + offset
            if left >= 0 and bone_names[left] in resolved:
                inherited = resolved[bone_names[left]]
                break
            if right < len(bone_names) and bone_names[right] in resolved:
                inherited = resolved[bone_names[right]]
                break
        if inherited is not None:
            result[bone_name] = inherited
        # si no hay ningún vecino resuelto en toda la cadena, se omite
        # (cadena entera degenerada — ver docstring, límite conocido).

    return result


def hinge_axes_in_local_frame(
    skin_data: SkinData,
    hinge_axes: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Convierte cada eje de `compute_hinge_axes` (fijado en el
    espacio-mundo de la BIND POSE) al marco LOCAL de su hueso padre en
    bind pose. Mismas claves que `hinge_axes` de entrada, ninguna se
    pierde ni se añade.

    **Por qué hace falta**: los ejes de `compute_hinge_axes` están
    fijados en el espacio-mundo de la bind pose. En cuanto una pata
    empiece a moverse durante el ciclo de marcha, ese eje "congelado en
    el mundo" deja de ser válido — la bisagra de la rodilla debe girar
    CON el muslo (co-rotar con el hueso padre), no quedarse fija en una
    dirección de mundo absoluta. Expresar cada eje en el marco LOCAL del
    padre en bind pose permite recalcular la dirección de mundo válida
    en CUALQUIER pose futura: en cualquier iteración de CCD, el eje de
    mundo válido en ESE momento es
    ``rotación_global_actual_del_padre @ eje_local`` — verificado en
    `test_hinge_axis_co_rotates_with_ancestor_perturbation`, la prueba
    que de verdad importa aquí (no solo que el round-trip a bind pose
    funcione, sino que el eje siga siendo válido cuando algo más arriba
    en la jerarquía se mueve).

    Esta función SOLO hace la conversión de marco y la deja lista para
    usar; NO aplica ningún límite de ángulo ni toca `ik_solver.solve_ik_ccd`
    todavía — eso es la tarea siguiente, una vez el marco local esté
    verificado (esta misma tarea).

    `parent_index` (el nodo padre de cada hueso) es el mismo concepto
    que ya usa `solve_ik_ccd` en su propio bucle CCD
    (``skin_data.node_parent[node_index]``) — no se inventa uno nuevo
    aquí.
    """
    local_matrix_of = {
        node_index: trs_to_matrix(trs.translation, trs.rotation, trs.scale)
        for node_index, trs in skin_data.node_trs.items()
    }
    bind_globals = compute_global_matrices(
        skin_data.root_node_index, skin_data.node_children, local_matrix_of
    )

    name_to_index = name_to_node_index(skin_data)

    local_axes: dict[str, np.ndarray] = {}
    for bone_name, world_axis in hinge_axes.items():
        node_index = name_to_index[bone_name]
        parent_index = skin_data.node_parent[node_index]
        parent_rotation = bind_globals[parent_index][:3, :3]
        local_axis = parent_rotation.T @ world_axis
        local_axes[bone_name] = local_axis / np.linalg.norm(local_axis)

    return local_axes
