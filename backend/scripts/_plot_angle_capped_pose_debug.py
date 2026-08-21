"""Depuración visual (matplotlib, sin Blender) del tope de ÁNGULO de
bisagra en `ik_solver.solve_ik_ccd` (`hinge_max_angle_deg`): para un
modelo dado, en varias fases del ciclo, dibuja la silueta COMPLETA de
cada pata (todas las articulaciones, no solo el pie) resuelta en TRES
variantes superpuestas — sin restringir, restringida solo a EJE
(`hinge_axes_local`, tarea anterior) y restringida a eje + ÁNGULO
(`hinge_max_angle_deg=90.0`, esta tarea) — para comprobar a ojo que el
tope de ángulo no aleja la silueta general de la pata de forma
descabellada respecto a las otras dos, especialmente en los modelos
donde se encontraron los giros extremos de dedos (cow, biped).

Extiende el mismo patrón de `_plot_constrained_pose_debug.py` (que se
deja intacto, sin tocar) añadiendo una tercera variante en vez de
modificarlo in-place.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`).

Uso:
    python backend/scripts/_plot_angle_capped_pose_debug.py <modelo> <salida.png>
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
    compute_safe_amplitudes,
    detect_stride_direction,
    foot_target_at_phase,
)
from backend.app.ik_solver import (
    DEFAULT_HINGE_MAX_ANGLE_DEG,
    chain_bone_names,
    name_to_node_index,
    solve_ik_ccd,
)
from backend.app.joint_limits import compute_hinge_axes, hinge_axes_in_local_frame
from backend.app.limb_classification import classify_support_limbs
from backend.app.skeletonization import build_skeleton_tree
from backend.app.skinning_quality import compute_global_matrices, trs_to_matrix, read_skin_data

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"
_NUM_PHASES = 5


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
        print("Uso: python _plot_angle_capped_pose_debug.py <cow|biped|bat> <salida.png>")
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    skin_data = read_skin_data(str(_SAMPLES_DIR / "_debug" / f"{model}_rigged.glb"))
    direction = detect_stride_direction(limbs, tree)
    amplitudes = compute_safe_amplitudes(limbs, tree, hierarchy, direction)

    fig, axes = plt.subplots(1, len(limbs), figsize=(4.5 * len(limbs), 5))
    if len(limbs) == 1:
        axes = [axes]

    phases = [i / _NUM_PHASES for i in range(_NUM_PHASES)]
    cmap = plt.get_cmap("viridis")

    for ax, limb in zip(axes, sorted(limbs, key=lambda l: l.chain_root)):
        bind_foot = np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
        chain_root_pos = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
        amplitude = amplitudes[limb.chain_root]

        world_axes = compute_hinge_axes(limb, hierarchy, tree)
        local_axes = hinge_axes_in_local_frame(skin_data, world_axes)

        for i, phase in enumerate(phases):
            color = cmap(i / max(_NUM_PHASES - 1, 1))
            target = foot_target_at_phase(
                bind_foot, chain_root_pos, direction, phase, stride_amplitude_pct=amplitude
            )

            unconstrained = solve_ik_ccd(skin_data, limb, hierarchy, bind_foot, target)
            axis_only = solve_ik_ccd(
                skin_data, limb, hierarchy, bind_foot, target,
                hinge_axes_local=local_axes, hinge_max_angle_deg=1000.0,
            )
            axis_and_angle = solve_ik_ccd(
                skin_data, limb, hierarchy, bind_foot, target,
                hinge_axes_local=local_axes, hinge_max_angle_deg=DEFAULT_HINGE_MAX_ANGLE_DEG,
            )

            for result, style, label in [
                (unconstrained, ":", "sin restringir" if i == 0 else None),
                (axis_only, "--", "solo eje" if i == 0 else None),
                (axis_and_angle, "-", "eje + ángulo (90°)" if i == 0 else None),
            ]:
                positions = _chain_positions(skin_data, limb, hierarchy, result.local_rotations)
                xs = [p[0] for p in positions]
                ys = [p[1] for p in positions]
                ax.plot(xs, ys, style, color=color, linewidth=1.5, marker="o", markersize=3, label=label)

        ax.set_title(f"chain_root={limb.chain_root}", fontsize=9)
        ax.set_xlabel("X")
        ax.set_ylabel("Y (altura)")
        ax.set_aspect("equal")
        ax.legend(fontsize=6, loc="best")

    fig.suptitle(
        f"{model}: silueta de pata sin restringir (punteado) vs solo-eje (discontinuo) "
        f"vs eje+ángulo≤90° (sólido)\ncolor = fase del ciclo ({_NUM_PHASES} fases, viridis oscuro->claro)",
        fontsize=10,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")


if __name__ == "__main__":
    main()
