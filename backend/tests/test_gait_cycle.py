"""Módulo 3 — trayectoria del pie de una sola pata a lo largo de un ciclo.

Cubre `foot_target_at_phase` en sí (periodicidad, suelo nunca traspasado,
validación de `stride_direction`), `safe_stride_amplitude_pct` (recorte
de amplitud solo cuando hace falta, sin tocar las patas que ya iban
bien) y, para varias patas concretas, que `ik_solver.solve_ik_ccd`
converge a los objetivos que genera en muchos puntos repartidos por todo
el ciclo — no solo unos pocos, precisamente para cubrir los extremos del
rango de movimiento donde CCD puede converger más lento (ver checkpoint
en CLAUDE.md).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app.gait_cycle import (
    assign_limb_phase_offsets,
    compute_safe_amplitudes,
    detect_stride_direction,
    foot_target_at_phase,
    max_chain_bone_length,
    safe_stride_amplitude_pct,
    solve_gait_cycle_pose,
    surprise_pose_phase_offsets,
    verify_never_below_ground,
    verify_phase_periodicity,
)
from backend.app.ik_solver import (
    DEFAULT_MAX_ITERATIONS,
    chain_bone_names,
    foot_position_given_rotations,
    name_to_node_index,
    solve_ik_ccd,
    tip_bone_and_offset,
)
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import read_skin_data

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_MODELS = ["cow", "biped", "bat"]

# Dirección de zancada horizontal usada para verificar la trayectoria
# contra el solver de IK. NO se calcula automáticamente (eso depende de
# saber qué es "delante" del modelo, tarea de coordinación multi-pata
# posterior) — aquí es una elección arbitraria documentada. Se probó
# primero el eje X (1,0,0): funciona sin problema para las patas
# elegidas de cow y biped, pero para la pata elegida de bat una fase
# concreta necesitaba 606 iteraciones — por encima del presupuesto de
# `DEFAULT_MAX_ITERATIONS` (500). Con el eje Z (0,0,1) las patas elegidas
# convergen con margen cómodo — es la que se usa aquí.
_STRIDE_DIRECTION = np.array([0.0, 0.0, 1.0])

_NUM_PHASE_SAMPLES = 30

# --- Qué patas se prueban contra el solver de IK, y por qué ---
#
# TODAS las patas de los 3 modelos (8 en total) — ya no vale probar solo
# una por modelo, precisamente porque `chain_root=3` (checkpoint
# 2026-08-21) reveló un problema DIRECCIONAL que el test anterior no
# habría detectado con una sola pata "representativa" por modelo.
#
# id, modelo, chain_root, ¿ya devuelve amplitud SIN recortar de
# `safe_stride_amplitude_pct` (0.3)?, techo de iteraciones esperado con
# margen generoso (no un valor exacto — solo para detectar una
# regresión real, "mismo orden de magnitud" que pide la tarea).
#
# - cow chain_root=31 / chain_root=33: ya convergían con margen (158 y
#   83 de 1000 iteraciones) sin recorte de amplitud.
# - cow chain_root=27: con amplitud fija 0.3 pedía objetivos hasta el
#   92% de su longitud física máxima en varias fases y no convergía
#   (checkpoint 2026-08-20). `safe_stride_amplitude_pct` la recorta a
#   ≈0.093; converge en las 30 fases con 325 de 1000 iteraciones.
# - cow chain_root=3: el hallazgo de ESTA tarea — con amplitud 0.3 SIN
#   recortar (el % de longitud máxima pedido, ~81%, no dispara el
#   recorte de `safe_stride_amplitude_pct`) la fase "zancada hacia
#   atrás" (phase≈0.5) necesita hasta 724 iteraciones frente a las ~150
#   de la fase "hacia adelante" pidiendo una magnitud casi idéntica —
#   confirmado DIRECCIONAL, no de magnitud (ver CLAUDE.md para la causa
#   raíz completa). Resuelto subiendo `DEFAULT_MAX_ITERATIONS` a 1000
#   (investigado y descartado: ni invertir el orden de recorrido de CCD
#   ni amortiguar el ángulo arreglan esto de forma general — es
#   convergencia lenta monótona, no oscilación ni un límite de alcance).
# - biped chain_root=5/88 y bat chain_root=17/15: comprobadas también
#   (punto 5 de la tarea — no solo cow) por si el mismo problema
#   direccional aparecía ahí. No aparece: máximos de 9, 8, 180 y 0
#   iteraciones respectivamente, muy por debajo del presupuesto.
_TESTED_LIMBS = [
    ("cow_root31", "cow", 31, True, 250),
    ("cow_root33", "cow", 33, True, 150),
    ("cow_root27", "cow", 27, False, 400),
    ("cow_root3", "cow", 3, True, 900),
    ("biped_root5", "biped", 5, True, 60),
    ("biped_root88", "biped", 88, True, 60),
    ("bat_root17", "bat", 17, True, 300),
    ("bat_root15", "bat", 15, True, 50),
]


@pytest.fixture(scope="module")
def skeleton_and_skin_by_model():
    data = {}
    for model in _MODELS:
        tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
        limbs = classify_support_limbs(tree, root, hierarchy)
        skin_data = read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{model}_rigged.glb"))
        data[model] = (tree, hierarchy, {limb.chain_root: limb for limb in limbs}, skin_data)
    return data


def _positions(tree, limb):
    bind_foot = np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
    chain_root = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
    return bind_foot, chain_root


# --- foot_target_at_phase en sí, sin IK (una pata cualquiera basta) ---


@pytest.mark.parametrize("model", _MODELS)
def test_phase_periodicity(skeleton_and_skin_by_model, model):
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limb = next(iter(limbs_by_root.values()))
    bind_foot, chain_root = _positions(tree, limb)
    error = verify_phase_periodicity(bind_foot, chain_root, _STRIDE_DIRECTION)
    assert error < 1e-9


@pytest.mark.parametrize("model", _MODELS)
def test_never_below_ground(skeleton_and_skin_by_model, model):
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limb = next(iter(limbs_by_root.values()))
    bind_foot, chain_root = _positions(tree, limb)
    min_margin = verify_never_below_ground(bind_foot, chain_root, _STRIDE_DIRECTION)
    assert min_margin >= -1e-9


def test_non_horizontal_stride_direction_raises():
    with pytest.raises(ValueError):
        foot_target_at_phase(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 1.0, 0.0]),
            stride_direction=np.array([1.0, 1.0, 0.0]),
            phase=0.1,
        )


def test_zero_stride_direction_raises():
    with pytest.raises(ValueError):
        foot_target_at_phase(
            np.array([0.0, 0.0, 0.0]),
            np.array([1.0, 0.0, 0.0]),
            stride_direction=np.array([0.0, 0.0, 0.0]),
            phase=0.1,
        )


# --- detect_stride_direction ---
#
# Nota sobre el nº de patas por modelo (relevante para qué rama del
# algoritmo se ejercita): cow tiene 4 patas (rama PCA, >=3), pero biped Y
# bat tienen 2 cada uno (rama de la perpendicular a la línea entre las
# dos `chain_root_position` — NO la rama PCA). Se comprueba la
# horizontalidad en los 3 modelos, y el recálculo independiente
# (siguiendo la rama que de verdad les corresponde a cada uno) en los 3
# también — no solo en cow.


def _independent_stride_direction(tree, limbs) -> np.ndarray:
    """Recálculo independiente de `detect_stride_direction`, con numpy
    directamente sobre las mismas posiciones, para usar como chequeo
    cruzado en el test — NO reutiliza la función bajo prueba ni un vector
    hardcodeado a mano."""
    positions = np.array(
        [tree.nodes[limb.chain_root]["pos"] for limb in limbs], dtype=np.float64
    )
    if len(limbs) == 2:
        delta = positions[1] - positions[0]
        delta_xz = np.array([delta[0], delta[2]])
        delta_xz = delta_xz / np.linalg.norm(delta_xz)
        # Perpendicular en 2D: (x,z) -> (z,-x) (mismo giro de 90° que la
        # función bajo prueba; el signo no importa para este chequeo,
        # ver comparación por valor absoluto del coseno más abajo).
        perpendicular_xz = np.array([delta_xz[1], -delta_xz[0]])
        return np.array([perpendicular_xz[0], 0.0, perpendicular_xz[1]])

    # PCA vía SVD en vez de vía autovalores de la matriz de covarianza
    # (que es como lo hace `detect_stride_direction`) — mismo resultado
    # matemático, camino de código genuinamente distinto.
    xz = positions[:, [0, 2]]
    centered = xz - xz.mean(axis=0)
    _, _, vt = np.linalg.svd(centered)
    principal_axis_xz = vt[0]
    return np.array([principal_axis_xz[0], 0.0, principal_axis_xz[1]])


@pytest.mark.parametrize("model", _MODELS)
def test_stride_direction_is_horizontal(skeleton_and_skin_by_model, model):
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)
    assert abs(direction[1]) < 1e-9
    assert np.linalg.norm(direction) == pytest.approx(1.0)


@pytest.mark.parametrize("model", _MODELS)
def test_stride_direction_matches_independent_recomputation(skeleton_and_skin_by_model, model):
    """Compara `detect_stride_direction` contra un recálculo hecho desde
    cero en el propio test (`_independent_stride_direction`), no contra
    un vector esperado escrito a mano. El signo es arbitrario (ver
    docstring de `detect_stride_direction`), así que se compara el
    ÁNGULO entre ambos vectores tratando `v` y `-v` como equivalentes
    (valor absoluto del coseno) — debe ser prácticamente 0°."""
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limbs = list(limbs_by_root.values())

    detected = detect_stride_direction(limbs, tree)
    independent = _independent_stride_direction(tree, limbs)

    cosine = np.clip(abs(np.dot(detected, independent)), -1.0, 1.0)
    angle_deg = np.degrees(np.arccos(cosine))
    assert angle_deg < 1.0, (
        f"{model}: ángulo entre detect_stride_direction y el recálculo "
        f"independiente = {angle_deg:.3f}°, se esperaba <1°"
    )


# --- assign_limb_phase_offsets ---


@pytest.mark.parametrize("model", ["biped", "bat"])
def test_phase_offsets_biped_and_bat_alternate(skeleton_and_skin_by_model, model):
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)

    offsets = assign_limb_phase_offsets(limbs, tree, direction)

    assert len(offsets) == 2
    assert set(offsets.values()) == {0.0, 0.5}


def _independent_cow_diagonal_pairs(tree, limbs) -> dict[int, str]:
    """Recálculo independiente del agrupamiento diagonal de cow, con
    numpy directamente sobre las posiciones reales de `chain_root` y
    `foot_leaf` de los 4 `LimbChain` — NO reutiliza
    `assign_limb_phase_offsets` (mismo patrón que
    `_independent_stride_direction` en este archivo). Devuelve
    `chain_root -> "A"/"B"`, agrupando por signo relativo de la
    proyección delante/detrás (chain_root) y lado (foot_leaf, no
    chain_root — las dos patas traseras comparten chain_root_position,
    ver docstring de `assign_limb_phase_offsets`)."""
    direction = detect_stride_direction(limbs, tree)
    side_axis = np.cross(np.array([0.0, 1.0, 0.0]), direction)
    side_axis = side_axis / np.linalg.norm(side_axis)

    chain_root_pos = {
        limb.chain_root: np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
        for limb in limbs
    }
    foot_pos = {
        limb.chain_root: np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
        for limb in limbs
    }
    chain_root_centroid = np.mean(list(chain_root_pos.values()), axis=0)
    foot_centroid = np.mean(list(foot_pos.values()), axis=0)

    groups = {}
    for limb in limbs:
        proj_front = np.dot(chain_root_pos[limb.chain_root] - chain_root_centroid, direction)
        proj_side = np.dot(foot_pos[limb.chain_root] - foot_centroid, side_axis)
        groups[limb.chain_root] = "A" if np.sign(proj_front) == np.sign(proj_side) else "B"
    return groups


def test_phase_offsets_cow_diagonal_pairs(skeleton_and_skin_by_model):
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model["cow"]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)

    offsets = assign_limb_phase_offsets(limbs, tree, direction)
    independent_groups = _independent_cow_diagonal_pairs(tree, limbs)

    pair_a = [root for root, group in independent_groups.items() if group == "A"]
    pair_b = [root for root, group in independent_groups.items() if group == "B"]
    assert len(pair_a) == 2 and len(pair_b) == 2

    assert offsets[pair_a[0]] == offsets[pair_a[1]], (
        f"cow: el par diagonal {pair_a} (recalculado de forma independiente) "
        "debería recibir el mismo phase_offset"
    )
    assert offsets[pair_b[0]] == offsets[pair_b[1]], (
        f"cow: el par diagonal {pair_b} (recalculado de forma independiente) "
        "debería recibir el mismo phase_offset"
    )
    assert offsets[pair_a[0]] != offsets[pair_b[0]], (
        "cow: los dos pares diagonales deberían recibir phase_offset distinto"
    )


def test_phase_offsets_invariant_to_input_order(skeleton_and_skin_by_model):
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model["cow"]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)

    offsets_forward = assign_limb_phase_offsets(limbs, tree, direction)
    offsets_reversed = assign_limb_phase_offsets(list(reversed(limbs)), tree, direction)

    def pairs_by_group(offsets: dict[int, float]) -> set[frozenset[int]]:
        by_value: dict[float, list[int]] = {}
        for chain_root, value in offsets.items():
            by_value.setdefault(value, []).append(chain_root)
        return {frozenset(roots) for roots in by_value.values()}

    assert pairs_by_group(offsets_forward) == pairs_by_group(offsets_reversed), (
        "el agrupamiento relativo (qué patas comparten phase_offset) no debería "
        "depender del orden de entrada de `limbs`, aunque el valor absoluto "
        "0.0/0.5 asignado a cada grupo pueda invertirse"
    )


# --- safe_stride_amplitude_pct ---


@pytest.mark.parametrize("limb_id,model,chain_root,expect_unclipped,_", _TESTED_LIMBS)
def test_safe_amplitude_matches_expected_clipping(
    skeleton_and_skin_by_model, limb_id, model, chain_root, expect_unclipped, _
):
    """Regresión clave del punto 4: las patas que ya convergían bien
    deben devolver la amplitud PEDIDA sin recortar (0.3); la pata
    problemática (cow, chain_root=27) debe recortarse."""
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limb = limbs_by_root[chain_root]
    bind_foot, chain_root_pos = _positions(tree, limb)
    max_length = max_chain_bone_length(limb, hierarchy, tree)

    amplitude = safe_stride_amplitude_pct(
        bind_foot, chain_root_pos, max_length, _STRIDE_DIRECTION
    )

    if expect_unclipped:
        assert amplitude == pytest.approx(0.3), (
            f"{limb_id}: se recortó la amplitud ({amplitude}) sin necesitarlo — "
            "regresión en una pata que ya convergía bien"
        )
    else:
        assert amplitude < 0.3, f"{limb_id}: se esperaba un recorte y no lo hubo"
        assert amplitude > 0.0, f"{limb_id}: recorte excesivo, amplitud quedó en 0"


# --- Trayectoria completa alimentada al solver de IK ---


@pytest.mark.parametrize("limb_id,model,chain_root,expect_unclipped,max_iterations_ceiling", _TESTED_LIMBS)
def test_ik_converges_across_full_cycle(
    skeleton_and_skin_by_model, limb_id, model, chain_root, expect_unclipped, max_iterations_ceiling
):
    """Más exigente que los objetivos puntuales de `test_ik_solver.py`:
    cubre >=20 fases repartidas por todo el ciclo, incluyendo los
    extremos del rango de movimiento (phase≈0 máxima amplitud adelante,
    phase≈0.5 máxima amplitud atrás, phase≈0.25 máxima elevación) donde
    CCD podría converger más lento o no converger en absoluto.

    La amplitud de zancada usada es siempre la de `safe_stride_amplitude_pct`
    (paso explícito previo, ver docstring de `gait_cycle.py`) — para las
    patas que ya iban bien esto es un no-op (devuelve 0.3 sin tocar,
    verificado en `test_safe_amplitude_matches_expected_clipping`), así
    que este test cubre el flujo real de extremo a extremo.
    """
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limb = limbs_by_root[chain_root]
    bind_foot, chain_root_pos = _positions(tree, limb)
    max_length = max_chain_bone_length(limb, hierarchy, tree)
    amplitude = safe_stride_amplitude_pct(bind_foot, chain_root_pos, max_length, _STRIDE_DIRECTION)

    failures = []
    max_iterations_used = 0
    for i in range(_NUM_PHASE_SAMPLES):
        phase = i / _NUM_PHASE_SAMPLES
        target = foot_target_at_phase(
            bind_foot, chain_root_pos, _STRIDE_DIRECTION, phase, stride_amplitude_pct=amplitude
        )

        result = solve_ik_ccd(
            skin_data,
            limb,
            hierarchy,
            bind_foot,
            target,
            max_iterations=DEFAULT_MAX_ITERATIONS,
        )
        max_iterations_used = max(max_iterations_used, result.iterations_used)
        if not result.converged:
            failures.append((phase, result.final_error, result.iterations_used))

    assert not failures, (
        f"{limb_id} (amplitud={amplitude:.4f}): "
        f"{len(failures)}/{_NUM_PHASE_SAMPLES} fases no convergieron: {failures}"
    )
    assert max_iterations_used <= max_iterations_ceiling, (
        f"{limb_id}: {max_iterations_used} iteraciones en el peor caso, por encima "
        f"del techo esperado ({max_iterations_ceiling}) — posible regresión de "
        "rendimiento aunque todo haya convergido"
    )


# --- solve_gait_cycle_pose (varias patas a la vez) ---

_NUM_GLOBAL_PHASE_SAMPLES = 24


@pytest.mark.parametrize("model", _MODELS)
def test_all_limbs_converge_across_full_cycle(skeleton_and_skin_by_model, model):
    """Resolver varias patas a la vez, en vez de una por una como hace
    `test_ik_converges_across_full_cycle`, podría en teoría necesitar
    más iteraciones si algo se combinase mal — se comprueba
    explícitamente, no se asume que la independencia entre patas basta
    (documentada en `solve_gait_cycle_pose`, pero verificada aquí de
    todas formas)."""
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)
    offsets = assign_limb_phase_offsets(limbs, tree, direction)
    amplitudes = compute_safe_amplitudes(limbs, tree, hierarchy, direction)

    failures = []
    for i in range(_NUM_GLOBAL_PHASE_SAMPLES):
        global_phase = i / _NUM_GLOBAL_PHASE_SAMPLES
        _, results = solve_gait_cycle_pose(
            skin_data, limbs, tree, hierarchy, global_phase, direction, offsets, amplitudes
        )
        for chain_root, result in results.items():
            if not result.converged:
                failures.append((global_phase, chain_root, result.final_error, result.iterations_used))

    assert not failures, f"{model}: fases/patas que no convergieron: {failures}"


def test_combined_rotations_preserve_non_limb_bones(skeleton_and_skin_by_model):
    """Los huesos que no pertenecen a NINGUNA pata (columna, cabeza,
    cola...) deben quedar en su rotación de bind pose exacta en el dict
    combinado — la combinación no debe "contaminar" huesos ajenos a las
    patas."""
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model["cow"]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)
    offsets = assign_limb_phase_offsets(limbs, tree, direction)
    amplitudes = compute_safe_amplitudes(limbs, tree, hierarchy, direction)

    name_to_index = name_to_node_index(skin_data)
    limb_bone_indices = set()
    for limb in limbs:
        for bone_name in chain_bone_names(limb, hierarchy):
            limb_bone_indices.add(name_to_index[bone_name])
    non_limb_indices = set(skin_data.node_trs) - limb_bone_indices
    assert non_limb_indices, "cow: se esperaban huesos fuera de las 4 patas (columna, cabeza...)"

    combined, _ = solve_gait_cycle_pose(
        skin_data, limbs, tree, hierarchy, 0.3, direction, offsets, amplitudes
    )

    for node_index in non_limb_indices:
        bind_rotation = skin_data.node_trs[node_index].rotation
        assert np.array_equal(combined[node_index], bind_rotation), (
            f"cow: el hueso {skin_data.node_name[node_index]} (fuera de "
            "cualquier pata) no quedó en bind pose tras solve_gait_cycle_pose"
        )


def test_phase_zero_offset_limbs_at_forward_extreme(skeleton_and_skin_by_model):
    """Confirma que el desfase realmente se aplica (no solo que todo
    converge a algún punto cualquiera): en global_phase=0.0, las patas
    con phase_offset=0.0 deben resolver su pie cerca del extremo "hacia
    adelante" de SU propio ciclo local (phase=0.0), y las de
    phase_offset=0.5 cerca del extremo "hacia atrás" (phase=0.5).

    Verificación explícita por cinemática directa sobre el dict
    COMBINADO devuelto por `solve_gait_cycle_pose` (no se confía en
    `IKResult.final_error` de cada pata por separado, aunque ya debería
    reflejar esto — comparar la posición real del pie tras combinar es
    una prueba más directa e independiente)."""
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model["cow"]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)
    offsets = assign_limb_phase_offsets(limbs, tree, direction)
    amplitudes = compute_safe_amplitudes(limbs, tree, hierarchy, direction)

    combined, results = solve_gait_cycle_pose(
        skin_data, limbs, tree, hierarchy, 0.0, direction, offsets, amplitudes
    )

    for limb in limbs:
        assert results[limb.chain_root].converged

        bind_foot = np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
        chain_root_pos = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
        local_phase = offsets[limb.chain_root]  # global_phase=0.0 + offset
        expected_target = foot_target_at_phase(
            bind_foot, chain_root_pos, direction, local_phase,
            stride_amplitude_pct=amplitudes[limb.chain_root],
        )

        tip_index, tip_offset = tip_bone_and_offset(skin_data, limb, hierarchy, bind_foot)
        resolved_foot = foot_position_given_rotations(skin_data, tip_index, tip_offset, combined)

        error = float(np.linalg.norm(resolved_foot - expected_target))
        assert error < 1e-3, (
            f"cow chain_root={limb.chain_root} (phase_offset="
            f"{offsets[limb.chain_root]}): el pie resuelto en el dict combinado "
            f"está a {error} de su propio objetivo de fase local {local_phase}"
        )


# --- pose de "asombro" (surprise_pose_phase_offsets) ---
#
# Mismo `solve_gait_cycle_pose` de siempre, pero con TODAS las patas en
# la MISMA fase (`phase_offset=0.0` para todas, en vez del reparto
# alternado/diagonal de `assign_limb_phase_offsets`) — sincronía
# imposible en una marcha real en equilibrio, que se lee como un
# sobresalto/salto congelado. `global_phase=0.25`: el pico de elevación
# es una propiedad exacta de `foot_target_at_phase` (`max(0, sin(2π·phase))`
# alcanza su único máximo en `phase=0.25`, para cualquier pata de
# cualquier modelo), confirmado empíricamente antes de escribir estos
# tests resolviendo la pose completa en 40 fases para los 3 modelos: el
# pico de altura de cada pata (salvo `bat chain_root=15`, la pata de un
# solo hueso con `reach=0` ya documentada — se queda plana en todas las
# fases) cae exactamente en `phase=0.25`.

_SURPRISE_GLOBAL_PHASE = 0.25


@pytest.mark.parametrize("model", _MODELS)
def test_surprise_pose_all_legs_converge(skeleton_and_skin_by_model, model):
    """Mismo patrón que `test_all_limbs_converge_across_full_cycle`, pero
    con `surprise_pose_phase_offsets` (todas las patas en fase) en vez
    del reparto alternado/diagonal — confirma que la pose de asombro en
    sí converge, para las 8 patas de los 3 modelos, en el
    `global_phase` que da la extensión más dramática."""
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limbs = list(limbs_by_root.values())
    direction = detect_stride_direction(limbs, tree)
    offsets = surprise_pose_phase_offsets(limbs)
    amplitudes = compute_safe_amplitudes(limbs, tree, hierarchy, direction)

    _, results = solve_gait_cycle_pose(
        skin_data, limbs, tree, hierarchy, _SURPRISE_GLOBAL_PHASE, direction, offsets, amplitudes
    )

    failures = [
        (chain_root, result.final_error, result.iterations_used)
        for chain_root, result in results.items()
        if not result.converged
    ]
    assert not failures, f"{model}: patas que no convergieron en la pose de asombro: {failures}"


@pytest.mark.parametrize("model", _MODELS)
def test_surprise_pose_offsets_are_all_zero(skeleton_and_skin_by_model, model):
    """Trivial pero explícito: `surprise_pose_phase_offsets` debe dar
    0.0 para CADA pata, para los 3 modelos — es la propiedad que
    distingue esta pose del reparto alternado de
    `assign_limb_phase_offsets`."""
    tree, hierarchy, limbs_by_root, skin_data = skeleton_and_skin_by_model[model]
    limbs = list(limbs_by_root.values())
    offsets = surprise_pose_phase_offsets(limbs)

    assert set(offsets.keys()) == set(limbs_by_root.keys())
    for chain_root, offset in offsets.items():
        assert offset == 0.0, f"{model} chain_root={chain_root}: offset {offset} != 0.0"
