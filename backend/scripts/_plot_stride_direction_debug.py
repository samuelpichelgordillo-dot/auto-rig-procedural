"""Depuración visual (matplotlib, sin Blender) de
`gait_cycle.detect_stride_direction`: vista cenital (plano X-Z, mirando
hacia abajo por el eje Y) mostrando las posiciones de `chain_root` de
TODAS las patas de un modelo, con una flecha desde su centroide en la
dirección de zancada detectada.

Utilidad de un solo uso para nuestra propia inspección — no forma parte
de los tests automatizados (`backend/tests/`).

Uso:
    python backend/scripts/_plot_stride_direction_debug.py <modelo> <salida.png>
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
from backend.app.skeletonization import build_skeleton_tree

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


def main() -> None:
    if len(sys.argv) != 3:
        print(
            "Uso: python _plot_stride_direction_debug.py <cow|biped|bat> <salida.png>"
        )
        sys.exit(1)
    model, output_png = sys.argv[1], sys.argv[2]

    tree, root, hierarchy = build_skeleton_tree(str(_SAMPLES_DIR / f"{model}_unrigged.glb"))
    limbs = classify_support_limbs(tree, root, hierarchy)
    direction = detect_stride_direction(limbs, tree)

    chain_root_positions = np.array(
        [tree.nodes[limb.chain_root]["pos"] for limb in limbs], dtype=np.float64
    )
    foot_positions = np.array(
        [tree.nodes[limb.foot_leaf]["pos"] for limb in limbs], dtype=np.float64
    )
    all_positions = np.array([tree.nodes[n]["pos"] for n in tree.nodes], dtype=np.float64)

    fig, ax = plt.subplots(figsize=(8, 8))

    # Silueta tenue de todo el esqueleto (X-Z), solo para dar contexto de forma.
    ax.scatter(all_positions[:, 0], all_positions[:, 2], color="lightgray", s=8, zorder=1)

    for i, (limb, root_pos, foot_pos) in enumerate(zip(limbs, chain_root_positions, foot_positions)):
        ax.plot(
            [root_pos[0], foot_pos[0]], [root_pos[2], foot_pos[2]],
            "o-", color="black", linewidth=1.5, markersize=5, zorder=3,
        )
        ax.annotate(
            f"chain_root={limb.chain_root}", (root_pos[0], root_pos[2]),
            textcoords="offset points", xytext=(6, 6), fontsize=8, zorder=4,
        )

    centroid = chain_root_positions.mean(axis=0)
    # Escala a partir de la dispersión horizontal (X-Z) de las propias
    # patas, no de la diagonal 3D completa del modelo — un cuerpo alto
    # pero delgado en Z (biped) haría la flecha invisible/desproporcionada
    # si se escalase con la altura (dominante en la diagonal 3D).
    xz_spread = chain_root_positions[:, [0, 2]]
    horizontal_extent = float(
        np.linalg.norm(xz_spread.max(axis=0) - xz_spread.min(axis=0))
    )
    if horizontal_extent < 1e-6:
        horizontal_extent = float(np.linalg.norm(all_positions.max(axis=0) - all_positions.min(axis=0)))
    arrow_length = horizontal_extent * 0.6

    # Percentil 60 de la distancia (X-Z) de cada nodo del esqueleto al
    # centroide de las patas — usado como suelo para la ventana de la
    # vista, así se ve suficiente silueta del cuerpo (cabeza, ala...) para
    # juzgar a ojo si la flecha va "a lo largo del cuerpo". Percentil en
    # vez de min/max: un puñado de puntos muy alejados (dedos de una mano
    # totalmente extendida en T-pose, p. ej. biped) no debe poder dominar
    # la escala de la ventana.
    all_xz = all_positions[:, [0, 2]]
    centroid_xz = np.array([centroid[0], centroid[2]])
    distances_to_centroid = np.linalg.norm(all_xz - centroid_xz, axis=1)
    body_radius_p60 = float(np.percentile(distances_to_centroid, 60))

    ax.annotate(
        "",
        xy=(centroid[0] + direction[0] * arrow_length, centroid[2] + direction[2] * arrow_length),
        xytext=(centroid[0], centroid[2]),
        arrowprops=dict(facecolor="red", edgecolor="red", width=3, headwidth=12),
        zorder=5,
    )
    ax.scatter([centroid[0]], [centroid[2]], color="red", s=40, zorder=5, label="centroide de chain_root")

    ax.set_xlabel("X")
    ax.set_ylabel("Z")
    ax.set_title(
        f"{model}: stride_direction detectado = ({direction[0]:.3f}, 0, {direction[2]:.3f})\n"
        f"{len(limbs)} patas — vista cenital (X-Z), flecha = dirección de zancada (signo arbitrario)"
    )
    ax.legend(loc="best", fontsize=8)
    ax.set_aspect("equal")

    # Ventana centrada en las patas, no en el bbox X-Z de todo el cuerpo:
    # un cuerpo mucho más ancho que profundo (biped en T-pose, brazos
    # extendidos en X) haría la flecha imperceptible si la vista se
    # autoescalase a los puntos grises de contexto. El eje Z se invierte
    # (ylim descendente) para que sea más intuitivo en una vista cenital.
    half_window = max(horizontal_extent * 0.9, body_radius_p60 * 1.3)
    ax.set_xlim(centroid[0] - half_window, centroid[0] + half_window)
    ax.set_ylim(centroid[2] + half_window, centroid[2] - half_window)

    fig.tight_layout()
    fig.savefig(output_png, dpi=150)
    print(f"Guardado: {output_png}")


if __name__ == "__main__":
    main()
