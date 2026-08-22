"""Depuración visual (matplotlib, sin Blender) de
`micro_movements.breathing_local_rotation`: para un modelo dado, aplica
la respiración a la rotación de bind pose de la RAÍZ del esqueleto
(``skin_data.root_node_index``) en varios instantes `t` repartidos en un
periodo completo, recalcula las posiciones de todos los huesos vía
`compute_global_matrices` y dibuja la silueta completa del esqueleto
superpuesta para cada instante (vista lateral) — para comprobar a ojo
que el efecto es un balanceo apenas perceptible del cuerpo completo, no
un movimiento exagerado ni descolocado.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`).

Uso:
    python backend/scripts/_plot_breathing_debug.py <modelo> <salida.png>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.app.gait_cycle import detect_stride_direction
from backend.app.limb_classification import classify_support_limbs
from backend.app.micro_movements import DEFAULT_BREATHS_PER_MINUTE, breathing_local_rotation
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import (
    compute_global_matrices,
    quat_multiply,
    read_skin_data,
    trs_to_matrix,
)

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_NUM_INSTANTS = 6


def _bone_edges(skin_data) -> list[tuple[int, int]]:
    """Aristas (nodo_padre, nodo_hijo) SOLO entre nodos-hueso
    ("bone_..."), ignorando nodos de malla (Cow, Eyes, SuperHero_Male...)
    que también cuelgan del mismo root_node_index."""
    edges = []
    for parent, children in skin_data.node_children.items():
        for child in children:
            if skin_data.node_name.get(child, "").startswith("bone_"):
                edges.append((parent, child))
    return edges


def _skeleton_positions(skin_data, root_rotation_override: np.ndarray | None) -> dict[int, np.ndarray]:
    local_matrix_of = {}
    for node_index, trs in skin_data.node_trs.items():
        rotation = trs.rotation
        if root_rotation_override is not None and node_index == skin_data.root_node_index:
            rotation = root_rotation_override
        local_matrix_of[node_index] = trs_to_matrix(trs.translation, rotation, trs.scale)

    globals_ = compute_global_matrices(
        skin_data.root_node_index, skin_data.node_children, local_matrix_of
    )
    return {node_index: mat[:3, 3] for node_index, mat in globals_.items()}


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python _plot_breathing_debug.py <cow|biped|bat> <salida.png>")
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    skin_data = read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{model}_rigged.glb"))
    direction = detect_stride_direction(limbs, tree)
    side_axis = np.cross(np.array([0.0, 1.0, 0.0]), direction)
    side_axis = side_axis / np.linalg.norm(side_axis)

    edges = _bone_edges(skin_data)
    root_bind_rotation = skin_data.node_trs[skin_data.root_node_index].rotation

    period = 60.0 / DEFAULT_BREATHS_PER_MINUTE
    instants = [i / _NUM_INSTANTS * period for i in range(_NUM_INSTANTS)]

    fig, ax = plt.subplots(1, 1, figsize=(6, 7))
    cmap = plt.get_cmap("coolwarm")

    # Proyección sobre (stride_direction, Y) en vez de (X, Y) crudo —
    # mismo criterio que `_plot_surprise_pose_debug.py`: para modelos
    # como cow, cuyo cuerpo se extiende mayormente a lo largo de un eje
    # horizontal distinto de X, una vista lateral cruda en (X, Y) proyecta
    # patas/cuernos casi de perfil, dando un aspecto de "X" cruzada que es
    # el aspecto NORMAL de bind pose (verificado aparte, sin respiración,
    # antes de aceptar esta vista) y no debe confundirse con distorsión.
    for i, t in enumerate(instants):
        color = cmap(i / max(_NUM_INSTANTS - 1, 1))
        extra = breathing_local_rotation(t, side_axis)
        perturbed_rotation = quat_multiply(extra, root_bind_rotation)
        positions = _skeleton_positions(skin_data, perturbed_rotation)

        for parent, child in edges:
            p, c = positions[parent], positions[child]
            p_h, c_h = float(np.dot(p, direction)), float(np.dot(c, direction))
            ax.plot([p_h, c_h], [p[1], c[1]], "-", color=color, linewidth=1.0, alpha=0.8)

        ax.plot([], [], "-", color=color, label=f"t={t:.2f}s")

    ax.set_xlabel("stride_direction (proyección horizontal)")
    ax.set_ylabel("Y (altura)")
    ax.set_aspect("equal")
    ax.legend(fontsize=7, loc="best")
    ax.set_title(
        f"{model}: silueta del esqueleto con respiración aplicada a la raíz\n"
        f"{_NUM_INSTANTS} instantes en un periodo completo ({period:.1f}s, "
        f"{DEFAULT_BREATHS_PER_MINUTE:.0f} resp/min) — vista lateral (X-Y)",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")


if __name__ == "__main__":
    main()
