"""Módulo 3 — IK simple (CCD) para una sola pata.

Cimiento previo al ciclo de marcha: solo verifica que, dada UNA pata
(`LimbChain` de `limb_classification.py`) y una posición objetivo
alcanzable para su pie, `solve_ik_ccd` converge en un nº acotado de
iteraciones. Nada de coordinación multi-pata ni trayectoria senoidal
todavía.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.app.gait_cycle import (
    detect_stride_direction,
    foot_target_at_phase,
    max_chain_bone_length,
    safe_stride_amplitude_pct,
)
from backend.app.ik_solver import (
    DEFAULT_MAX_ITERATIONS,
    chain_bone_names,
    name_to_node_index,
    foot_position_given_rotations,
    solve_ik_ccd,
    tip_bone_and_offset,
    verify_zero_displacement_converges_immediately,
)
from backend.app.joint_limits import compute_hinge_axes, hinge_axes_in_local_frame
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import (
    axis_angle_to_quat,
    quat_conjugate,
    quat_multiply,
    read_skin_data,
)

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_MODELS = ["cow", "biped", "bat"]

# Umbral de convergencia para el error final (distancia pie-objetivo, en
# las mismas unidades que la malla). No relativo a la diagonal como el
# resto del pipeline porque aquí lo relevante es la distancia absoluta
# real entre pie y objetivo tras converger, no una fracción del tamaño
# del modelo — pero el propio DEFAULT_TOLERANCE de solve_ik_ccd (1e-4) ya
# es sensato en las 3 escalas de estos samples (diagonales 2.6-10.1,
# alcances de pata 0.37-3.7): un error de 1e-4 es despreciable frente a
# cualquiera de esos alcances.
_CONVERGENCE_TOLERANCE = 1e-4


@pytest.fixture(scope="module")
def scenario_by_model():
    scenarios = {}
    for model in _MODELS:
        tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
        limbs = classify_support_limbs(tree, root, hierarchy)
        skin_data = read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{model}_rigged.glb"))
        scenarios[model] = (tree, hierarchy, limbs, skin_data)
    return scenarios


def _bind_foot_position(tree, limb) -> np.ndarray:
    return np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)


def _reachable_target(skin_data, limb, hierarchy, bind_foot_position, axis, angle_deg):
    """Genera un objetivo GARANTIZADO alcanzable: rota el hueso más
    próximo a `chain_root` (el pivote más proximal de la pata) un ángulo
    conocido y lee, por cinemática directa, dónde queda el pie — en vez
    de inventar una posición 3D que podría estar fuera del alcance real
    de la cadena (el propio enunciado de la tarea pide explícitamente
    evitar eso). Así el objetivo es, por construcción, una pose que la
    pata SÍ puede alcanzar con exactamente una rotación.

    Eje de rotación: igual criterio que `test_skinning.py`
    (`_FLEX_AXIS`) — los huesos de este armature apuntan a lo largo del
    eje Y local (offset del hijo ≈ (0, longitud, 0)), así que rotar sobre
    X o Z flexiona el hueso en un plano perpendicular a su propio eje sin
    introducir torsión sobre él mismo.
    """
    chain_names = chain_bone_names(limb, hierarchy)
    name_to_index = name_to_node_index(skin_data)
    top_bone_index = name_to_index[chain_names[-1]]  # el más cercano a chain_root

    tip_index, tip_offset = tip_bone_and_offset(skin_data, limb, hierarchy, bind_foot_position)

    bind_rotation = skin_data.node_trs[top_bone_index].rotation
    extra = axis_angle_to_quat(axis, np.radians(angle_deg))
    rotated_state = {top_bone_index: quat_multiply(bind_rotation, extra)}

    return foot_position_given_rotations(skin_data, tip_index, tip_offset, rotated_state)


# (eje, ángulo en grados) — 3 objetivos por pata: dos flexiones en el
# plano X (ida y vuelta, magnitudes distintas) y una en el plano Z, para
# cubrir algo de variedad sin acoplar el test a una sola dirección.
_TEST_TARGET_PARAMS = [
    ((1.0, 0.0, 0.0), 20.0),
    ((1.0, 0.0, 0.0), -15.0),
    ((0.0, 0.0, 1.0), 15.0),
]


def _limb_id(limb):
    return f"root{limb.chain_root}_foot{limb.foot_leaf}"


@pytest.mark.parametrize("model", _MODELS)
def test_identity_target_converges_without_rotating(scenario_by_model, model):
    """Auto-chequeo obligatorio (ver `ik_solver.py`): antes de fiarse de
    CCD para nada más, un objetivo igual a la posición de bind pose del
    pie debe converger sin rotar ningún hueso, para TODAS las patas del
    modelo."""
    tree, hierarchy, limbs, skin_data = scenario_by_model[model]
    for limb in limbs:
        bind_pos = _bind_foot_position(tree, limb)
        error = verify_zero_displacement_converges_immediately(
            skin_data, limb, hierarchy, bind_pos
        )
        assert error < 1e-8, f"{model}/{_limb_id(limb)}: error {error} en auto-chequeo"


@pytest.mark.parametrize("model", _MODELS)
def test_ccd_converges_to_reachable_targets(scenario_by_model, model):
    tree, hierarchy, limbs, skin_data = scenario_by_model[model]

    for limb in limbs:
        bind_pos = _bind_foot_position(tree, limb)
        for axis, angle_deg in _TEST_TARGET_PARAMS:
            target = _reachable_target(skin_data, limb, hierarchy, bind_pos, axis, angle_deg)

            result = solve_ik_ccd(
                skin_data,
                limb,
                hierarchy,
                bind_pos,
                target,
                max_iterations=DEFAULT_MAX_ITERATIONS,
            )

            assert result.converged, (
                f"{model}/{_limb_id(limb)} objetivo eje={axis} ángulo={angle_deg}°: "
                f"no convergió en {DEFAULT_MAX_ITERATIONS} iteraciones "
                f"(error final={result.final_error:.6f})"
            )
            assert result.final_error < _CONVERGENCE_TOLERANCE
            assert result.iterations_used <= DEFAULT_MAX_ITERATIONS


# --- hinge_axes_local: restricción de rotación a 1 eje por articulación ---
#
# Alcance de esta tarea: restringir el EJE de rotación (bisagra de 1
# grado de libertad) para los huesos con eje calculado; el pivote de
# cadera/hombro (excluido de compute_hinge_axes) sigue rotando libre.
# NO incluye todavía un límite de ÁNGULO (rango de flexión/extensión)
# dentro de esa bisagra — tarea posterior, a propósito.


@pytest.mark.parametrize("model", _MODELS)
def test_unconstrained_behavior_unchanged(scenario_by_model, model):
    """`hinge_axes_local=None` (el default) debe dar resultados
    IDÉNTICOS a no pasar el parámetro en absoluto — confirma que el
    parámetro nuevo no cambia nada del comportamiento existente cuando
    no se usa."""
    tree, hierarchy, limbs, skin_data = scenario_by_model[model]

    for limb in limbs[:2]:  # 2 patas por modelo bastan para esta comprobación
        bind_pos = _bind_foot_position(tree, limb)
        for axis, angle_deg in _TEST_TARGET_PARAMS[:2]:
            target = _reachable_target(skin_data, limb, hierarchy, bind_pos, axis, angle_deg)

            result_default = solve_ik_ccd(skin_data, limb, hierarchy, bind_pos, target)
            result_explicit_none = solve_ik_ccd(
                skin_data, limb, hierarchy, bind_pos, target, hinge_axes_local=None
            )

            assert result_default.final_error == result_explicit_none.final_error
            assert result_default.iterations_used == result_explicit_none.iterations_used
            assert result_default.converged == result_explicit_none.converged
            for node_index in result_default.local_rotations:
                np.testing.assert_array_equal(
                    result_default.local_rotations[node_index],
                    result_explicit_none.local_rotations[node_index],
                )


@pytest.mark.parametrize("model", _MODELS)
def test_hinge_constrained_converges_across_full_cycle(scenario_by_model, model):
    """Verificado independientemente (fuera de este entorno) antes de
    esta tarea: 0 fallos en las 8 patas de los 3 modelos, 24 fases cada
    una. Si esto sale distinto aquí, algo se implementó diferente de lo
    especificado."""
    tree, hierarchy, limbs, skin_data = scenario_by_model[model]
    direction = detect_stride_direction(limbs, tree)

    for limb in limbs:
        bind_pos = _bind_foot_position(tree, limb)
        chain_root_pos = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
        max_length = max_chain_bone_length(limb, hierarchy, tree)
        amplitude = safe_stride_amplitude_pct(bind_pos, chain_root_pos, max_length, direction)

        world_axes = compute_hinge_axes(limb, hierarchy, tree)
        local_axes = hinge_axes_in_local_frame(skin_data, world_axes)

        failures = []
        for i in range(24):
            phase = i / 24
            target = foot_target_at_phase(
                bind_pos, chain_root_pos, direction, phase, stride_amplitude_pct=amplitude
            )
            result = solve_ik_ccd(
                skin_data, limb, hierarchy, bind_pos, target,
                hinge_axes_local=local_axes, max_iterations=DEFAULT_MAX_ITERATIONS,
            )
            if not result.converged:
                failures.append((phase, result.final_error, result.iterations_used))

        assert not failures, (
            f"{model}/{_limb_id(limb)}: {len(failures)}/24 fases no convergieron "
            f"con restricción de bisagra: {failures}"
        )


@pytest.mark.parametrize("chain_root,bone_name", [(31, "bone_31_10"), (3, "bone_3_29")])
def test_constrained_rotation_axis_matches_hinge(scenario_by_model, chain_root, bone_name):
    """Verifica DIRECTAMENTE que la restricción se respeta: para un
    hueso con eje conocido, fuerza un objetivo alcanzable rotando ESE
    hueso sobre su propio eje de bisagra (mundo), resuelve con
    `hinge_axes_local` y `max_iterations=1`, y confirma que el eje de la
    rotación LOCAL aplicada (`new_local * conj(old_local)`) es paralelo
    (o antiparalelo) al eje local esperado — no cualquier otro eje."""
    tree, hierarchy, limbs, skin_data = scenario_by_model["cow"]
    limb = next(l for l in limbs if l.chain_root == chain_root)
    bind_pos = _bind_foot_position(tree, limb)

    world_axes = compute_hinge_axes(limb, hierarchy, tree)
    local_axes = hinge_axes_in_local_frame(skin_data, world_axes)
    assert bone_name in local_axes

    name_to_index = name_to_node_index(skin_data)
    node_index = name_to_index[bone_name]

    # Objetivo alcanzable rotando ESTE hueso 25° sobre su propio eje de
    # bisagra en MUNDO (bind pose) — cinemática directa, no una posición
    # 3D inventada.
    tip_index, tip_offset = tip_bone_and_offset(skin_data, limb, hierarchy, bind_pos)
    bind_rotation = skin_data.node_trs[node_index].rotation
    extra = axis_angle_to_quat(world_axes[bone_name], np.radians(25))
    rotated_state = {node_index: quat_multiply(bind_rotation, extra)}
    target = foot_position_given_rotations(skin_data, tip_index, tip_offset, rotated_state)

    result = solve_ik_ccd(
        skin_data, limb, hierarchy, bind_pos, target,
        hinge_axes_local=local_axes, max_iterations=1,
    )

    new_local = result.local_rotations[node_index]
    delta = quat_multiply(new_local, quat_conjugate(bind_rotation))
    delta = delta / np.linalg.norm(delta)
    axis_part = delta[:3]
    axis_norm = np.linalg.norm(axis_part)
    assert axis_norm > 1e-6, f"{bone_name}: no rotó en absoluto tras 1 iteración"

    applied_axis = axis_part / axis_norm
    expected_axis = local_axes[bone_name]
    cosine = float(np.clip(np.dot(applied_axis, expected_axis), -1.0, 1.0))
    assert abs(abs(cosine) - 1.0) < 1e-6, (
        f"{bone_name}: eje de la rotación aplicada ({applied_axis}) no es "
        f"paralelo/antiparalelo al eje de bisagra esperado ({expected_axis}), "
        f"cos={cosine}"
    )
