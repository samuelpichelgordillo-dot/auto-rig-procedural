"""Módulo 3 — trayectoria del pie de UNA sola pata a lo largo de un ciclo.

Cimiento previo a coordinar varias patas: genera la posición objetivo 3D
del pie de UNA pata para una fase `phase` cualquiera de un ciclo de
marcha/carrera. Nada de desfase entre patas, dirección de zancada
automática (eso depende de saber qué es "delante" del modelo — tarea de
coordinación multi-pata, después) ni coordinación de varias patas
moviéndose a la vez — es deliberadamente "una pata, un ciclo completo,
con el suelo respetado por construcción".

Pensado para encadenarse con `ik_solver.solve_ik_ccd`: la salida de
`foot_target_at_phase` es exactamente el `target_position` que espera
ese solver.
"""
from __future__ import annotations

import math

import numpy as np

_STRIDE_DIRECTION_Y_TOLERANCE = 1e-6


def foot_target_at_phase(
    bind_foot_position: np.ndarray,
    chain_root_position: np.ndarray,
    stride_direction: np.ndarray,
    phase: float,
    stride_amplitude_pct: float = 0.3,
    lift_height_pct: float = 0.15,
) -> np.ndarray:
    """Posición objetivo 3D del pie en la fase `phase` (∈ [0,1), cíclico —
    `phase` fuera de ese rango también funciona, ``cos``/``sin`` ya son
    periódicos en 2π sin necesidad de envolverlo a mano) de un ciclo.

    ``chain_root_position`` es la posición del `chain_root` de la pata
    (`limb_classification.LimbChain.chain_root`, en las mismas unidades y
    ejes que `bind_foot_position` — típicamente ambas vienen de
    `tree.nodes[...]["pos"]` del árbol de esqueleto de `build_skeleton_tree`,
    ejes glTF Y-up). El alcance de la pata, ``|chain_root_position -
    bind_foot_position|``, es la escala de referencia para la amplitud
    horizontal y la altura de elevación — mismo criterio relativo que el
    resto del proyecto (nunca una unidad absoluta nueva).

    ``stride_direction`` se recibe tal cual, NO se calcula aquí (depende
    de saber qué es "delante" del modelo — tarea de coordinación
    multi-pata). Debe ser un vector horizontal (componente Y ~0 tras
    normalizar, plano perpendicular al eje Y) — se normaliza aquí, y se
    lanza ``ValueError`` si no es horizontal en vez de forzarlo en
    silencio, para no enmascarar un vector mal construido más arriba.

    Componentes del resultado:

    - Horizontal, a lo largo de ``stride_direction``:
      ``stride_amplitude_pct · alcance · cos(2π·phase)`` — oscila entre
      +amplitud (phase=0, pie hacia adelante) y -amplitud (phase=0.5, pie
      hacia atrás).
    - Vertical (+Y), añadida sobre la altura de ``bind_foot_position``:
      ``lift_height_pct · alcance · max(0, sin(2π·phase))`` — el pie solo
      se eleva sobre el suelo durante la mitad del ciclo (0 < phase < 0.5,
      fase de "swing"); en la otra mitad (fase de "stance") se queda
      exactamente a la altura de bind pose, nunca por debajo (fuerza de
      construcción, ver `verify_never_below_ground`).
    - El eje horizontal perpendicular a ``stride_direction`` no se toca:
      como solo se suma a lo largo de ``stride_direction`` y en +Y, ese
      componente queda igual que en ``bind_foot_position`` sin necesidad
      de proyección explícita.
    """
    bind_foot_position = np.asarray(bind_foot_position, dtype=np.float64)
    chain_root_position = np.asarray(chain_root_position, dtype=np.float64)
    stride_direction = np.asarray(stride_direction, dtype=np.float64)

    direction_norm = np.linalg.norm(stride_direction)
    if direction_norm < 1e-9:
        raise ValueError("stride_direction no puede ser el vector nulo")
    unit_direction = stride_direction / direction_norm

    if abs(unit_direction[1]) > _STRIDE_DIRECTION_Y_TOLERANCE:
        raise ValueError(
            f"stride_direction debe ser horizontal (componente Y ~0 tras "
            f"normalizar); componente Y normalizada = {unit_direction[1]!r}"
        )

    reach = float(np.linalg.norm(chain_root_position - bind_foot_position))

    horizontal_offset = stride_amplitude_pct * reach * math.cos(2 * math.pi * phase)
    vertical_offset = lift_height_pct * reach * max(0.0, math.sin(2 * math.pi * phase))

    target = bind_foot_position + horizontal_offset * unit_direction
    target[1] += vertical_offset
    return target


def verify_phase_periodicity(
    bind_foot_position: np.ndarray,
    chain_root_position: np.ndarray,
    stride_direction: np.ndarray,
    tolerance: float = 1e-9,
) -> float:
    """Auto-chequeo obligatorio: ``foot_target_at_phase(phase=0)`` y
    ``foot_target_at_phase(phase=1)`` deben coincidir casi exactamente
    (periodicidad del ciclo). Devuelve la distancia entre ambos puntos;
    lanza ``AssertionError`` si supera ``tolerance``.
    """
    target_at_0 = foot_target_at_phase(
        bind_foot_position, chain_root_position, stride_direction, phase=0.0
    )
    target_at_1 = foot_target_at_phase(
        bind_foot_position, chain_root_position, stride_direction, phase=1.0
    )
    error = float(np.linalg.norm(target_at_1 - target_at_0))
    if error >= tolerance:
        raise AssertionError(
            f"foot_target_at_phase no es periódico: |target(1) - target(0)| = "
            f"{error} >= tolerancia {tolerance}"
        )
    return error


def verify_never_below_ground(
    bind_foot_position: np.ndarray,
    chain_root_position: np.ndarray,
    stride_direction: np.ndarray,
    num_samples: int = 1000,
    tolerance: float = 1e-9,
) -> float:
    """Auto-chequeo obligatorio: para NINGUNA fase la coordenada Y del
    resultado debe quedar por debajo de la Y de ``bind_foot_position`` —
    garantizado por construcción vía ``max(0, sin(...))`` en
    `foot_target_at_phase`, pero se comprueba explícitamente aquí
    muestreando muchas fases en vez de fiarse solo de la fórmula.
    Devuelve el peor déficit observado (negativo si alguna muestra
    quedó por debajo — no debería pasar nunca); lanza ``AssertionError``
    si lo hace.
    """
    bind_foot_position = np.asarray(bind_foot_position, dtype=np.float64)
    min_margin = math.inf
    for i in range(num_samples):
        phase = i / num_samples
        target = foot_target_at_phase(
            bind_foot_position, chain_root_position, stride_direction, phase
        )
        margin = float(target[1] - bind_foot_position[1])
        min_margin = min(min_margin, margin)

    if min_margin < -tolerance:
        raise AssertionError(
            f"foot_target_at_phase produjo un pie por debajo de la altura de "
            f"bind pose: déficit máximo {-min_margin} >= tolerancia {tolerance}"
        )
    return min_margin
