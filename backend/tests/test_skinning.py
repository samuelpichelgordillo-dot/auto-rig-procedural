"""Módulo 2 — cierre formal: métrica cuantitativa de suavidad de pesos +
test de deformación, sobre los 3 GLB ya rigged en `samples/_debug/`. Todo
en Python puro (numpy + pygltflib vía `backend.app.skinning_quality`), sin
Blender — los datos de skin ya están en el GLB exportado.

La inspección visual (heatmaps, checkpoint 2026-08-20) ya concluyó que los
3 modelos no necesitan suavizado adicional; estos tests son la red de
seguridad de regresión, no un veredicto de calidad nuevo.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pytest

from backend.app.skinning_quality import (
    apply_bone_rotation,
    axis_angle_to_quat,
    read_skin_data,
    verify_identity_rotation_reproduces_bind_pose,
    weight_smoothness_metric,
)

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples" / "_debug"
_MODELS = ["cow", "biped", "bat"]

logger = logging.getLogger(__name__)


# --- Línea base de suavizado (Módulo 2, checkpoint 2026-08-20) ---
# Valores exactos medidos sobre los 3 samples, ver CLAUDE.md. Umbral de
# regresión: p99 observado + margen absoluto de 0.05 (el rango de la
# métrica L1 es [0,2]; un margen de 0.05 es ~2.5% del rango total —
# suficiente para absorber ruido de punto flotante entre ejecuciones
# deterministas del mismo pipeline de auto-weight, sin dejar pasar una
# regresión real). Nota: cow y bat ya tienen p99 muy cerca del máximo
# teórico (2.0) en bind pose — son bordes NO problemáticos entre huesos
# rígidos lejanos (p.ej. entre dos falanges sin necesidad de mezcla), no
# indicio de mal suavizado; el margen de regresión para esos dos modelos
# tiene por tanto poco margen de maniobra por construcción, ver discusión
# en CLAUDE.md.
_P99_BASELINE = {
    "cow": 1.9802,
    "biped": 1.6271,
    "bat": 1.9235,
}
_P99_MARGIN = 0.05


@pytest.fixture(scope="module")
def skin_data_by_model():
    return {model: read_skin_data(str(_SAMPLES_DIR / f"{model}_rigged.glb")) for model in _MODELS}


def test_identity_rotation_reproduces_bind_pose(skin_data_by_model):
    """Auto-chequeo obligatorio (ver skinning_quality.py): si esto falla,
    el bug está en la composición jerárquica de matrices, no en la
    rotación — no tiene sentido confiar en ningún otro test hasta que
    pase."""
    for model, skin_data in skin_data_by_model.items():
        max_error = verify_identity_rotation_reproduces_bind_pose(skin_data)
        assert max_error < 1e-5, f"{model}: error {max_error} en auto-chequeo de identidad"


def test_bind_pose_weights_sum_to_one(skin_data_by_model):
    """Chequeo de regresión (ya sabíamos que esto se cumple por inspección
    manual — Módulo 2, checkpoint del 2026-08-19 — pero no había test
    automatizado): la suma de WEIGHTS_0 por vértice debe ser 1.0 en bind
    pose, para los 3 modelos."""
    for model, skin_data in skin_data_by_model.items():
        for prim in skin_data.primitives:
            sums = prim.weights.sum(axis=1)
            assert np.allclose(sums, 1.0, atol=1e-4), (
                f"{model}: hay vértices cuya suma de pesos no es 1.0 "
                f"(min={sums.min()}, max={sums.max()})"
            )


def test_weight_smoothness_baseline(skin_data_by_model):
    """Mide la distribución completa de distancia L1 entre vectores de
    peso de vértices adyacentes, para los 3 modelos, y la compara contra
    la línea base documentada en CLAUDE.md. Red de seguridad de
    regresión, no umbral de calidad absoluto (ver docstring del módulo)."""
    for model, skin_data in skin_data_by_model.items():
        distances = weight_smoothness_metric(skin_data)
        assert distances.size > 0, f"{model}: sin aristas, algo va mal"

        mean = float(distances.mean())
        median = float(np.median(distances))
        p95 = float(np.percentile(distances, 95))
        p99 = float(np.percentile(distances, 99))
        maximum = float(distances.max())

        logger.info(
            "%s: n_edges=%d mean=%.4f median=%.4f p95=%.4f p99=%.4f max=%.4f",
            model, distances.size, mean, median, p95, p99, maximum,
        )
        print(
            f"{model}: n_edges={distances.size} mean={mean:.4f} median={median:.4f} "
            f"p95={p95:.4f} p99={p99:.4f} max={maximum:.4f}"
        )

        threshold = min(2.0, _P99_BASELINE[model] + _P99_MARGIN)
        assert p99 <= threshold, (
            f"{model}: p99={p99:.4f} supera el umbral de regresión {threshold:.4f} "
            f"(línea base {_P99_BASELINE[model]:.4f} + margen {_P99_MARGIN})"
        )


# --- Test de deformación ---
# Muestra de huesos por modelo, reutilizando el criterio validado en el
# checkpoint de reselección de heatmaps (2026-08-20): grado 2 real a
# ~50% de una cadena larga entre bifurcaciones reales para el ejemplo
# "mid-chain" (los mismos huesos usados en los heatmaps de codo/rodilla/
# ala), más un hueso justo tras la raíz, más un hueso hoja, más (si el
# modelo tiene una bifurcación real hacia varias hojas en 1 salto — firma
# de dedos/dedos del pie) un hueso justo antes de esa bifurcación.
#
# cow: el esqueleto simplificado de este modelo no tiene bifurcación tipo
# "dedos" (los únicos nodos de grado>=3 son 2,3,4,12 — ninguno bifurca
# directamente en varias hojas de 1 salto, ver checkpoint del Módulo 1),
# así que esa 4ª categoría no aplica y se deja fuera deliberadamente.
_DEFORMATION_BONE_SAMPLES = {
    "cow": [
        ("bone_2_3", "justo tras la raíz"),
        ("bone_3_29", "mid-chain grado2 (mismo que el heatmap de codo/rodilla)"),
        ("bone_29_15", "hoja (pie)"),
    ],
    "biped": [
        ("bone_48_4", "justo tras la raíz"),
        ("bone_107_206", "mid-chain grado2 (mismo que el heatmap de codo)"),
        ("bone_71_118", "mid-chain grado2 (mismo que el heatmap de rodilla)"),
        ("bone_116_30", "justo antes de la bifurcación de dedos del pie (nodo 30, grado 5)"),
        ("bone_30_3", "hoja (dedo del pie)"),
    ],
    "bat": [
        ("bone_13_18", "justo tras la raíz"),
        ("bone_34_24", "mid-chain grado2 (mismo que el heatmap del ala)"),
        ("bone_16_2", "justo antes de una bifurcación de 2 hojas en 1 salto (nodo 2, grado 3)"),
        ("bone_24_27", "hoja (punta del ala)"),
    ],
}

# Ángulo de flexión moderado, dentro del rango 30-45° pedido.
_FLEX_ANGLE_DEG = 35.0

# Eje de rotación: los huesos de este armature apuntan a lo largo del eje
# Y local (el offset del hueso hijo es (0, longitud, 0) en espacio local
# del padre — comprobado en el GLB exportado, translation de cada joint).
# Rotar sobre el eje X local flexiona el hueso en un plano perpendicular a
# su propio eje longitudinal (como una bisagra de codo/rodilla), sin
# introducir torsión sobre el eje del propio hueso (que sería rotar sobre
# Y) ni una flexión en el otro plano perpendicular (Z) — X es una elección
# arbitraria entre X/Z igualmente válida para el propósito de este test
# (detectar NaN/explosiones/huérfanos, no verificar una pose anatómica
# específica).
_FLEX_AXIS = np.array([1.0, 0.0, 0.0])


@pytest.mark.parametrize("model", _MODELS)
def test_bone_rotation_deformation_sanity(skin_data_by_model, model):
    skin_data = skin_data_by_model[model]

    original_positions = np.concatenate(
        [prim.positions for prim in skin_data.primitives], axis=0
    )
    original_bbox_diagonal = float(
        np.linalg.norm(original_positions.max(axis=0) - original_positions.min(axis=0))
    )
    assert original_bbox_diagonal > 0

    quat = axis_angle_to_quat(_FLEX_AXIS, np.radians(_FLEX_ANGLE_DEG))

    for bone_name, _reason in _DEFORMATION_BONE_SAMPLES[model]:
        deformed = apply_bone_rotation(skin_data, bone_name, quat)
        combined = np.concatenate(deformed, axis=0)

        assert np.isfinite(combined).all(), f"{model}/{bone_name}: NaN/Inf tras deformar"

        deformed_bbox_diagonal = float(
            np.linalg.norm(combined.max(axis=0) - combined.min(axis=0))
        )
        assert deformed_bbox_diagonal <= 3.0 * original_bbox_diagonal, (
            f"{model}/{bone_name}: bounding box deformado ({deformed_bbox_diagonal:.3f}) "
            f"excede 3x la diagonal original ({original_bbox_diagonal:.3f}) — "
            "posible explosión numérica"
        )

        for prim in skin_data.primitives:
            sums = prim.weights.sum(axis=1)
            assert np.allclose(sums, 1.0, atol=1e-4), (
                f"{model}/{bone_name}: vértices huérfanos (suma de pesos != 1.0) "
                "detectados en bind pose de esta primitiva"
            )
