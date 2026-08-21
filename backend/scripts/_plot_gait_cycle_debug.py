"""Depuración visual (matplotlib, sin Blender) de
`gait_cycle.solve_gait_cycle_pose`: para un modelo dado, un subplot por
pata mostrando la altura (Y) del pie resuelto por IK a lo largo de
`global_phase` en [0,1) — así se ve de un vistazo el patrón de
swing/stance de cada pata y si las que comparten grupo de fase realmente
suben y bajan EN FASE mientras las del otro grupo lo hacen desfasadas
medio ciclo.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`). Mismo patrón de estilo
que `_plot_stride_direction_debug.py` / `_plot_phase_offsets_debug.py`.

Uso:
    python backend/scripts/_plot_gait_cycle_debug.py <modelo> <salida.png>
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from backend.app.gait_cycle import (
    assign_limb_phase_offsets,
    compute_safe_amplitudes,
    detect_stride_direction,
    solve_gait_cycle_pose,
)
from backend.app.ik_solver import foot_position_given_rotations, tip_bone_and_offset
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import read_skin_data

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_NUM_PHASE_SAMPLES = 40
_OFFSET_COLOR = {0.0: "tab:blue", 0.5: "tab:red"}


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python _plot_gait_cycle_debug.py <cow|biped|bat> <salida.png>")
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    skin_data = read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{model}_rigged.glb"))
    direction = detect_stride_direction(limbs, tree)
    offsets = assign_limb_phase_offsets(limbs, tree, direction)
    amplitudes = compute_safe_amplitudes(limbs, tree, hierarchy, direction)

    tip_info = {
        limb.chain_root: tip_bone_and_offset(
            skin_data, limb, hierarchy, np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
        )
        for limb in limbs
    }

    phases = [i / _NUM_PHASE_SAMPLES for i in range(_NUM_PHASE_SAMPLES)]
    heights_by_root: dict[int, list[float]] = {limb.chain_root: [] for limb in limbs}
    converged_by_root: dict[int, list[bool]] = {limb.chain_root: [] for limb in limbs}

    for global_phase in phases:
        combined, results = solve_gait_cycle_pose(
            skin_data, limbs, tree, hierarchy, global_phase, direction, offsets, amplitudes
        )
        for limb in limbs:
            tip_index, tip_offset = tip_info[limb.chain_root]
            foot_pos = foot_position_given_rotations(skin_data, tip_index, tip_offset, combined)
            heights_by_root[limb.chain_root].append(float(foot_pos[1]))
            converged_by_root[limb.chain_root].append(results[limb.chain_root].converged)

    limbs_sorted = sorted(limbs, key=lambda limb: limb.chain_root)
    fig, axes = plt.subplots(len(limbs_sorted), 1, figsize=(8, 2.2 * len(limbs_sorted)), sharex=True)
    if len(limbs_sorted) == 1:
        axes = [axes]

    for ax, limb in zip(axes, limbs_sorted):
        color = _OFFSET_COLOR[offsets[limb.chain_root]]
        heights = heights_by_root[limb.chain_root]
        converged = converged_by_root[limb.chain_root]
        ax.plot(phases, heights, "-o", color=color, markersize=4)
        for phase, height, ok in zip(phases, heights, converged):
            if not ok:
                ax.plot(phase, height, "x", color="black", markersize=10, zorder=5)
        ax.set_ylabel("altura Y")
        ax.set_title(
            f"chain_root={limb.chain_root}  phase_offset={offsets[limb.chain_root]}",
            fontsize=9, loc="left",
        )
        ax.grid(alpha=0.3)

    axes[-1].set_xlabel("global_phase")
    fig.suptitle(
        f"{model}: altura del pie por pata a lo largo del ciclo\n"
        "azul=phase_offset 0.0, rojo=phase_offset 0.5 — 'x' negra = fase que no convergió",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")


if __name__ == "__main__":
    main()
