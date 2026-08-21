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

import math
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
# probados, pero algunas combinaciones concretas necesitan mucho más —
# el peor caso conocido (checkpoint 2026-08-20, cow `chain_root=3`,
# ciclo de marcha hacia atrás) necesita 724. Investigado con
# instrumentación directa del bucle (eje/ángulo elegido en cada
# sub-paso): NO es un problema de alcance ni de oscilación — el error
# baja de forma monótona y suave durante las 724 iteraciones (se
# aproximadamente reduce a la mitad cada ~100 pasadas: 0.026 -> 0.009 ->
# 0.004 -> 0.0016 -> 0.0007 -> 0.0003 -> 0.0001 -> converge). La causa
# real: para esta dirección concreta, los dos huesos más próximos a
# `chain_root` (`bone_3_29`, `bone_2_3`) contribuyen ángulos casi nulos
# en cada pasada (<1.2° y <1° respectivamente, frente a varios grados en
# la dirección que SÍ converge rápido) — CCD los da por "ya alineados"
# porque el ÁNGULO visto desde su propio pivote es pequeño, aunque el
# ERROR global de posición siga siendo grande; con esos dos huesos casi
# inmóviles, el hueso más distal (`bone_29_15`) tiene que cerrar casi
# todo el hueco él solo, y su alcance por pasada es limitado. Se probó
# invertir el orden de recorrido (raíz->pie en vez de pie->raíz) y
# amortiguar el ángulo por paso — ninguno de los dos arregla esto de
# forma general (invertir el orden ayuda a unas patas/fases y empeora
# otras; amortiguar solo hace la convergencia, ya lenta, más lenta
# todavía) — así que la solución no es cambiar el algoritmo, es darle el
# presupuesto de iteraciones que de verdad necesita: verificado sobre
# las 8 patas de los 3 modelos (30 fases cada una, con la amplitud de
# `safe_stride_amplitude_pct`) que ninguna necesita más de 724. 1000 da
# ~35% de margen sobre ese peor caso sin ser arbitrariamente alto; si una
# futura pata necesitara más, es una señal de que hace falta amortiguación
# adaptativa de verdad o migrar a FABRIK — mejora de una fase posterior,
# no de este cimiento.
DEFAULT_MAX_ITERATIONS = 1000
DEFAULT_TOLERANCE = 1e-4

