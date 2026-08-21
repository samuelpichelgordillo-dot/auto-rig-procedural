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

from backend.app.ik_solver import (
    DEFAULT_MAX_ITERATIONS,
    IKResult,
    chain_bone_names,
    name_to_node_index,
    solve_ik_ccd,
)
from backend.app.limb_classification import LimbChain
from backend.app.skinning_quality import SkinData

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


def assign_limb_phase_offsets(
    limbs: list[LimbChain],
    tree: nx.Graph,
    stride_direction: np.ndarray,
) -> dict[int, float]:
    """Asigna un desfase de fase (`phase_offset`, en {0.0, 0.5}) a cada
    pata, para que varias patas puedan animarse a la vez sin pisarse —
    ``foot_target_at_phase(..., phase=fase_global + phase_offset)`` ya es
    periódica, no hace falta ningún cambio ahí (la propia periodicidad de
    `cos`/`sin` en 2π se encarga). NO conecta todavía con `solve_ik_ccd`
    en un bucle de varias patas — eso es la tarea siguiente.

    Devuelve un dict `chain_root -> phase_offset`.

    Dos casos, mismo estilo de ramificación honesta que
    `detect_stride_direction` (solo cubre lo que aparece en los 3
    samples de este proyecto, no un caso general para cualquier nº de
    patas):

    - **2 patas** (biped, bat): alternancia simple. Se ordenan las patas
      por `chain_root` ascendente para que el resultado sea
      determinista; la primera recibe 0.0, la segunda 0.5. Cuál de las
      dos "empieza" es arbitrario — igual que el signo de
      `stride_direction` (ver su docstring), lo único que importa aquí
      es que las dos patas reciban valores DISTINTOS, no cuál en
      concreto recibe cuál.
    - **4 patas** (cow): patrón de trote por pares diagonales (delantera-
      izquierda + trasera-derecha en fase, delantera-derecha + trasera-
      izquierda en la opuesta — o el espejo, el signo de "izquierda" no
      se resuelve, ver más abajo), SIN necesitar resolver el signo de
      "adelante" ni de "izquierda":

      1. `side_axis = normalizado(cross((0,1,0), stride_direction))` —
         perpendicular horizontal a la zancada, "el otro eje horizontal".
      2. `proj_front` de cada pata = proyección de su
         `chain_root_position` (menos el centroide de todas las
         `chain_root_position`) sobre `stride_direction` — positivo o
         negativo según el LADO del eje de zancada en el que cae esa
         pata (delante/detrás, signo arbitrario).
      3. `proj_side` de cada pata = proyección de su `foot_leaf_position`
         (menos el centroide de todas las `foot_leaf_position`) sobre
         `side_axis` — igual pero para el otro lado (izquierda/derecha,
         signo arbitrario).

         **Por qué `foot_leaf` y NO `chain_root` aquí**: verificado con
         las posiciones reales del modelo (`chain_root=31` y
         `chain_root=33`, las dos patas traseras de cow) — comparten
         EXACTAMENTE la misma `chain_root_position`, porque cuelgan del
         mismo nodo de cadera antes de divergir más abajo en la
         jerarquía (ver checkpoint de `limb_classification.py`: el
         `chain_root` es el hueso concreto de cadera de ESA pata, pero
         dos patas del mismo lado del cuerpo pueden compartir esa misma
         posición si la bifurcación real está un nivel más arriba de lo
         que separa ambas cadenas). Usar `chain_root_position` para
         `proj_side` colapsaría la proyección lateral a ~0 para ambas
         patas traseras y rompería el agrupamiento por pares —
         `foot_leaf_position` sí diverge entre patas siempre (es
         literalmente el punto de apoyo en el suelo, nunca compartido
         entre dos patas distintas).
      4. Grupo de cada pata: `"A"` si `sign(proj_front) == sign(proj_side)`
         (delante-de-un-lado + detrás-del-lado-opuesto caen en el mismo
         signo relativo), si no `"B"`. Grupo A -> `phase_offset` 0.0,
         grupo B -> `phase_offset` 0.5.
      5. Se comprueba internamente (`assert`, sin silenciar) que salen
         exactamente 2 patas por grupo — si no, algo está mal en la
         clasificación de patas de entrada (`classify_support_limbs`),
         mejor fallar ruidosamente que devolver un reparto sin sentido.

    - **Cualquier otro nº de patas**: `NotImplementedError` explícito —
      solo 2 o 4 patas están cubiertas por los samples actuales de este
      proyecto.
    """
    if len(limbs) == 2:
        ordered = sorted(limbs, key=lambda limb: limb.chain_root)
        return {ordered[0].chain_root: 0.0, ordered[1].chain_root: 0.5}

    if len(limbs) == 4:
        side_axis = np.cross(np.array([0.0, 1.0, 0.0]), stride_direction)
        side_axis = side_axis / np.linalg.norm(side_axis)

        chain_root_positions = {
            limb.chain_root: np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
            for limb in limbs
        }
        foot_positions = {
            limb.chain_root: np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
            for limb in limbs
        }
        chain_root_centroid = np.mean(list(chain_root_positions.values()), axis=0)
        foot_centroid = np.mean(list(foot_positions.values()), axis=0)

        groups: dict[str, list[int]] = {"A": [], "B": []}
        offsets: dict[int, float] = {}
        for limb in limbs:
            proj_front = float(
                np.dot(chain_root_positions[limb.chain_root] - chain_root_centroid, stride_direction)
            )
            proj_side = float(
                np.dot(foot_positions[limb.chain_root] - foot_centroid, side_axis)
            )
            group = "A" if np.sign(proj_front) == np.sign(proj_side) else "B"
            groups[group].append(limb.chain_root)
            offsets[limb.chain_root] = 0.0 if group == "A" else 0.5

        assert len(groups["A"]) == 2 and len(groups["B"]) == 2, (
            f"assign_limb_phase_offsets: se esperaban 2 patas por grupo diagonal, "
            f"salió A={groups['A']} B={groups['B']} — revisar classify_support_limbs "
            "para este modelo, el reparto no tiene sentido"
        )
        return offsets

    raise NotImplementedError(
        f"assign_limb_phase_offsets solo cubre 2 o 4 patas (lo que aparece en "
        f"los 3 samples de este proyecto), hay {len(limbs)}"
    )


