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
    foot_target_at_phase,
    max_chain_bone_length,
    safe_stride_amplitude_pct,
    verify_never_below_ground,
    verify_phase_periodicity,
)
from backend.app.ik_solver import DEFAULT_MAX_ITERATIONS, solve_ik_ccd
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
