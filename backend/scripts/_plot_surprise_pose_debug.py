"""Depuración visual (matplotlib, sin Blender) de la pose de "asombro"
(`gait_cycle.surprise_pose_phase_offsets`): para un modelo dado, dibuja
la silueta lateral COMPLETA de cada pata (todas las articulaciones, no
solo el pie) en la pose de asombro (`global_phase=0.25`, todas las
patas en fase) superpuesta contra la MISMA fase global de la marcha
normal (reparto alternado/diagonal de `assign_limb_phase_offsets`) —
para comprobar a ojo que en la pose de asombro TODAS las patas están
claramente en el mismo momento del ciclo (todas extendidas/elevadas a
la vez), a diferencia de la marcha normal donde se alternan.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`). Mismo patrón de estilo
que `_plot_constrained_pose_debug.py` / `_plot_angle_capped_pose_debug.py`.

Uso:
    python backend/scripts/_plot_surprise_pose_debug.py <modelo> <salida.png>
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
    surprise_pose_phase_offsets,
)
from backend.app.ik_solver import chain_bone_names, name_to_node_index
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import compute_global_matrices, trs_to_matrix, read_skin_data

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_GLOBAL_PHASE = 0.25  # pico de elevación — ver docstring de surprise_pose_phase_offsets


def _chain_positions(skin_data, limb, hierarchy, local_rotations) -> list[np.ndarray]:
    local_matrix_of = {
        node_index: trs_to_matrix(trs.translation, local_rotations.get(node_index, trs.rotation), trs.scale)
        for node_index, trs in skin_data.node_trs.items()
    }
    globals_ = compute_global_matrices(
        skin_data.root_node_index, skin_data.node_children, local_matrix_of
    )
    name_to_index = name_to_node_index(skin_data)
    bone_names = chain_bone_names(limb, hierarchy)  # foot -> root
    positions = []
    for bone_name in reversed(bone_names):  # root -> foot
        node_index = name_to_index[bone_name]
        positions.append(globals_[node_index][:3, 3])
    return positions


def main() -> None:
    if len(sys.argv) != 3:
        print("Uso: python _plot_surprise_pose_debug.py <cow|biped|bat> <salida.png>")
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    skin_data = read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{model}_rigged.glb"))
    direction = detect_stride_direction(limbs, tree)
    amplitudes = compute_safe_amplitudes(limbs, tree, hierarchy, direction)

    normal_offsets = assign_limb_phase_offsets(limbs, tree, direction)
    surprise_offsets = surprise_pose_phase_offsets(limbs)

    normal_combined, _ = solve_gait_cycle_pose(
        skin_data, limbs, tree, hierarchy, _GLOBAL_PHASE, direction, normal_offsets, amplitudes
    )
    surprise_combined, _ = solve_gait_cycle_pose(
        skin_data, limbs, tree, hierarchy, _GLOBAL_PHASE, direction, surprise_offsets, amplitudes
    )

    limbs_sorted = sorted(limbs, key=lambda limb: limb.chain_root)
    fig, ax = plt.subplots(1, 1, figsize=(6, 6))
    cmap = plt.get_cmap("tab10")

    for i, limb in enumerate(limbs_sorted):
        color = cmap(i % 10)
        normal_positions = _chain_positions(skin_data, limb, hierarchy, normal_combined)
        surprise_positions = _chain_positions(skin_data, limb, hierarchy, surprise_combined)

        xs_n = [p[2] for p in normal_positions]  # eje Z (stride_direction en los tests)
        ys_n = [p[1] for p in normal_positions]
        xs_s = [p[2] for p in surprise_positions]
        ys_s = [p[1] for p in surprise_positions]

        ax.plot(xs_n, ys_n, "--", color=color, linewidth=1.5, marker="o", markersize=3,
                 label=f"chain_root={limb.chain_root} marcha normal" if i < len(limbs_sorted) else None)
        ax.plot(xs_s, ys_s, "-", color=color, linewidth=2.5, marker="o", markersize=4,
                 label=f"chain_root={limb.chain_root} asombro")

    ax.set_xlabel("Z (stride_direction)")
    ax.set_ylabel("Y (altura)")
    ax.set_aspect("equal")
    ax.legend(fontsize=7, loc="best")
    ax.set_title(
        f"{model}: pose de asombro (sólido, todas en fase) vs marcha normal "
        f"(discontinuo, alternada/diagonal)\nmisma global_phase={_GLOBAL_PHASE} en ambas",
        fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")


if __name__ == "__main__":
    main()