# Tope FIJO y genérico de ángulo de flexión/extensión dentro de cada
# bisagra, respecto a la rotación de bind pose — igual para TODOS los
# huesos con eje de bisagra, no calibrado por hueso a propósito (ver
# docstring de `solve_ik_ccd`, sección `hinge_max_angle_deg`, para el
# hallazgo que motivó este valor: huesos de dedos que giraban 200-350°
# durante un ciclo de marcha normal sin ningún tope de ángulo).
DEFAULT_HINGE_MAX_ANGLE_DEG = 90.0


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
    hinge_axes_local: dict[str, np.ndarray] | None = None,
    hinge_max_angle_deg: float = DEFAULT_HINGE_MAX_ANGLE_DEG,
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

    ``hinge_axes_local`` (opcional, `None` por defecto — preserva el
    comportamiento exacto de antes de esta restricción): resultado de
    `joint_limits.hinge_axes_in_local_frame`, `bone_name -> eje unitario
    en el marco LOCAL del padre en bind pose`. Si un hueso de la cadena
    aparece en este dict, su rotación en cada sub-paso se restringe a
    girar SOLO alrededor de ese eje (bisagra de 1 grado de libertad) en
    vez de la rotación libre de 3 grados de libertad del camino sin
    restringir — el pivote de cadera/hombro (excluido de
    `compute_hinge_axes` por diseño) sigue rotando libre siempre, esté o
    no `hinge_axes_local` presente. Esta tarea SOLO restringe el EJE de
    rotación, no el ÁNGULO (rango de flexión/extensión dentro de esa
    bisagra) — eso queda pendiente para una tarea posterior a propósito,
    para no mezclar ambas cosas en un mismo cambio.

    Cálculo restringido, por hueso con eje conocido: (1)
    `current_axis = G_p_rotación @ hinge_axes_local[bone_name]`,
    normalizado — el eje de mundo válido EN ESTE MOMENTO, co-rota con el
    padre (ver checkpoint de `hinge_axes_in_local_frame` para por qué
    esto es necesario en vez de usar el eje de mundo de bind pose tal
    cual). (2) `to_effector`/`to_target` se proyectan sobre el plano
    perpendicular a `current_axis` (se les resta su propia componente a
    lo largo del eje) antes de normalizarlos — si alguna proyección
    tiene norma casi nula (los vectores pivote→pie/pivote→objetivo caen
    casi paralelos al propio eje de bisagra, sin componente de flexión
    que resolver desde este pivote), se salta el hueso esta pasada,
    igual que ya se salta cuando `effector_len`/`target_len` son casi
    nulos. (3) El ángulo se calcula CON SIGNO alrededor de
    `current_axis` (`arctan2(sin, cos)` con `sin = cross(...) ·
    current_axis`, `cos = dot(...)`) en vez del ángulo sin signo
    (`arccos`) del camino sin restringir — una bisagra necesita saber en
    qué SENTIDO girar sobre su único eje, no solo cuánto.

    ``hinge_max_angle_deg`` (default `DEFAULT_HINGE_MAX_ANGLE_DEG` =
    90.0): tope simétrico de flexión/extensión, `[-hinge_max_angle_deg,
    +hinge_max_angle_deg]` respecto a la rotación de BIND POSE de cada
    hueso, alrededor de su propio eje de bisagra — solo tiene efecto
    sobre huesos presentes en `hinge_axes_local` (con `hinge_axes_local
    is None`, sin cambio de comportamiento). Un valor FIJO, igual para
    todas las bisagras, deliberadamente NO calibrado por hueso: se probó
    medir el rango de ángulo que cada bisagra recorre durante un ciclo
    de marcha normal y calibrar el tope a partir de eso (mismo criterio
    que `DEFAULT_MAX_ITERATIONS` o `degenerate_angle_threshold_deg`) —
    se descartó porque varios huesos de DEDOS (p.ej. `bone_28_13` en
    cow, `bone_21_102` en biped) giran 200-350° sin ningún tope, que es
    precisamente el comportamiento anatómicamente absurdo que hay que
    cortar, no validar calibrando a partir de él. 90° es 2-3x el rango
    que ya usan de forma razonable los huesos que se comportan bien
    (`bone_31_10`: ~30°, `bone_3_29`: ~35°, `bone_17_22` de bat: ~36°),
    y muy por debajo de los giros de 200-350° que corta de raíz.

    Cada sub-paso restringido (con eje conocido) calcula, ANTES de
    aplicar la rotación: (1) el ángulo total acumulado actual respecto a
    bind pose (`joint_limits.signed_hinge_angle_deg`); (2) el ángulo
    total que CCD querría alcanzar sumando el incremento de esta pasada;
    (3) lo recorta a `[-hinge_max_angle_deg, hinge_max_angle_deg]`; (4)
    aplica solo el incremento AJUSTADO tras el recorte (la diferencia
    entre el total recortado y el total actual), no el que CCD pedía
    originalmente — si el hueso ya está en el límite y CCD querría
    seguir empujando en la misma dirección, el incremento ajustado es
    ~0 y se salta esta pasada para ese hueso, igual que cuando el ángulo
    sin restringir ya es ~0.
    """
    from backend.app.joint_limits import signed_hinge_angle_deg
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
        for bone_name, node_index in zip(chain_names, chain_indices):
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

            if hinge_axes_local is not None and bone_name in hinge_axes_local:
                current_axis = globals_[parent_index][:3, :3] @ hinge_axes_local[bone_name]
                current_axis = current_axis / np.linalg.norm(current_axis)

                to_effector_proj = to_effector - np.dot(to_effector, current_axis) * current_axis
                to_target_proj = to_target - np.dot(to_target, current_axis) * current_axis
                effector_proj_len = np.linalg.norm(to_effector_proj)
                target_proj_len = np.linalg.norm(to_target_proj)
                if effector_proj_len < 1e-9 or target_proj_len < 1e-9:
                    continue  # pivote→pie/objetivo casi paralelos al propio eje de bisagra
                to_effector_proj /= effector_proj_len
                to_target_proj /= target_proj_len

                sin_a = float(np.dot(np.cross(to_effector_proj, to_target_proj), current_axis))
                cos_a = float(np.clip(np.dot(to_effector_proj, to_target_proj), -1.0, 1.0))
                signed_angle = float(np.arctan2(sin_a, cos_a))
                if abs(signed_angle) < 1e-8:
                    continue

                old_local_for_angle = local_rotation.get(
                    node_index, skin_data.node_trs[node_index].rotation
                )
                current_total_deg = signed_hinge_angle_deg(
                    skin_data, node_index, old_local_for_angle, hinge_axes_local[bone_name]
                )
                new_total_deg = current_total_deg + math.degrees(signed_angle)
                new_total_clamped_deg = float(
                    np.clip(new_total_deg, -hinge_max_angle_deg, hinge_max_angle_deg)
                )
                actual_delta_rad = math.radians(new_total_clamped_deg - current_total_deg)
                if abs(actual_delta_rad) < 1e-8:
                    continue  # ya en el límite, CCD querría seguir empujando igual

                world_rotation = axis_angle_to_quat(current_axis, actual_delta_rad)
            else:
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
