"""Módulo 4 — micro-movimientos: respiración.

Primera pieza del Módulo 4: una oscilación sinusoidal MUY pequeña de
rotación aplicada directamente a la rotación LOCAL de la raíz del
esqueleto (``skin_data.root_node_index``, mismo nodo que
`joint_limits.py`/`ik_solver.py` ya tratan como "la raíz de todo" en
`compute_global_matrices` — ver
`test_hinge_axis_co_rotates_with_ancestor_perturbation` en
`test_joint_limits.py`, que perturba exactamente ese mismo nodo para
simular un movimiento del ancestro común).

**Por qué la raíz entera y no un hueso de "pecho"**: se descartó buscar
un hueso de torso/pecho específico por el mismo motivo ya documentado
para el signo de `stride_direction` (checkpoint Módulo 3, "decisión de
no perseguirlo") — un heurístico de ramificación es frágil. Comprobado
aquí también: seguir "la rama con más descendientes no-pata" desde la
raíz se desvía hacia brazos/cabeza (alta ramificación de dedos) en vez
de seguir la columna real. En vez de eso, la respiración es una
aproximación deliberada de "balanceo sutil de todo el torso" mediante
una rotación de la raíz — no una animación anatómicamente precisa de
caja torácica, y se documenta como tal.

**Limitación conocida y ACEPTADA de esta pieza (no resuelta aquí)**:
esta función NO integra con el ciclo de marcha activo. Si se combina la
rotación de la raíz con `solve_gait_cycle_pose` sin más, los pies
podrían deslizarse ligeramente sobre el suelo durante la fase de
"stance" (la posición del pie se calcula como cinemática directa desde
la raíz hacia abajo; rotar la raíz mueve el origen de esa cadena aunque
el objetivo de IK del pie no cambie). Resolver esto (p. ej. recalcular
el objetivo del pie compensando la rotación de la raíz, o solo aplicar
respiración en poses estáticas sin locomoción activa) es tarea de una
integración posterior, no de esta pieza aislada.

**Por qué NO depende del signo de `stride_direction`**: a diferencia de
la marcha (que necesita saber cuál extremo es "adelante" para que la
zancada tenga sentido direccional), un balanceo simétrico de ida y
vuelta alrededor de `side_axis` se ve igual de plausible sea cual sea
el signo real del eje — mismo argumento ya usado para
`gait_cycle.surprise_pose_phase_offsets` (todas las patas moviéndose
hacia el mismo lado relativo a la vez, sin importar cuál sea "adelante"
de verdad).
"""
from __future__ import annotations

import math

import numpy as np

from backend.app.skinning_quality import axis_angle_to_quat

# Sin ninguna fuente de datos biológicos por especie en este proyecto,
# usar un único valor razonable de "reposo tranquilo" para las 3 es más
# honesto que fingir precisión zoológica que no tenemos base para dar.
DEFAULT_BREATHS_PER_MINUTE = 15.0

# Calibrado con datos reales de los 3 modelos (ver checkpoint de
# CLAUDE.md, Módulo 4): el desplazamiento aproximado resultante en la
# posición del pie (`radians(max_amplitude_deg) * (dist_raíz_a_chain_root
# + max_chain_bone_length)`) queda entre el 2.98% y el 6.11% de la
# longitud de cadena de cada una de las 8 patas de los 3 modelos —
# claramente sutil frente a las amplitudes de zancada normales (30%+ de
# esa misma referencia, ver `gait_cycle.foot_target_at_phase`).
DEFAULT_MAX_AMPLITUDE_DEG = 1.5


def breathing_local_rotation(
    t: float,
    side_axis: np.ndarray,
    breaths_per_minute: float = DEFAULT_BREATHS_PER_MINUTE,
    max_amplitude_deg: float = DEFAULT_MAX_AMPLITUDE_DEG,
) -> np.ndarray:
    """Cuaternión de rotación (a componer con la rotación LOCAL de bind
    pose de la raíz del esqueleto, p. ej. vía
    ``quat_multiply(breathing_local_rotation(...), root_bind_rotation)``
    — mismo patrón que ya usa
    `test_hinge_axis_co_rotates_with_ancestor_perturbation`) que
    representa la respiración en el instante ``t`` (segundos).

    ``side_axis``: eje lateral del cuerpo, mismo criterio ya usado en
    `gait_cycle.assign_limb_phase_offsets`
    (``cross((0,1,0), stride_direction)``, normalizado) — no se
    normaliza aquí porque `axis_angle_to_quat` ya lo hace internamente,
    pero se espera un vector no nulo.

    Ángulo instantáneo: ``max_amplitude_deg * sin(2π ·
    breaths_per_minute/60 · t)`` grados, convertido a radianes antes de
    pasar a `axis_angle_to_quat`. En ``t=0`` el ángulo es exactamente 0
    (``sin(0)=0``), así que el cuaternión devuelto es la identidad
    ``[0,0,0,1]`` — la respiración no produce ningún salto visible si la
    animación arranca en ``t=0`` desde bind pose.
    """
    breaths_per_second = breaths_per_minute / 60.0
    angle_deg = max_amplitude_deg * math.sin(2 * math.pi * breaths_per_second * t)
    angle_rad = math.radians(angle_deg)
    return axis_angle_to_quat(side_axis, angle_rad)


