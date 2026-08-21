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

**Decisión de diseño — dónde vive la seguridad de amplitud
(`safe_stride_amplitude_pct`)**: NO se mete dentro de
`foot_target_at_phase` como recorte implícito. Esa función se mantiene
como una fórmula geométrica pura (posición objetivo dada una amplitud ya
decidida), sin conocer nada de cinemática ni de si el resultado es
alcanzable — igual separación de responsabilidades que ya usa el
proyecto entre "calcular algo" y los `verify_*` que lo comprueban aparte.
`safe_stride_amplitude_pct` es un PASO EXPLÍCITO PREVIO que quien vaya a
generar la trayectoria de una pata llama UNA VEZ (no en cada fase) antes
del bucle de fases, para decidir qué `stride_amplitude_pct` usar en las
llamadas a `foot_target_at_phase` de ese ciclo completo — así
`foot_target_at_phase` sigue siendo determinista y fácil de razonar de
forma aislada, y el ajuste de seguridad es visible y opcional en el
código de quien la usa (`test_gait_cycle.py` es el primer caso real de
este flujo), no un efecto secundario oculto.
"""
from __future__ import annotations

import math

import networkx as nx
import numpy as np

from backend.app.ik_solver import chain_bone_names
from backend.app.limb_classification import LimbChain

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


def max_chain_bone_length(limb: LimbChain, hierarchy: dict[int, "int | None"], tree: nx.Graph) -> float:
    """Longitud física máxima real de la cadena de la pata: suma de las
    longitudes de CADA hueso desde `chain_root` hasta `foot_leaf` (no la
    distancia en línea recta `chain_root_position` -> `bind_foot_position`
    que usa `foot_target_at_phase` como escala — esa es una cota inferior
    de esta, coinciden solo si la pata está perfectamente estirada en
    bind pose).

    Reutiliza `ik_solver.chain_bone_names` para obtener los huesos de la
    cadena en orden (cada nombre "bone_P_C" es una arista del árbol de
    esqueleto) y mide la distancia real entre esos dos nodos en `tree`
    (mismo árbol que produjo `hierarchy` — `build_skeleton_tree`).

    Es el límite kinemático DURO de la pata: con huesos rígidos y sin
    límites articulares (los límites articulares son una fase
    posterior), ningún punto a más de esta distancia de `chain_root` es
    alcanzable, sin importar cuánto itere CCD.
    """
    total_length = 0.0
    for bone_name in chain_bone_names(limb, hierarchy):
        _, parent_str, child_str = bone_name.split("_")
        parent_pos = tree.nodes[int(parent_str)]["pos"]
        child_pos = tree.nodes[int(child_str)]["pos"]
        total_length += math.dist(parent_pos, child_pos)
    return total_length


def safe_stride_amplitude_pct(
    bind_foot_position: np.ndarray,
    chain_root_position: np.ndarray,
    max_chain_length: float,
    stride_direction: np.ndarray,
    lift_height_pct: float = 0.15,
    safe_fraction: float = 0.87,
    requested_amplitude_pct: float = 0.3,
    num_phase_samples: int = 200,
    num_search_iterations: int = 40,
) -> float:
    """Mayor ``stride_amplitude_pct`` ≤ ``requested_amplitude_pct`` tal
    que, en NINGUNA fase del ciclo, la distancia entre ``chain_root_position``
    y el objetivo de `foot_target_at_phase` supere ``safe_fraction ·
    max_chain_length``.

    Por qué hace falta (hallazgo documentado en el checkpoint del
    2026-08-20 de CLAUDE.md): con `stride_amplitude_pct` fijo sobre el
    alcance en línea recta (`reach`, no `max_chain_length`), algunas
    patas piden objetivos por encima del ~87% de su longitud física
    máxima real en ciertas fases — ahí CCD converge extremadamente
    despacio por proximidad a la extensión completa de la cadena
    (geometría casi degenerada: un triángulo pivote-efector-objetivo casi
    plano no tiene una dirección de rotación bien definida que reduzca el
    error rápido). Esta función recorta la amplitud SOLO cuando hace
    falta, muestreando la fase igual que ``verify_never_below_ground``
    (no hay una forma cerrada simple porque el punto más lejano de
    ``chain_root_position`` a lo largo del ciclo depende de cómo se
    combinan el offset horizontal y el vertical, que no son colineales en
    general).

    Si ``requested_amplitude_pct`` ya cumple la condición sin recortar,
    se devuelve tal cual — las patas que ya convergían bien con la
    amplitud pedida no deben cambiar de comportamiento (verificado en
    `test_gait_cycle.py`: mismo orden de magnitud de iteraciones que
    antes de este cambio para esas patas).

    ``safe_fraction=0.87`` por defecto — calibrado empíricamente contra
    LAS DOS patas conocidas, no solo la problemática:

    - `chain_root=27` (cow, la que falla sin recorte): con
      `safe_fraction` en 0.868-0.87 el recorte da amplitudes muy
      similares (0.081-0.093) y `solve_ik_ccd` converge en las 30 fases
      del ciclo con margen cómodo (máx. 324-325 de 500 iteraciones,
      65% del presupuesto — ya no "pegado al límite"). Con 0.92 o 0.95
      el recorte es casi nulo (amplitud final 0.2975-0.3) y las mismas 4
      fases siguen sin converger ni con 500 iteraciones — no basta con
      subir el `safe_fraction`, hay que quedarse cerca de la banda que
      de verdad excluye las fases problemáticas.
    - `chain_root=31` (cow, la que YA convergía bien sin recorte, 158
      iteraciones): su distancia máxima real a lo largo del ciclo, con
      la amplitud pedida (0.3) sin tocar, es **86.7%** de su longitud
      máxima — un primer intento con `safe_fraction=0.85` (más bajo)
      recortaba esta pata también (a amplitud 0.238), violando el
      requisito de que las patas que ya iban bien no cambien de
      comportamiento. 0.87 queda justo por encima de ese 86.7%, así que
      `chain_root=31` sigue devolviendo la amplitud pedida sin modificar
      (158 iteraciones, idénticas a antes de este cambio).

    Nota honesta: el % de la longitud máxima alcanzado NO es un
    predictor perfecto por sí solo de si CCD converge rápido — a modo de
    ejemplo, `chain_root=31` llega al 86.7% y converge en 158
    iteraciones, mientras que `chain_root=27` ya falla en fases con un
    87.0% (la geometría concreta de cada cadena, qué huesos necesitan
    doblarse y en qué dirección, importa además del porcentaje). Aun así,
    recortar por este criterio relativo resuelve el caso conocido sin
    tocar el que no lo necesitaba, que es el objetivo de esta tarea.

    Búsqueda binaria sobre la amplitud (``num_search_iterations`` pasos,
    cada uno evaluando ``num_phase_samples`` fases) — asume que la
    distancia máxima a `chain_root_position` a lo largo del ciclo crece
    con la amplitud (cierto por construcción: solo escala la magnitud del
    componente horizontal, todo lo demás fijo), así que basta encontrar
    el punto de corte, no hace falta una forma cerrada.

    Caso límite: si NI SIQUIERA amplitud 0 cumple la condición (una pata
    cuya `bind_foot_position` más la elevación del salto ya está por
    encima de `safe_fraction · max_chain_length` sin ningún movimiento
    horizontal), la búsqueda binaria devuelve 0.0 igualmente — es lo
    mejor que se puede hacer sin amplitud negativa. No aparece en los 3
    samples (la pata más cercana al límite, `chain_root=27`, todavía deja
    margen para amplitud 0.09 con `safe_fraction=0.87`), pero si ocurriera
    en un futuro modelo sería la señal de que este `chain_root` concreto
    ya está casi en extensión completa incluso en bind pose — haría falta
    revisar la propia clasificación de la pata o sus límites articulares,
    no este recorte.
    """
    chain_root_position = np.asarray(chain_root_position, dtype=np.float64)
    safe_limit = safe_fraction * max_chain_length

    def worst_case_distance(amplitude_pct: float) -> float:
        worst = 0.0
        for i in range(num_phase_samples):
            phase = i / num_phase_samples
            target = foot_target_at_phase(
                bind_foot_position,
                chain_root_position,
                stride_direction,
                phase,
                stride_amplitude_pct=amplitude_pct,
                lift_height_pct=lift_height_pct,
            )
            distance = float(np.linalg.norm(target - chain_root_position))
            worst = max(worst, distance)
        return worst

    if worst_case_distance(requested_amplitude_pct) <= safe_limit:
        return requested_amplitude_pct

    low, high = 0.0, requested_amplitude_pct
    for _ in range(num_search_iterations):
        mid = (low + high) / 2.0
        if worst_case_distance(mid) <= safe_limit:
            low = mid
        else:
            high = mid
    return low


def detect_stride_direction(limbs: list[LimbChain], tree: nx.Graph) -> np.ndarray:
    """Determina automáticamente el eje de zancada del modelo a partir de
    dónde están las patas — hasta ahora `stride_direction` se pasaba a
    mano (ver checkpoints anteriores).

    Dos casos, según cuántas patas hay (usa `chain_root_position` de cada
    `LimbChain`, no `foot_leaf` — `chain_root` es el punto de la
    cadera/hombro, más estable y menos sujeto a la pose concreta de la
    punta del pie):

    - **2 patas** (biped, bat en estos samples): el eje de zancada es la
      dirección HORIZONTAL perpendicular a la línea entre las dos
      `chain_root_position` (proyectada al plano XZ) — dos patas por sí
      solas no dan información de "a lo largo de qué" salvo la línea que
      las une, y la zancada va perpendicular a esa línea (adelante/atrás
      respecto al eje cadera-cadera u hombro-hombro), no a lo largo de
      ella.
    - **3+ patas** (cow en estos samples): PCA sobre las posiciones
      (X, Z) de TODOS los `chain_root_position` — el eje de mayor
      varianza es, para un cuadrúpedo con patas repartidas a lo largo del
      cuerpo, el eje longitudinal del propio cuerpo (de un extremo a
      otro), que es la dirección natural de zancada. Con solo 2 patas
      esto degenera (la "varianza máxima" sería trivialmente la propia
      línea que las une, dando el eje EQUIVOCADO — a lo largo en vez de
      perpendicular), de ahí el caso especial de arriba.

    **Limitación conocida, deliberada, no resuelta en esta tarea**: el
    SIGNO del vector devuelto es arbitrario (no se resuelve cuál extremo
    es "adelante") — no hace falta resolverlo todavía porque
    `foot_target_at_phase` es simétrico respecto al signo de
    `stride_direction`: invertir el signo solo desplaza la fase del ciclo
    medio periodo (`phase=0` pasaría a pedir lo que antes pedía
    `phase=0.5`), no cambia la FORMA de la trayectoria ni si converge —
    verificado explícitamente en `test_gait_cycle.py`. Resolver el signo
    (qué extremo del eje detectado es de verdad "el morro"/"la cabeza")
    es tarea de coordinación multi-pata (necesita saber dónde está la
    cabeza/cola, no solo dónde están las patas).
    """
    if len(limbs) < 2:
        raise ValueError(
            f"Hacen falta al menos 2 patas para detectar una dirección de "
            f"zancada, hay {len(limbs)}"
        )

    positions = np.array(
        [tree.nodes[limb.chain_root]["pos"] for limb in limbs], dtype=np.float64
    )

    if len(limbs) == 2:
        delta = positions[1] - positions[0]
        delta_horizontal = np.array([delta[0], 0.0, delta[2]])
        norm = np.linalg.norm(delta_horizontal)
        if norm < 1e-9:
            raise ValueError(
                "Las dos patas están en la misma posición horizontal (X,Z) — "
                "no se puede derivar una dirección perpendicular"
            )
        line_direction = delta_horizontal / norm
        # Rotación de 90° en el plano XZ (Y fijo en 0): (x,z) -> (z,-x).
        # El signo de esta rotación es arbitrario — ver docstring.
        direction = np.array([line_direction[2], 0.0, -line_direction[0]])
    else:
        xz = positions[:, [0, 2]]
        centered = xz - xz.mean(axis=0)
        covariance = np.cov(centered, rowvar=False)
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        principal_axis_xz = eigenvectors[:, int(np.argmax(eigenvalues))]
        direction = np.array([principal_axis_xz[0], 0.0, principal_axis_xz[1]])

    direction = direction / np.linalg.norm(direction)

    if abs(direction[1]) > _STRIDE_DIRECTION_Y_TOLERANCE:
        raise AssertionError(
            f"detect_stride_direction produjo un vector no horizontal "
            f"(componente Y = {direction[1]!r}) — bug en la construcción del "
            "vector, no debería poder pasar por cómo se construye"
        )

    return direction
