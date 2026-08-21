"""Depuración visual (matplotlib, sin Blender) de
`joint_limits.compute_hinge_axes`: dibuja el esqueleto en bind pose
(vista lateral, plano de mayor variación del cuerpo, vía PCA sobre todos
los nodos) con una flecha corta en la posición de cada pivote a lo largo
de su eje de bisagra calculado.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`). Mismo patrón de estilo
que los demás `_plot_*_debug.py` de este módulo.

Uso:
    python backend/scripts/_plot_hinge_axes_debug.py <modelo> <salida.png>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.app.ik_solver import chain_bone_names
from backend.app.joint_limits import compute_hinge_axes
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python _plot_hinge_axes_debug.py <cow|biped|bat> <salida.png>")
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)

    all_positions = np.array([tree.nodes[n]["pos"] for n in tree.nodes], dtype=np.float64)

    # Nodos de las PATAS únicamente (no todo el esqueleto) para calcular
    # el plano de mayor variación: en biped, la mayor variación del
    # cuerpo COMPLETO es el brazo extendido en T-pose (irrelevante para
    # las bisagras de las piernas, que son las que nos interesan aquí) —
    # escoger el plano solo a partir de los nodos de las patas evita que
    # esa variación ajena domine la proyección.
    leg_node_positions = []
    for limb in limbs:
        node = limb.foot_leaf
        while True:
            leg_node_positions.append(tree.nodes[node]["pos"])
            if node == limb.chain_root:
                break
            node = hierarchy[node]
    leg_positions = np.array(leg_node_positions, dtype=np.float64)

    centroid_3d = leg_positions.mean(axis=0)
    centered = leg_positions - centroid_3d
    _, _, vt = np.linalg.svd(centered)
    plane_u, plane_v = vt[0], vt[1]

    def project(point: np.ndarray) -> tuple[float, float]:
        rel = np.asarray(point, dtype=np.float64) - centroid_3d
        return float(np.dot(rel, plane_u)), float(np.dot(rel, plane_v))

    fig, ax = plt.subplots(figsize=(9, 9))

    projected_all = np.array([project(p) for p in all_positions])
    ax.scatter(projected_all[:, 0], projected_all[:, 1], color="lightgray", s=8, zorder=1)

    leg_diagonal = float(np.linalg.norm(leg_positions.max(axis=0) - leg_positions.min(axis=0)))
    arrow_length = leg_diagonal * 0.08

    for limb in limbs:
        bone_names = chain_bone_names(limb, hierarchy)
        axes = compute_hinge_axes(limb, hierarchy, tree)

        # Cadena completa en bind pose (pie a chain_root), para contexto.
        chain_nodes = [limb.foot_leaf]
        node = limb.foot_leaf
        while node != limb.chain_root:
            node = hierarchy[node]
            chain_nodes.append(node)
        chain_points = [project(tree.nodes[n]["pos"]) for n in chain_nodes]
        xs, ys = zip(*chain_points)
        ax.plot(xs, ys, "o-", color="black", linewidth=1.5, markersize=4, zorder=2)

        for bone_name in bone_names:
            if bone_name not in axes:
                continue
            _, parent_str, _ = bone_name.split("_")
            pivot_node = int(parent_str)
            pivot_2d = np.array(project(tree.nodes[pivot_node]["pos"]))

            axis_3d = axes[bone_name]
            axis_2d = np.array([np.dot(axis_3d, plane_u), np.dot(axis_3d, plane_v)])
            axis_2d_norm = np.linalg.norm(axis_2d)
            if axis_2d_norm < 1e-9:
                continue  # eje casi perpendicular al plano de proyección, invisible aquí
            axis_2d = axis_2d / axis_2d_norm

            ax.annotate(
                "",
                xy=(pivot_2d[0] + axis_2d[0] * arrow_length, pivot_2d[1] + axis_2d[1] * arrow_length),
                xytext=(pivot_2d[0] - axis_2d[0] * arrow_length, pivot_2d[1] - axis_2d[1] * arrow_length),
                arrowprops=dict(facecolor="tab:orange", edgecolor="tab:orange", width=1.5, headwidth=6),
                zorder=4,
            )

        ax.annotate(
            f"chain_root={limb.chain_root}",
            chain_points[-1], textcoords="offset points", xytext=(6, 6), fontsize=8, zorder=5,
        )

    ax.set_title(
        f"{model}: ejes de bisagra por articulación (naranja)\n"
        "proyección sobre el plano de mayor variación de LAS PATAS (PCA)"
    )
    ax.set_aspect("equal")

    # Ventana centrada en las patas (no en el bbox de todo el cuerpo, que
    # incluiría zonas irrelevantes aquí como los brazos de biped).
    leg_projected = np.array([project(p) for p in leg_positions])
    pad = leg_diagonal * 0.25
    ax.set_xlim(leg_projected[:, 0].min() - pad, leg_projected[:, 0].max() + pad)
    ax.set_ylim(leg_projected[:, 1].min() - pad, leg_projected[:, 1].max() + pad)
    fig.tight_layout()
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")


if __name__ == "__main__":
    main()
