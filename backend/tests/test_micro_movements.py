"""Módulo 4 — micro-movimientos: respiración.

Cubre `micro_movements.breathing_local_rotation` en sí (amplitud nunca
excedida, periodicidad, identidad exacta en t=0) y, reproduciendo el
cálculo de calibración documentado en el propio módulo, que el
desplazamiento aproximado que produce en la posición del pie de cada
pata es de verdad sutil frente a la longitud de la cadena — para las 8
patas de los 3 modelos, no solo de memoria.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from backend.app.gait_cycle import max_chain_bone_length
from backend.app.limb_classification import classify_support_limbs
from backend.app.micro_movements import (
    DEFAULT_BREATHS_PER_MINUTE,
    DEFAULT_MAX_AMPLITUDE_DEG,
    breathing_local_rotation,
)
from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_MODELS = ["cow", "biped", "bat"]

_SIDE_AXIS = np.array([1.0, 0.0, 0.0])


@pytest.fixture(scope="module")
def tree_and_limbs_by_model():
    data = {}
    for model in _MODELS:
        tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
        limbs = classify_support_limbs(tree, root, hierarchy)
        data[model] = (tree, root, hierarchy, limbs)
    return data


def _rotation_angle_deg(quat: np.ndarray) -> float:
    """Ángulo total (sin signo, en grados) representado por un
    cuaternión [x,y,z,w] unitario: ``2*arccos(|w|)`` — el valor absoluto
    de ``w`` evita el problema de que ``q`` y ``-q`` representan la
    misma rotación pero podrían dar ``w`` de signo distinto."""
    w = float(np.clip(abs(quat[3]), -1.0, 1.0))
    return math.degrees(2.0 * math.acos(w))


def test_breathing_amplitude_never_exceeds_max():
    num_samples = 200
    period = 60.0 / DEFAULT_BREATHS_PER_MINUTE
    t_values = [i / num_samples * 3 * period for i in range(num_samples)]  # >=2-3 periodos

    max_angle = 0.0
    for t in t_values:
        quat = breathing_local_rotation(t, _SIDE_AXIS)
        angle = _rotation_angle_deg(quat)
        max_angle = max(max_angle, angle)

    assert max_angle <= DEFAULT_MAX_AMPLITUDE_DEG + 1e-6, (
        f"ángulo máximo observado {max_angle} excede DEFAULT_MAX_AMPLITUDE_DEG "
        f"({DEFAULT_MAX_AMPLITUDE_DEG})"
    )


@pytest.mark.parametrize("t", [0.0, 0.3, 1.7, 3.14, 5.0, 10.25])
def test_breathing_is_periodic(t):
    period = 60.0 / DEFAULT_BREATHS_PER_MINUTE
    quat_a = breathing_local_rotation(t, _SIDE_AXIS)
    quat_b = breathing_local_rotation(t + period, _SIDE_AXIS)

    same = np.allclose(quat_a, quat_b, atol=1e-9)
    negated = np.allclose(quat_a, -quat_b, atol=1e-9)
    assert same or negated, (
        f"breathing_local_rotation no es periódico en t={t}: {quat_a} vs {quat_b}"
    )


def test_breathing_identity_at_t_zero():
    quat = breathing_local_rotation(0.0, _SIDE_AXIS)
    np.testing.assert_allclose(quat, np.array([0.0, 0.0, 0.0, 1.0]), atol=1e-12)


@pytest.mark.parametrize("model", _MODELS)
def test_breathing_displacement_is_subtle(tree_and_limbs_by_model, model):
    """Reproduce el cálculo de calibración documentado en
    `micro_movements.DEFAULT_MAX_AMPLITUDE_DEG`: para cada pata, el
    desplazamiento aproximado de respiración
    (`radians(max_amplitude_deg) * (dist_raíz_a_chain_root +
    max_chain_bone_length)`) debe quedar muy por debajo de la longitud
    de cadena de esa pata — margen generoso (15%) sobre el 2.98%-6.11%
    observado en los 3 modelos al calibrar el default, para detectar una
    regresión real si un modelo futuro diera una proporción mucho mayor,
    en vez de dejarlo pasar en silencio."""
    _MAX_SUBTLE_FRACTION = 0.15

    tree, root, hierarchy, limbs = tree_and_limbs_by_model[model]
    root_pos = np.array(tree.nodes[root]["pos"], dtype=np.float64)

    for limb in limbs:
        chain_root_pos = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
        dist_root_to_chain_root = float(np.linalg.norm(chain_root_pos - root_pos))
        max_length = max_chain_bone_length(limb, hierarchy, tree)

        displacement = math.radians(DEFAULT_MAX_AMPLITUDE_DEG) * (
            dist_root_to_chain_root + max_length
        )
        fraction = displacement / max_length

        assert fraction < _MAX_SUBTLE_FRACTION, (
            f"{model} chain_root={limb.chain_root}: desplazamiento de respiración "
            f"({displacement:.4f}) es un {fraction * 100:.1f}% de la longitud de "
            f"cadena ({max_length:.4f}) — por encima del margen esperado "
            f"({_MAX_SUBTLE_FRACTION * 100:.0f}%), ya no es sutil"
        )