# Nº de senos sumados para el ruido de baja frecuencia — 3, ni 2 (se lee
# demasiado regular/predecible, casi como la propia respiración) ni más
# (rendimientos decrecientes para "ruido de idle" perceptible en una
# rotación de amplitud ya de por sí pequeña).
DEFAULT_LOW_FREQUENCY_NOISE_COMPONENTS = 3

# Los multiplicadores de frecuencia por componente se sortean dentro de
# este rango alrededor de `base_frequency_hz` — lo bastante separados
# entre sí para que la suma no colapse en un único seno efectivo (batido
# casi nulo), lo bastante juntos para que las 3 componentes sigan
# leyéndose como "una sola cosa moviéndose", no 3 osciladores
# independientes y desincronizados.
_FREQUENCY_JITTER_RANGE = (0.7, 1.3)


def low_frequency_noise_rotation(
    t: float,
    axis: np.ndarray,
    seed: int,
    max_amplitude_deg: float,
    base_frequency_hz: float = 0.3,
) -> np.ndarray:
    """Cuaternión de rotación (mismo patrón de uso que
    `breathing_local_rotation`: componer con la rotación LOCAL de bind
    pose del hueso objetivo) que representa "ruido" de idle en el
    instante ``t`` — a diferencia de la respiración (un único seno
    limpio y predecible), esto debe leerse como el pequeño temblor
    irregular de un dedo/cola/oreja en reposo, no como una oscilación
    perfectamente periódica.

    Suma `DEFAULT_LOW_FREQUENCY_NOISE_COMPONENTS` senos de frecuencias y
    fases ligeramente distintas, derivadas de ``seed`` de forma
    DETERMINISTA vía ``np.random.default_rng(seed)`` — el generador se
    crea y se muestrea una sola vez por llamada, así que la MISMA
    llamada (mismos argumentos) da siempre el MISMO resultado
    (reproducible, no aleatoriedad real). Las frecuencias se sortean en
    torno a ``base_frequency_hz`` (rango `_FREQUENCY_JITTER_RANGE`) y las
    fases uniformemente en `[0, 2π)`.

    Los pesos de cada componente son iguales (`1 / nº de componentes`),
    así que la suma nunca puede exceder `[-1, 1]` en valor absoluto
    (cada término aporta como máximo su propio peso, y los pesos suman
    1) — multiplicado por `max_amplitude_deg`, la amplitud angular total
    NUNCA excede `max_amplitude_deg`, igual que en `breathing_local_rotation`.

    ``seed`` distinto por cadena (p. ej. el nodo hoja de esa cola/dedo/
    oreja concreta) para que varios apéndices no se muevan todos
    exactamente igual y en fase — verificado en
    `test_low_frequency_noise_seed_changes_result`.

    A diferencia de `breathing_local_rotation`, NO se garantiza
    identidad en `t=0` (las fases son aleatorias por `seed`, no fijas en
    0) — no hace falta: el "ruido" de idle no necesita arrancar
    exactamente en la pose de bind, a diferencia del ciclo de
    respiración que si empieza desincronizado con el resto de la
    animación produciría un salto visible en `t=0`.
    """
    rng = np.random.default_rng(seed)
    num_components = DEFAULT_LOW_FREQUENCY_NOISE_COMPONENTS
    freq_multipliers = rng.uniform(_FREQUENCY_JITTER_RANGE[0], _FREQUENCY_JITTER_RANGE[1], size=num_components)
    phases = rng.uniform(0.0, 2 * math.pi, size=num_components)
    frequencies_hz = base_frequency_hz * freq_multipliers

    weight = 1.0 / num_components
    normalized_signal = sum(
        weight * math.sin(2 * math.pi * freq * t + phase)
        for freq, phase in zip(frequencies_hz, phases)
    )

    angle_deg = max_amplitude_deg * normalized_signal
    angle_rad = math.radians(angle_deg)
    return axis_angle_to_quat(axis, angle_rad)