def surprise_pose_phase_offsets(limbs: list[LimbChain]) -> dict[int, float]:
    """`phase_offset = 0.0` para TODAS las patas — el reparto (deliberadamente
    trivial) que usa la pose de "asombro" en vez de
    `assign_limb_phase_offsets`.

    **Por qué "todas en fase" da una pose de sobresalto y no "otro
    instante cualquiera de caminar"**: en una marcha real (o en
    `assign_limb_phase_offsets`), el reparto alterna/diagonaliza
    precisamente para que NUNCA todas las patas estén en swing (en el
    aire, alejándose del suelo) al mismo tiempo — un cuerpo necesita
    siempre alguna pata de apoyo para no caerse. Poner TODAS las patas
    en la MISMA fase rompe esa restricción a propósito: en
    `global_phase=0.25` (el pico de elevación, ver `foot_target_at_phase`
    — `max(0, sin(2π·phase))` alcanza su único máximo exacto en
    `phase=0.25` para CUALQUIER pata, es una propiedad de la fórmula, no
    algo que dependa del modelo) todas las patas se extienden hacia
    arriba/adelante A LA VEZ, una postura físicamente imposible de
    sostener en equilibrio durante una marcha real — pero es exactamente
    la lectura visual de un sobresalto o un salto congelado en el aire
    (todas las extremidades reaccionando al mismo tiempo), no un instante
    de locomoción normal.

    **Por qué esto generaliza sin heurísticas nuevas**: a diferencia de
    `assign_limb_phase_offsets` (que necesita ramificar explícitamente
    entre 2 y 4 patas, con un `NotImplementedError` para cualquier otro
    número), "todas a 0.0" es trivialmente válido para CUALQUIER nº de
    patas — no hay pares que formar ni ejes de "lado" que calcular. No
    depende tampoco del signo sin resolver de `stride_direction` (ver
    `detect_stride_direction`): todas las patas se mueven hacia el MISMO
    lado relativo del eje detectado a la vez, así que da igual cuál
    extremo sea "adelante" de verdad para que la pose se lea como
    sobresalto.

    Devuelve `chain_root -> 0.0` para cada pata de `limbs` — misma forma
    de retorno que `assign_limb_phase_offsets`, intercambiable como
    argumento `phase_offsets` de `solve_gait_cycle_pose`.
    """
    return {limb.chain_root: 0.0 for limb in limbs}


