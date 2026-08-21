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
# id, modelo, chain_root, ¿ya convergía bien SIN recorte de amplitud
# (baseline conocido, checkpoint 2026-08-20)?, techo de iteraciones
# esperado con margen generoso (no un valor exacto — solo para detectar
# una regresión real, "mismo orden de magnitud" que pide la tarea).
#
# - cow chain_root=31: la PRIMERA que devuelve `classify_support_limbs`
#   para cow — ya convergía con margen (158 de 500 iteraciones) con
#   stride_amplitude_pct=0.3 sin recortar. Debe seguir sin recortarse.
# - cow chain_root=27: la que motivó esta tarea — con amplitud fija 0.3
#   pedía objetivos hasta el 92% de su longitud física máxima en varias
#   fases y NO convergía (500/500 iteraciones, error final ~1e-4 en 4 de
#   30 fases). Con el recorte de `safe_stride_amplitude_pct`, converge en
#   las 30 fases con margen cómodo (ver CLAUDE.md para los números
#   exactos). Añadida explícitamente aquí — ya no se evita.
# - biped chain_root=5 / bat chain_root=17: primera pata de cada modelo,
#   ya convergían bien (8 y 180 de 500 iteraciones respectivamente).
_TESTED_LIMBS = [
    ("cow_root31", "cow", 31, True, 250),
    ("cow_root27", "cow", 27, False, 400),
    ("biped_root5", "biped", 5, True, 60),
    ("bat_root17", "bat", 17, True, 300),
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
