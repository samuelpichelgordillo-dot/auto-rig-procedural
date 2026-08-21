"""Depuración visual (matplotlib, sin Blender) de
`gait_cycle.assign_limb_phase_offsets`: vista cenital (plano X-Z) de las
patas de un modelo, cada una coloreada según su `phase_offset` (azul =
0.0, rojo = 0.5) — para comprobar a ojo que el agrupamiento tiene
sentido (en cow, los dos pares de colores deben quedar en DIAGONAL, no
"los dos de un lado" ni "delante vs atrás").

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`). Mismo patrón de estilo
que `_plot_stride_direction_debug.py`.

Uso:
    python backend/scripts/_plot_phase_offsets_debug.py <modelo> <salida.png>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.app.gait_cycle import assign_limb_phase_offsets, detect_stride_direction
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_OFFSET_COLOR = {0.0: "tab:blue", 0.5: "tab:red"}


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python _plot_phase_offsets_debug.py <cow|biped|bat> <salida.png>")
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    direction = detect_stride_direction(limbs, tree)
    offsets = assign_limb_phase_offsets(limbs, tree, direction)

    chain_root_positions = np.array(
        [tree.nodes[limb.chain_root]["pos"] for limb in limbs], dtype=np.float64
    )
    foot_positions = np.array(
        [tree.nodes[limb.foot_leaf]["pos"] for limb in limbs], dtype=np.float64
    )
    all_positions = np.array([tree.nodes[n]["pos"] for n in tree.nodes], dtype=np.float64)

    fig, ax = plt.subplots(figsize=(8, 8))

    ax.scatter(all_positions[:, 0], all_positions[:, 2], color="lightgray", s=8, zorder=1)

    for limb, root_pos, foot_pos in zip(limbs, chain_root_positions, foot_positions):
        color = _OFFSET_COLOR[offsets[limb.chain_root]]
        ax.plot(
            [root_pos[0], foot_pos[0]], [root_pos[2], foot_pos[2]],
            "o-", color=color, linewidth=2.5, markersize=8, zorder=3,
        )
        ax.annotate(
            f"chain_root={limb.chain_root}\nphase_offset={offsets[limb.chain_root]}",
            (foot_pos[0], foot_pos[2]),
            textcoords="offset points", xytext=(8, -10), fontsize=8, zorder=4,
        )

    centroid = chain_root_positions.mean(axis=0)
    centroid_xz = np.array([centroid[0], centroid[2]])
    xz_spread = chain_root_positions[:, [0, 2]]
    horizontal_extent = float(np.linalg.norm(xz_spread.max(axis=0) - xz_spread.min(axis=0)))
    if horizontal_extent < 1e-6:
        horizontal_extent = float(
            np.linalg.norm(all_positions.max(axis=0) - all_positions.min(axis=0))
        )

    all_xz = all_positions[:, [0, 2]]
    distances_to_centroid = np.linalg.norm(all_xz - centroid_xz, axis=1)
    body_radius_p60 = float(np.percentile(distances_to_centroid, 60))

    # Flecha de stride_direction también, para contexto (misma escala que
    # _plot_stride_direction_debug.py).
    arrow_length = horizontal_extent * 0.6
    ax.annotate(
        "",
        xy=(centroid[0] + direction[0] * arrow_length, centroid[2] + direction[2] * arrow_length),
        xytext=(centroid[0], centroid[2]),
        arrowprops=dict(facecolor="black", edgecolor="black", width=2, headwidth=8),
        zorder=2,
    )

    handles = [
        plt.Line2D([0], [0], marker="o", color=_OFFSET_COLOR[0.0], linestyle="", markersize=8, label="phase_offset=0.0"),
        plt.Line2D([0], [0], marker="o", color=_OFFSET_COLOR[0.5], linestyle="", markersize=8, label="phase_offset=0.5"),
    ]
    ax.legend(handles=handles, loc="best", fontsize=8)

    ax.set_xlabel("X")
    ax.set_ylabel("Z")
    ax.set_title(
        f"{model}: assign_limb_phase_offsets — {len(limbs)} patas\n"
        "vista cenital (X-Z), flecha negra = stride_direction (contexto)"
    )
    ax.set_aspect("equal")

    half_window = max(horizontal_extent * 0.9, body_radius_p60 * 1.3)
    ax.set_xlim(centroid[0] - half_window, centroid[0] + half_window)
    ax.set_ylim(centroid[2] + half_window, centroid[2] - half_window)

    fig.tight_layout()
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")


if __name__ == "__main__":
    main()