def compute_safe_amplitudes(
    limbs: list[LimbChain],
    tree: nx.Graph,
    hierarchy: dict[int, "int | None"],
    stride_direction: np.ndarray,
) -> dict[int, float]:
    """`max_chain_bone_length` + `safe_stride_amplitude_pct` para cada
    pata, UNA VEZ (no por fase) — mismo criterio de separación de
    responsabilidades que ya explica el docstring de este módulo sobre
    por qué `safe_stride_amplitude_pct` es un paso explícito previo, no
    un recorte implícito dentro de `foot_target_at_phase`: aquí se hace
    explícito también que es un cálculo POR PATA, no por fase — llamarlo
    dentro de un bucle de fases repetiría trabajo idéntico en cada
    iteración sin ninguna ganancia (la amplitud segura de una pata no
    depende de la fase, solo de su propia geometría).

    Devuelve `chain_root -> stride_amplitude_pct` ya seguro, listo para
    pasar a `foot_target_at_phase` (o, como aquí, a `solve_gait_cycle_pose`)
    en cualquier fase del ciclo sin recalcular nada más.
    """
    amplitudes: dict[int, float] = {}
    for limb in limbs:
        bind_foot_position = np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
        chain_root_position = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
        max_length = max_chain_bone_length(limb, hierarchy, tree)
        amplitudes[limb.chain_root] = safe_stride_amplitude_pct(
            bind_foot_position, chain_root_position, max_length, stride_direction
        )
    return amplitudes


def solve_gait_cycle_pose(
    skin_data: SkinData,
    limbs: list[LimbChain],
    tree: nx.Graph,
    hierarchy: dict[int, "int | None"],
    global_phase: float,
    stride_direction: np.ndarray,
    phase_offsets: dict[int, float],
    amplitude_by_root: dict[int, float],
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
) -> tuple[dict[int, np.ndarray], dict[int, IKResult]]:
    """Pose de TODAS las patas de `limbs` a la vez, en `global_phase`.

    Cada pata tiene su propia fase LOCAL (`global_phase +
    phase_offsets[chain_root]`), resuelta de forma INDEPENDIENTE con
    `solve_ik_ccd` — válido porque las patas son cadenas de huesos
    disjuntas (cada `chain_root` distinto no comparte ningún hueso con
    otra pata, garantizado implícitamente por `classify_support_limbs`:
    cada `LimbChain` es una rama separada del árbol de esqueleto), así
    que no hace falta ningún solver conjunto — resolver cada pata por su
    cuenta y combinar los resultados al final da exactamente el mismo
    resultado que resolverlas "a la vez" en cualquier sentido físico
    relevante aquí (no hay una restricción compartida entre patas, cada
    una solo mueve sus propios huesos).

    Combina los `local_rotations` de cada `ik_solver.IKResult` en un
    ÚNICO dict para todo el esqueleto: cada `IKResult.local_rotations`
    ya trae la rotación de BIND POSE para los huesos fuera de su propia
    cadena (ver docstring de `IKResult`), así que para cada pata basta
    con sobrescribir en el dict combinado solo las entradas de los
    huesos que pertenecen a ESA cadena (`chain_bone_names` +
    `name_to_node_index`), dejando el resto tal como esté. El dict
    combinado empieza en bind pose (una copia de
    `skin_data.node_trs[...].rotation` para cada nodo) antes de aplicar
    las patas una a una — así, si `limbs` no cubre TODOS los huesos del
    esqueleto (nunca lo hace: columna, cabeza, cola, etc. no pertenecen
    a ninguna pata), esos huesos quedan correctamente en bind pose en el
    resultado final.

    Devuelve `(combined_local_rotations, ik_results_by_chain_root)` — el
    segundo elemento es para que quien llame (o los tests) pueda
    comprobar convergencia e iteraciones por pata sin tener que
    re-derivar nada volviendo a llamar a `solve_ik_ccd`.
    """
    combined_local_rotations: dict[int, np.ndarray] = {
        node_index: trs.rotation.copy() for node_index, trs in skin_data.node_trs.items()
    }
    ik_results_by_chain_root: dict[int, IKResult] = {}
    name_to_index = name_to_node_index(skin_data)

    for limb in limbs:
        bind_foot_position = np.array(tree.nodes[limb.foot_leaf]["pos"], dtype=np.float64)
        chain_root_position = np.array(tree.nodes[limb.chain_root]["pos"], dtype=np.float64)
        local_phase = global_phase + phase_offsets[limb.chain_root]
        target = foot_target_at_phase(
            bind_foot_position,
            chain_root_position,
            stride_direction,
            local_phase,
            stride_amplitude_pct=amplitude_by_root[limb.chain_root],
        )

        result = solve_ik_ccd(
            skin_data,
            limb,
            hierarchy,
            bind_foot_position,
            target,
            max_iterations=max_iterations,
        )
        ik_results_by_chain_root[limb.chain_root] = result

        for bone_name in chain_bone_names(limb, hierarchy):
            node_index = name_to_index[bone_name]
            combined_local_rotations[node_index] = result.local_rotations[node_index]

    return combined_local_rotations, ik_results_by_chain_root
