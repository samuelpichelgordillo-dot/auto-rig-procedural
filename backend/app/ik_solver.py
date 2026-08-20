"""Módulo 3 — IK simple (CCD) para una sola pata.

Cimiento previo al ciclo de marcha: dado un `LimbChain` (Módulo 3,
`limb_classification.py`) y una posición objetivo 3D para su `foot_leaf`,
calcula las rotaciones que acercan el pie al objetivo, iterando desde el
hueso más cercano al pie hacia arriba hasta el `chain_root` (Cyclic
Coordinate Descent). Nada de coordinación entre patas, trayectoria
senoidal ni límites articulares todavía — eso es la tarea de después.

Reutiliza toda la infraestructura ya verificada en `skinning_quality.py`
(`SkinData`, `compute_global_matrices`, `trs_to_matrix`, `quat_multiply`,
`quat_conjugate`, `axis_angle_to_quat`, `matrix3_to_quat`) en vez de
duplicarla — el propio `apply_bone_rotation` de ese módulo no sirve
directamente aquí porque solo rota UN hueso a la vez y no necesita saber
"dónde está el pie ahora"; CCD necesita ambas cosas en cada sub-paso.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from backend.app.limb_classification import LimbChain
from backend.app.skinning_quality import (
    SkinData,
    axis_angle_to_quat,
    compute_global_matrices,
    matrix3_to_quat,
    quat_conjugate,
    quat_multiply,
    trs_to_matrix,
)

# CCD converge en pocas iteraciones para la mayoría de patas/objetivos
# probados (1-43, ver test_ik_solver.py), pero al menos una combinación
# concreta (cow, chain_root=27, flexión de -15° sobre X) necesitó 356 —
# comportamiento conocido de CCD "de libro" (sin amortiguación ni límites
# articulares): para ciertas geometrías de cadena y direcciones de
# objetivo converge mucho más despacio, sin que eso indique un bug (el
# error baja de forma monótona hasta el objetivo, solo que a pasos
# pequeños). 500 da margen sobre el peor caso observado sin ser
# arbitrariamente alto; si una futura pata necesitara más, es una señal
# de que hace falta amortiguación (damping) o una cota de ángulo por
# paso — mejora de una fase posterior, no de este cimiento.
DEFAULT_MAX_ITERATIONS = 500
DEFAULT_TOLERANCE = 1e-4


def _bone_name(parent_skel_node: int, child_skel_node: int) -> str:
    return f"bone_{parent_skel_node}_{child_skel_node}"


def chain_bone_names(limb: LimbChain, hierarchy: dict[int, "int | None"]) -> list[str]:
    """Nombres de hueso de la cadena, del más cercano al pie al más
    cercano a la raíz (orden foot-to-root, el que pide CCD aquí).

    Incluye el hueso que TERMINA en `chain_root` (el hueso concreto de
    cadera/hombro de esta pata — ver `limb_classification.LimbChain`,
    ese es justo el pivote más proximal que debe poder rotar la pata) y
    el hueso que empieza en `foot_leaf` (el último segmento, el que
    "sostiene" el pie). Para una pata de un solo hueso (chain_root ==
    foot_leaf, caso real en bat) devuelve una lista de un elemento.
    """
    names = []
    node = limb.foot_leaf
    while True:
        parent = hierarchy[node]
        names.append(_bone_name(parent, node))
        if node == limb.chain_root:
            break
        node = parent
    return names


def name_to_node_index(skin_data: SkinData) -> dict[str, int]:
    return {name: index for index, name in skin_data.node_name.items()}


def _local_matrix_for(
    skin_data: SkinData, node_index: int, local_rotation: dict[int, np.ndarray]
) -> np.ndarray:
    trs = skin_data.node_trs[node_index]
    rotation = local_rotation.get(node_index, trs.rotation)
    return trs_to_matrix(trs.translation, rotation, trs.scale)


def _all_global_matrices(
    skin_data: SkinData, local_rotation: dict[int, np.ndarray]
) -> dict[int, np.ndarray]:
    local_matrix_of = {
        node_index: _local_matrix_for(skin_data, node_index, local_rotation)
        for node_index in skin_data.node_trs
    }
    return compute_global_matrices(
        skin_data.root_node_index, skin_data.node_children, local_matrix_of
    )


def tip_bone_and_offset(
    skin_data: SkinData,
    limb: LimbChain,
    hierarchy: dict[int, "int | None"],
    bind_foot_position: np.ndarray,
) -> tuple[int, np.ndarray]:
    """Índice de nodo del último hueso de la cadena (el que "sostiene" el
    pie) y el offset local fijo, DENTRO del marco de ese hueso en bind
    pose, que representa la posición del pie. Se deriva de
    ``bind_foot_position`` porque un hueso hoja no tiene hijo en glTF que
    codifique su propia longitud (ver docstring de `solve_ik_ccd`).

    Expuesto como función pública (no solo uso interno de
    `solve_ik_ccd`) para que quien genere objetivos de prueba pueda
    calcular la posición del pie tras una rotación conocida vía
    `foot_position_given_rotations` — así los objetivos de test son
    alcanzables por construcción en vez de una posición 3D inventada.
    """
    chain_names = chain_bone_names(limb, hierarchy)
    name_to_index = name_to_node_index(skin_data)
    tip_bone_index = name_to_index[chain_names[0]]
    bind_globals = _all_global_matrices(skin_data, {})
    bind_foot_h = np.array([*bind_foot_position, 1.0], dtype=np.float64)
    local_tip_offset = np.linalg.inv(bind_globals[tip_bone_index]) @ bind_foot_h
    return tip_bone_index, local_tip_offset


def foot_position_given_rotations(
    skin_data: SkinData,
    tip_bone_index: int,
    local_tip_offset: np.ndarray,
    local_rotation: dict[int, np.ndarray],
) -> np.ndarray:
    """Posición mundo del pie dado un estado de rotaciones locales
    cualquiera (bind pose para los nodos ausentes de ``local_rotation``).
    """
    globals_ = _all_global_matrices(skin_data, local_rotation)
    return (globals_[tip_bone_index] @ local_tip_offset)[:3]


@dataclass
class IKResult:
    final_error: float
    """Distancia euclídea final entre el pie y el objetivo."""

    iterations_used: int
    """Nº de pasadas completas por la cadena (0 si ya estaba convergido
    antes de rotar nada — ver `verify_zero_displacement_converges_immediately`)."""

    converged: bool
    """``final_error < tolerance``."""

    local_rotations: dict[int, np.ndarray]
    """Rotación local (cuaternión, [x,y,z,w]) resultante para CADA nodo
    del esqueleto — bind pose para los huesos fuera de la cadena, la
    rotación calculada por CCD para los huesos de la cadena."""


def solve_ik_ccd(
    skin_data: SkinData,
    limb: LimbChain,
    hierarchy: dict[int, "int | None"],
    bind_foot_position: np.ndarray,
    target_position: np.ndarray,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    tolerance: float = DEFAULT_TOLERANCE,
) -> IKResult:
    """CCD (Cyclic Coordinate Descent) sobre una sola pata.

    ``bind_foot_position`` es la posición mundo (ejes glTF) de
    ``limb.foot_leaf`` en bind pose — viene del árbol de esqueleto
    (`tree.nodes[limb.foot_leaf]["pos"]` de `build_skeleton_tree`), no de
    la malla riggeada: el último hueso de la cadena es una hoja sin
    hijos, así que glTF no guarda su "longitud" en ningún sitio (a
    diferencia de un hueso intermedio, cuya longitud es la traslación de
    su hijo) — necesitamos ese punto de fuera para saber dónde está la
    punta del hueso, y con él calculamos (una sola vez, aquí) el offset
    local fijo dentro del propio hueso que representa la punta del pie:
    ese offset es lo que se transforma en cada iteración para saber dónde
    está el pie AHORA.

    Cada sub-paso de un hueso de la cadena (de pie a raíz, tal y como se
    pide):

    1. Recalcula las matrices globales de TODO el esqueleto con el
       estado actual de rotaciones (necesario porque el hueso anterior de
       esta misma pasada puede haber cambiado la orientación del padre).
    2. El pivote de este hueso es la posición mundo de su propia cabeza
       (la traslación de su matriz global — ver docstring de
       `chain_bone_names`: la traslación de la matriz global de un hueso
       "bone_P_C" da la posición del nodo P, no C, porque el origen local
       de un hueso ES su cabeza).
    3. Calcula la rotación en espacio MUNDO que llevaría el vector
       pivote→pie sobre el vector pivote→objetivo (eje = producto
       vectorial normalizado, ángulo = arco-coseno del producto escalar).
       Si los vectores ya están alineados, o son casi opuestos (eje
       indefinido), se salta este hueso en esta pasada — no hay una
       rotación de flexión única bien definida para 180°, y ese caso no
       aparece con los objetivos alcanzables usados en los tests.
    4. Esa rotación de mundo se convierte a una actualización de la
       rotación LOCAL del hueso: si G_p es la rotación global actual del
       padre y R_mundo la rotación a aplicar en espacio mundo,
       ``nueva_local = conj(G_p) · R_mundo · G_p · local_actual``
       (composición de cuaterniones) — porque rotación_global(hueso) =
       G_p · rotación_local(hueso), y queremos que la NUEVA
       rotación_global sea ``R_mundo · rotación_global_actual``.

    Auto-chequeo obligatorio antes de fiarse de esto para nada más: ver
    `verify_zero_displacement_converges_immediately`.
    """
    chain_names = chain_bone_names(limb, hierarchy)
    name_to_index = name_to_node_index(skin_data)
    chain_indices = [name_to_index[name] for name in chain_names]
    tip_bone_index, local_tip_offset = tip_bone_and_offset(
        skin_data, limb, hierarchy, bind_foot_position
    )

    local_rotation: dict[int, np.ndarray] = {}
    target_position = np.asarray(target_position, dtype=np.float64)

    def effector_and_globals() -> tuple[np.ndarray, dict[int, np.ndarray]]:
        globals_ = _all_global_matrices(skin_data, local_rotation)
        effector = foot_position_given_rotations(
            skin_data, tip_bone_index, local_tip_offset, local_rotation
        )
        return effector, globals_

    effector, globals_ = effector_and_globals()
    error = float(np.linalg.norm(effector - target_position))
    iterations_used = 0

    while error >= tolerance and iterations_used < max_iterations:
        iterations_used += 1
        for node_index in chain_indices:
            parent_index = skin_data.node_parent[node_index]
            pivot = globals_[node_index][:3, 3]

            to_effector = effector - pivot
            to_target = target_position - pivot
            effector_len = np.linalg.norm(to_effector)
            target_len = np.linalg.norm(to_target)
            if effector_len < 1e-9 or target_len < 1e-9:
                continue
            to_effector /= effector_len
            to_target /= target_len

            dot = float(np.clip(np.dot(to_effector, to_target), -1.0, 1.0))
            angle = float(np.arccos(dot))
            if angle < 1e-8:
                continue

            axis = np.cross(to_effector, to_target)
            axis_norm = np.linalg.norm(axis)
            if axis_norm < 1e-9:
                continue  # vectores ~antiparalelos, eje de rotación indefinido

            world_rotation = axis_angle_to_quat(axis / axis_norm, angle)
            parent_global_rotation = matrix3_to_quat(globals_[parent_index][:3, :3])
            old_local = local_rotation.get(node_index, skin_data.node_trs[node_index].rotation)

            new_local = quat_multiply(
                quat_multiply(
                    quat_multiply(quat_conjugate(parent_global_rotation), world_rotation),
                    parent_global_rotation,
                ),
                old_local,
            )
            local_rotation[node_index] = new_local / np.linalg.norm(new_local)

            effector, globals_ = effector_and_globals()

        error = float(np.linalg.norm(effector - target_position))

    full_local_rotations = {
        node_index: local_rotation.get(node_index, trs.rotation)
        for node_index, trs in skin_data.node_trs.items()
    }
    return IKResult(
        final_error=error,
        iterations_used=iterations_used,
        converged=error < tolerance,
        local_rotations=full_local_rotations,
    )


def verify_zero_displacement_converges_immediately(
    skin_data: SkinData,
    limb: LimbChain,
    hierarchy: dict[int, "int | None"],
    bind_foot_position: np.ndarray,
    tolerance: float = DEFAULT_TOLERANCE,
) -> float:
    """Auto-chequeo obligatorio antes de usar `solve_ik_ccd` para nada
    más: un objetivo que coincide EXACTAMENTE con la posición del pie en
    bind pose debe converger en la primera pasada — de hecho, sin
    necesitar ninguna (``iterations_used == 0``), porque el error ya es
    ~0 antes de rotar nada. Si esto falla, el bug está en cómo se deriva
    ``local_tip_offset`` o en la composición jerárquica de matrices, no
    en el algoritmo CCD en sí. Devuelve el error final; lanza
    AssertionError si no se cumple.
    """
    result = solve_ik_ccd(
        skin_data,
        limb,
        hierarchy,
        bind_foot_position,
        target_position=bind_foot_position,
        max_iterations=1,
        tolerance=tolerance,
    )
    if result.iterations_used != 0 or result.final_error >= tolerance:
        raise AssertionError(
            f"Objetivo = posición de bind pose no converge sin rotar: "
            f"iterations_used={result.iterations_used}, error={result.final_error} "
            f">= tolerancia {tolerance}. Bug antes del propio CCD."
        )
    return result.final_error
