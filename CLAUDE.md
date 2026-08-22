# CLAUDE.md — Auto-Rig & Animación Procedural para Criaturas 3D

Este archivo es la memoria central del proyecto. Léelo por completo al empezar
cada sesión. Después de completar y verificar cada módulo, actualiza la
sección "Estado actual" y el "Historial de checkpoints" antes de pasar al
siguiente módulo. No avances de módulo sin que su comando de verificación
haya pasado.

## Visión del proyecto

App capaz de tomar cualquier criatura 3D en formato GLB y:
1. Detectar automáticamente su esqueleto (máximo número de articulaciones
   identificables con coherencia, incluyendo micro-huesos: párpados, dedos,
   cola, orejas).
2. Generar el skinning (pesos de piel) de forma robusta.
3. Aplicar animación procedural básica (caminar, correr, poses como "asombro"),
   generada matemáticamente, no por clips pregrabados.
4. Añadir micro-movimientos (respiración, parpadeo, dedos, cola/orejas).
5. Generar micro-expresiones faciales.

Salida siempre en GLB estándar, para máxima compatibilidad (motores de juego,
vídeo, visores web, AR/VR).

## Arquitectura (stack) — no cambiar sin actualizar esta sección

- Backend: Python 3.11+, FastAPI.
- Motor de cómputo geométrico: Blender en modo headless (`bpy`), invocado como
  subproceso `blender --background --python script.py`. Blender nunca es
  visible al usuario final, es solo motor de cálculo.
- Formato de intercambio: GLB/glTF 2.0 en todo el pipeline.
- Frontend/visor de pruebas: Three.js (Vite), carga GLB por input de archivo,
  OrbitControls, AnimationMixer para previsualizar animaciones.
- Testing: `pytest` para el backend. Cada módulo debe incluir al menos un test
  automatizado que verifique su criterio de éxito, no solo inspección visual.

## Enfoque de auto-rigging

Heurística geométrica primero (esqueletización por contracción de malla +
clasificación topológica del grafo resultante), no ML. Motivo: determinista,
depurable, no requiere dataset etiquetado. ML queda como posible mejora en
fase de pulido, una vez tengamos casos reales fallidos con los que evaluar.

## Estado actual

- **Módulo actual:** 4 — Micro-movimientos (en curso)
- **Estado:** Módulos 0, 1, 2 y 3 completados y verificados. Módulo 3
  (animación procedural básica) **CERRADO** 2026-08-21: clasificación de
  patas de apoyo (`limb_classification.classify_support_limbs`) + IK CCD
  de una sola pata (`ik_solver.solve_ik_ccd`) + trayectoria de ciclo por
  pata (`gait_cycle.foot_target_at_phase` + amplitud segura) + dirección
  de zancada automática (`detect_stride_direction`) + reparto de fase
  entre patas (`assign_limb_phase_offsets`) + pose de marcha con varias
  patas a la vez (`solve_gait_cycle_pose`) + límites articulares por
  bisagra, eje y ángulo combinados (`joint_limits.compute_hinge_axes` +
  `hinge_axes_in_local_frame`, aplicados dentro de `solve_ik_ccd` vía
  `hinge_axes_local`/`hinge_max_angle_deg`) + pose de "asombro"
  (`surprise_pose_phase_offsets`, todas las patas en fase). El signo de
  `stride_direction` queda sin resolver como límite ACEPTADO Y
  PERMANENTE de este enfoque geométrico (investigado y documentado, no
  pendiente — ver checkpoint 2026-08-21 "signo de stride_direction,
  decisión de no perseguirlo"), no bloquea el cierre del módulo porque
  ninguna pieza construida depende de resolverlo. Módulo 4
  (micro-movimientos) en curso: respiración
  (`micro_movements.breathing_local_rotation`, rotación sinusoidal de la
  raíz del esqueleto) hecha y verificada. **Pendiente dentro de Módulo
  4**: integración de la respiración con el ciclo de marcha activo (sin
  resolver — combinar ambas podría deslizar ligeramente los pies durante
  la fase de apoyo, limitación conocida y aceptada de esta primera pieza,
  no bloquea seguir con el resto de micro-movimientos). Parpadeo:
  **bloqueo documentado y aceptado** (no pendiente activo — ver
  checkpoint 2026-08-21 "bloqueo de parpadeo": los 3 GLB de muestra
  tienen 0 morph targets y ningún esqueleto tiene hueso de párpado,
  límite duro de los datos de entrada, no un algoritmo por mejorar).
  Único pendiente activo de Módulo 4: ruido de baja frecuencia en
  dedos/cola/orejas — sin empezar todavía.

## Roadmap por módulos

Cada módulo se da por completo únicamente cuando su comando de verificación
pasa sin errores. No se avanza al siguiente módulo antes de eso.

### Módulo 0 — Cimientos
- Objetivo: estructura de repo, backend arrancando, frontend cargando un GLB,
  script de inspección funcionando sobre Blender headless.
- Entregables: `backend/app/main.py` (health-check), `backend/scripts/inspect_glb.py`,
  `frontend/` (Vite + Three.js mínimo), `samples/` con README pidiendo modelos
  de prueba, `requirements.txt`.
- Verificación: `python backend/scripts/inspect_glb.py samples/<modelo>.glb`
  se ejecuta sin errores e imprime nº de vértices, huesos existentes,
  bounding box y nº de materiales. Además: `pytest backend/tests/test_setup.py`
  (test mínimo que confirma que Blender headless responde).

### Módulo 1 — Detección de esqueleto
- Objetivo: esqueletización de malla (contracción tipo Laplaciano) +
  clasificación topológica (raíz/columna, extremidades, hojas: dedos, cola,
  orejas) + generación del `Armature` en Blender con jerarquía correcta.
- Verificación: `pytest backend/tests/test_skeleton.py` sobre los 3 GLB de
  muestra (cuadrúpedo, bípedo, atípico) — comprueba nº de huesos razonable,
  jerarquía padre-hijo sin ciclos, y que la raíz esté cerca del centroide de
  masa. Validación visual adicional en el visor.

### Módulo 2 — Skinning
- Objetivo: auto-weighting por difusión de calor + post-proceso (máx. 4
  influencias/vértice, normalizado, suavizado).
- Verificación: `pytest backend/tests/test_skinning.py` — ningún vértice sin
  peso asignado, ninguna influencia negativa o > 1 tras normalizar, máx. 4
  huesos por vértice. Test de deformación: mover un hueso no debe dejar
  vértices "huérfanos" (distancia post-deformación dentro de un umbral).

### Módulo 3 — Animación procedural básica
- Objetivo: ciclos de marcha/carrera paramétricos (senoidales con desfase de
  fase por extremidad), IK simple (CCD/FABRIK) para contacto con el suelo,
  pose de "asombro" como ejemplo de pose dirigida.
- Verificación: **no existe `backend/tests/test_locomotion.py`** — el módulo
  terminó organizado en 4 archivos de test más pequeños y temáticos en vez
  de uno solo por módulo (decisión tomada sobre la marcha, nunca revertida
  porque no había ganancia real en mover tests ya verificados; ver
  checkpoint de cierre del Módulo 3 en el historial): `test_limb_classification.py`
  (clasificación de patas de apoyo), `test_ik_solver.py` (IK CCD, incluida
  la restricción de eje+ángulo de bisagra), `test_joint_limits.py` (ejes de
  bisagra por articulación), `test_gait_cycle.py` (trayectoria de ciclo,
  dirección de zancada, reparto de fase, pose de marcha multi-pata y pose
  de "asombro"). El criterio de éxito sigue siendo el mismo: `pytest
  backend/tests/` completo sobre los 3 modelos — el ciclo de marcha es
  periódico (`verify_phase_periodicity`) y los pies/patas no atraviesan el
  plano del suelo (`verify_never_below_ground`, cubre el objetivo pedido a
  `foot_target_at_phase`; la posición REAL resuelta por IK se confirma
  aparte, dentro de tolerancia 1e-4, en los tests de convergencia de
  `test_ik_solver.py`/`test_gait_cycle.py`).

### Módulo 4 — Micro-movimientos
- Objetivo: respiración, parpadeo, ruido de baja frecuencia en dedos/cola/orejas.
- Verificación: `pytest backend/tests/test_micromovements.py` — amplitud de
  los micro-movimientos dentro de rango (perceptible pero no rompe el ciclo
  principal), parpadeo con intervalo dentro de rango fisiológico razonable.

### Módulo 5 — Micro-expresiones faciales
- Objetivo: morph targets en zonas faciales detectadas (ojos, boca) o fallback
  por huesos (mandíbula, ojos, cejas).
- Verificación: al menos 3 expresiones (sorpresa, enfado, calma) generadas y
  exportadas correctamente como morph targets válidos en el GLB de salida
  (`pytest backend/tests/test_expressions.py`, valida estructura del glTF).

### Módulo 6 — Pulido (post-aprobación del usuario)
- Libre, sin gate de verificación fijo predefinido.

## Convenciones de código

- Python: type hints obligatorios en funciones públicas, `ruff` para lint.
- Un test por módulo como mínimo, en `backend/tests/`, antes de marcar el
  módulo como completo.
- Commits atómicos, un commit por sub-tarea, mensaje descriptivo.

## Historial de checkpoints

(Se añade una entrada aquí cada vez que un módulo se completa y verifica.
Formato: `[Módulo N] fecha — resumen de qué se hizo y qué decisiones se tomaron.`)

- **[Módulo 0] 2026-08-18** — Estructura de repo creada: `backend/app/main.py`
  (FastAPI con `GET /health`), `backend/scripts/inspect_glb.py` (carga un GLB
  vía `bpy` en modo `--background`, imprime vértices, huesos, bounding box y
  nº de materiales; funciona tanto invocado directamente dentro de Blender
  como vía wrapper `python inspect_glb.py <glb>` que reinvoca Blender como
  subproceso), `frontend/` (Vite + Three.js mínimo: input de archivo GLB,
  `OrbitControls`, sin lógica adicional), `samples/README.md`,
  `requirements.txt`, `backend/tests/test_setup.py`.
  Decisión: Blender no estaba instalado en el sistema; se instaló Blender
  4.5 LTS vía `winget` (`BlenderFoundation.Blender.LTS.4.5`) y se añadió su
  directorio al `PATH` de usuario, ya que la arquitectura del proyecto
  depende de invocar `blender --background` como subproceso (no se usó el
  paquete `bpy` de PyPI para mantener la versión de Blender bajo control
  explícito vía winget). Se generó `samples/test_cube.glb` (cubo + armature
  de 1 hueso, creado con Blender, sin dependencias de licencia externa) para
  validar `inspect_glb.py` end-to-end.
  Verificación: `pytest backend/tests/test_setup.py` → 2 passed (health
  endpoint + Blender headless responde). `python backend/scripts/inspect_glb.py
  samples/test_cube.glb` → ejecuta sin errores, imprime 24 vértices, 1 hueso
  ("Bone"), bounding box y 1 material.
  Corrección post-verificación: el conteo inicial daba 66 vértices en lugar
  de 24. Causa raíz: el importador glTF de Blender crea, por cada hueso, un
  objeto MESH auxiliar (p.ej. "Icosphere", 42 vértices) usado solo como
  widget visual de pose (`pose_bone.custom_shape`); no es geometría del
  modelo. `inspect_glb.py` ahora excluye explícitamente los objetos
  referenciados como `custom_shape` de huesos antes de contar vértices y
  calcular el bounding box. Relevante para el Módulo 1: cualquier código que
  itere `bpy.data.objects` tras un `import_scene.gltf` con armature debe
  aplicar el mismo filtro.

- **[Módulo 1] 2026-08-19** — Pipeline de esqueletización completo sobre
  los 3 samples (cow/biped/bat_unrigged.glb), implementado en
  `backend/app/skeletonization.py` y verificado con
  `backend/tests/test_skeleton.py` (15 tests, todos en verde).

  **Pipeline final (1.1 → 1.3):**
  1. `extract_skeleton_graph` — carga la malla con trimesh (`merge_vertices`
     imprescindible: los exportadores glTF duplican vértices por cara y
     dejan la malla partida en cientos de fragmentos de 1 cara) y la
     esqueletiza con `skeletor.skeletonize.by_wavefront` (step_size=2;
     step_size=1 se probó como arreglo global y se descartó — no resolvía
     el problema de fondo en cow y metía ruido en biped/bat).
  2. `densify_long_edges` — para aristas del grafo en bruto que superen el
     10% de la diagonal del modelo, recalcula `by_wavefront` a step_size=1
     y sustituye la arista por el camino real entre sus extremos.
  3. `merge_components` — fusiona las componentes conexas del esqueleto en
     bruto (frecuentes: partes de malla no soldadas) en un único árbol vía
     MST entre componentes (peso = distancia mínima punto-a-punto).
  4. `select_root` — centroide de grafo (minimiza el mayor sub-árbol tras
     quitar el nodo), no centroide espacial (ese caía en manos/alas en vez
     de en el torso).
  5. `collapse_short_edges` — colapsa aristas por debajo del 0.5% de la
     diagonal, cualquier grado (no solo grado 2): imprescindible tras
     detectar geometría solapada real en la malla del bípedo (mano/guante
     con dos capas casi coincidentes, confirmado con análisis de hulls
     convexos y vértices compartidos).
  6. `simplify_chains_rdp` — Ramer-Douglas-Peucker por TRAMO completo
     (bifurcación a bifurcación/hoja/raíz), no ángulo nodo a nodo: el
     criterio de ángulo local no detectaba zigzag repartido en varios
     nodos con ángulo individual muy por debajo del umbral.
  7. `build_hierarchy` — jerarquía padre-hijo por BFS desde la raíz.

  **Lecciones clave para Módulo 2 en adelante:**
  - Filtro de widgets de hueso (`pose_bone.custom_shape`) del Módulo 0
    sigue aplicando a cualquier iteración de `bpy.data.objects`.
  - `merge_components` y `densify_long_edges` dependen de una fuente de
    verdad fiable para "qué nodo corresponde a qué región de la malla":
    la posición por sí sola puede confundir dos regiones cercanas pero
    distintas (comprobado en `densify_long_edges` — un nodo cercano en
    posición pero de un grupo de vértices distinto daba un camino
    incorrecto). `Skeleton.mesh_map` (pertenencia real vértice→nodo) es la
    fuente de verdad correcta, no la proximidad espacial.
  - `by_wavefront` con `step_size>1` agrupa el detalle geodésico fino
    ANTES de calcular los centros de anillo — ese detalle no queda
    accesible en el resultado ya agrupado (ni `mesh_map` ni ningún otro
    atributo de una sola llamada); hay que recalcular a menor step_size
    si se necesita.
  - Generación de `Armature` real + conversión de ejes glTF→Blender
    (`Blender_X=gltf_X, Blender_Y=-gltf_Z, Blender_Z=gltf_Y`) validada
    visualmente en `backend/scripts/_render_armature_debug.py` +
    `samples/_debug/*.png` sobre los 3 modelos — sub-paso 1.4, es
    depuración/inspección visual, no el generador de Armature de
    producción (eso corresponde a un módulo posterior).

  Verificación: `pytest backend/tests/test_skeleton.py` → 15 passed.

- **[Módulo 1 — cierre] 2026-08-19** — `build_skeleton_tree(mesh_path, ...)`
  añadida en `backend/app/skeletonization.py`: encapsula el pipeline
  completo (`extract_skeleton_graph` → `densify_long_edges` →
  `merge_components` → `select_root`, seguido de un bucle de punto fijo
  que alterna `collapse_short_edges`/`simplify_chains_rdp` hasta que una
  ronda completa no cambie ni nodos ni aristas, y termina con
  `build_hierarchy`). Sustituye la lógica duplicada que antes vivía por
  separado en `backend/tests/test_skeleton.py`,
  `backend/scripts/inspect_skeleton.py` y
  `backend/scripts/_export_skeleton_json.py`.

  **Causa raíz de la arista residual de `biped_unrigged`** (la limitación
  conocida del checkpoint anterior, ahora resuelta): `collapse_short_edges`
  y `simplify_chains_rdp` se ejecutaban una sola vez cada uno, en ese
  orden. Pero `simplify_chains_rdp` puede acercar directamente dos
  anclajes (bifurcaciones/hojas) que antes no eran vecinos, al quitar los
  nodos intermedios de grado 2 entre ellos — y esa arista nueva puede
  quedar por debajo del umbral de longitud mínima sin que nadie vuelva a
  comprobarlo, porque `collapse_short_edges` ya había terminado su única
  pasada. El fix es alternar ambos pasos en un bucle `while changed` (con
  `max_iters=20` como cinturón de seguridad, nunca alcanzado en la
  práctica) hasta alcanzar un punto fijo real. Verificado por logging:
  cow y bat convergen en 2 rondas, biped en 3 — muy por debajo del límite
  de 5 usado en el test de convergencia.

  `biped_unrigged` pasa de 183 a **182** nodos finales tras el fix (una
  fusión más, la que antes se quedaba pendiente), y de **1 arista residual
  a 0** — ya no hace falta ninguna excepción documentada en el test.

  Módulo 1 cerrado formalmente sin pendientes conocidos: los 3 modelos dan
  árbol único, conexo, acíclico, raíz de grado ≥3, sin aristas por debajo
  del umbral, y el bucle de punto fijo converge en pocas rondas en los 3.

  Verificación: `pytest` completo → 20 passed, 0 failed.

- **[Módulo 2 — sub-paso, en curso] 2026-08-19** — Armature real +
  parentado con auto-weight nativo de Blender (`ARMATURE_AUTO`, difusión
  de calor) sobre los 3 samples. **Módulo 2 NO cerrado**: falta el
  post-proceso de pesos (máx. 4 influencias/vértice, normalizado,
  suavizado) y su test de deformación — pendiente para la siguiente
  sesión, una vez revisados estos pesos en bruto.

  `backend/scripts/build_armature.py` (producción, sin prefijo `_`):
  mismo patrón dual-modo que `inspect_glb.py` — calcula el esqueleto con
  `build_skeleton_tree` en Python de sistema, lo serializa a JSON temporal
  (posiciones ya en ejes Blender vía la nueva `gltf_to_blender`, movida de
  `_export_skeleton_json.py` a `skeletonization.py` por estar ahora
  usada en 2 sitios) y reinvoca Blender como subproceso para construir el
  Armature (`create_armature`), parentear con auto-weight y exportar.

  Nota de corrección (2026-08-19, mismo día): este checkpoint afirmaba que
  `create_armature` había sido "factorizada de `_render_armature_debug.py`
  para no duplicarla" — eso NO ocurrió en este commit: `create_armature`
  se escribió de nuevo en `build_armature.py`, pero `_render_armature_debug.py`
  se quedó con su propia construcción de edit bones inline, duplicada. Ver
  el checkpoint siguiente para el fix real.

- **[Módulo 2 — inspección visual de pesos] 2026-08-20** —
  `backend/scripts/_render_weights_debug.py` (debug, prefijo `_`): lee un
  GLB ya rigged de `samples/_debug/{cow,biped,bat}_rigged.glb` (sin
  recalcular nada, mismo patrón que `_render_rigged_debug.py`) y genera:
  (a) segmentación por hueso dominante — cada vértice coloreado según el
  vertex group de mayor peso, paleta categórica fija de 20 colores
  (aprox. 'tab20'), asignada por orden alfabético de nombre de hueso para
  ser determinista sin añadir matplotlib como dependencia; y (b) mapa de
  calor (azul=0, rojo=1) de 1-2 huesos elegidos a mano por modelo,
  inspeccionando la jerarquía del esqueleto exportada con
  `_export_skeleton_json.py` (posiciones ya en ejes Blender): cow →
  `bone_3_29` (codo/rodilla de la pata delantera), biped → `bone_57_107`
  (codo) y `bone_5_71` (rodilla), bat → `bone_33_34` (articulación media
  del ala). Cada heatmap incluye un marcador cian en el punto medio del
  hueso resaltado. Vista frontal + lateral, mismo encuadre que los scripts
  anteriores.

  Generados en `samples/_debug/`: 3× `{modelo}_weights_segmentation_
  {front,side}.png` y 4× `{modelo}_weights_heatmap_{etiqueta}_
  {front,side}.png` (14 renders en total).

  **Lectura de los resultados (solo inspección visual, sin decisión de
  post-proceso todavía):** la segmentación muestra regiones por hueso
  razonablemente compactas y sin salpicado disperso en los 3 modelos — no
  hay indicios de vértices con influencia dominante de un hueso lejano
  (síntoma típico de auto-weight sin post-procesar). Los heatmaps de codo/
  rodilla/articulación de ala muestran una transición roja→azul suave
  centrada en la articulación marcada, sin franjas duras ni vértices
  aislados en rojo puro rodeados de azul puro (lo que indicaría ruido de
  alta frecuencia necesitando suavizado). Conclusión preliminar: los pesos
  en bruto parecen razonables a nivel visual; queda pendiente el test de
  deformación cuantitativo (mover un hueso y medir distancia post-
  deformación) para confirmar si el post-proceso de pesos sigue siendo
  necesario o es opcional en estos 3 samples — decisión para la siguiente
  sesión.

  Nota técnica: `blender --background` con una ruta de salida relativa
  (`samples/_debug`) resolvió el path de forma inconsistente en esta
  sesión (escribió una vez en `C:\samples\_debug` en vez del repo) — se
  usó una ruta absoluta al invocar el script para evitarlo. Aplica a
  cualquier invocación futura de scripts de Blender headless con rutas de
  salida relativas.

- **[Módulo 2 — corrección de huesos elegidos para heatmaps] 2026-08-20**
  — Verificación estructural independiente (grado de cada nodo del árbol
  de esqueleto + detección de ramas espurias de 1 salto a hoja aislada,
  usando solo `build_skeleton_tree`, sin Blender) mostró que 3 de los 4
  huesos elegidos en el checkpoint anterior para (b) no eran el punto
  medio de una articulación real:

  - biped `bone_57_107` ("codo"): el nodo 107 es él mismo una bifurcación
    espuria (rama de 1 salto a la hoja aislada 147) — firma de dedo/bulto
    de malla, no de articulación.
  - biped `bone_5_71` ("rodilla"): el nodo 71 es grado 4, con DOS ramas
    espurias de 1 salto (130, 132) — firma de dedo del pie.
  - bat `bone_33_34`: la cadena completa del ala (excluyendo el tramo
    torso->hombro 13->18, que es sobre todo attachment, no ala) es
    18->33->34->24->27; el nodo 33 está solo al 13% de la distancia
    acumulada 18->27, muy lejos del punto medio real.

  Criterio revisado y aplicado para la reselección: el nodo debe ser
  **grado 2** (paso simple, sin bifurcación propia) y estar lo más cerca
  posible del **50% de la distancia geométrica acumulada** (no del nº de
  saltos, que es engañoso cuando la densidad de nodos no es uniforme a lo
  largo de la cadena — comprobado explícitamente en biped, donde la zona
  cercana a la mano está mucho más densificada que la zona cercana al
  hombro) entre dos bifurcaciones reales (nodos de grado ≥3 que no
  terminan en una hoja aislada a 1-2 saltos).

  Nuevos huesos: biped codo → `bone_107_206` (nodo 206, grado 2, al 74%
  de hombro(180)->mano(151); único candidato limpio más cercano al medio,
  ya que 106 —el otro nodo grado 2— está solo al 17%). Biped rodilla →
  `bone_71_118` (nodo 118, grado 2, al 47.5% de cadera(72)->tobillo(30) —
  el más cercano al punto medio real de toda la cadena). Bat ala →
  `bone_34_24` (nodo 24, al 45% de la parte real del ala 18->27, tras
  excluir el tramo torso->hombro). Se comprobó también si el murciélago
  tenía una segunda cadena de ala más representativa (bajo el nodo 16,
  grado 5) — sus subcadenas más largas tienen 2-3 saltos hasta hoja,
  consistentes con orejas/nariz, no con un ala; se confirmó que
  18->33->34->24->27 es la única cadena de extremidad larga en el modelo.
  `cow bone_3_29` se verificó y se confirmó correcto sin cambios (único
  nodo interior de grado 2 de esa pata, al 66.5% de la cadena).

  Heatmaps regenerados para los 3 modelos (`samples/_debug/{modelo}_
  weights_heatmap_*`); la segmentación por hueso dominante no depende de
  esta corrección y se dejó sin recalcular en contenido (se regeneró junto
  al resto por conveniencia del comando, pero es bit-a-bit equivalente).

  **Verificación adicional de la paleta categórica en biped** (182
  huesos, 20 colores): con asignación de color por orden alfabético del
  nombre de hueso, hay colisión de color entre huesos ADYACENTES
  (padre-hijo en la jerarquía) en 7 de 177 pares comprobados (~4%) —
  ejemplo: `bone_4_115` y `bone_115_157` comparten índice de color 10 por
  pura coincidencia alfabética. Esto significa que, en esos 7 puntos
  concretos de la malla de biped, un borde de "fuga" de peso real entre
  dos huesos vecinos podría no ser visible en el render de segmentación
  (ambos lados del borde tendrían el mismo color aunque los vertex groups
  sean distintos) — la lectura de "regiones compactas sin salpicado" del
  checkpoint anterior es válida en general pero no es una garantía
  completa para esos puntos concretos. No se ha corregido (fuera de
  alcance de esta tarea; requeriría asignar color por adyacencia en el
  árbol en vez de por orden alfabético, o una paleta más grande). Pendiente
  para si se decide confiar más en la segmentación por hueso dominante en
  el futuro.

  **Bug real encontrado y corregido durante el desarrollo:** con la malla
  tal como la importa Blender (vértices duplicados por cara, igual
  problema que motivó `merge_vertices` en `skeletonization.py` para el
  cálculo del esqueleto), `bpy.ops.object.parent_set(type='ARMATURE_AUTO')`
  creaba los vertex groups pero la difusión de calor no asignaba peso a
  NINGÚN vértice (0/1616 en cow) — sin conectividad real de superficie
  (islas de 1 cara), el calor no tiene por dónde propagarse. El exportador
  glTF entonces ni siquiera escribía datos de skin ("Cow has no skin").
  Fix: `bpy.ops.mesh.remove_doubles()` en cada malla antes de parentear
  (mismo criterio que `merge_vertices`, ahora en el lado de Blender).
  Verificado tras el fix: 100% de vértices con peso asignado en los 3
  modelos, Armature real (no Empties) y parentado correcto al reimportar
  el GLB exportado.

  Generados `samples/_debug/{cow,biped,bat}_rigged.glb` y sus renders de
  depuración `samples/_debug/{cow,biped,bat}_rigged_{front,side}.png` (vía
  `backend/scripts/_render_rigged_debug.py`, que lee el Armature ya
  presente en el GLB rigged en vez de recalcular nada).

  Sin tests automatizados todavía (se decidió deliberadamente: dependen de
  cómo se procesen los pesos en bruto, tarea siguiente).

- **[Módulo 2 — fix de duplicación] 2026-08-19** — `_render_armature_debug.py`
  seguía con su propia construcción de edit bones inline (duplicada de
  `create_armature` en `build_armature.py`), pese a lo que afirmaba el
  checkpoint anterior. Corregido: ahora importa `create_armature` desde
  `backend.scripts.build_armature` (mismo patrón de `sys.path.insert` que
  ya usan el resto de scripts para importar desde `backend/`) y su bloque
  inline (`bpy.data.armatures.new`, `edit_bones.new`, `parent`/`use_connect`)
  se eliminó. Comportamiento verificado sin cambios: mismo comando de uso,
  render manual sobre los 3 modelos (vía Blender headless) con resultado
  visual idéntico al ya generado (tamaños de PNG iguales o casi iguales;
  biped_unrigged difiere en <100 bytes por variación normal de encoding
  PNG entre ejecuciones, no en contenido — comparado visualmente).

- **[Módulo 2 — cierre formal] 2026-08-20** — Métrica cuantitativa de
  suavidad de pesos + test de deformación, en Python puro (numpy +
  pygltflib) directamente sobre los GLB ya exportados en
  `samples/_debug/{cow,biped,bat}_rigged.glb`, sin Blender.

  **`backend/app/skinning_quality.py`** (nuevo, reutilizable):
  - `read_skin_data(glb_path)`: decodifica accessors de glTF a mano
    (componentType/type genérico, con y sin `byteStride`; matrices MAT4
    interpretadas column-major — glTF las serializa así, hay que
    transponer tras el reshape) — sin depender de ningún helper de
    decodificación de pygltflib 1.16 (no trae ninguno). Soporta varios
    nodos-malla compartiendo un mismo `skin` (caso real de biped: 3 nodos
    Eyebrows/Eyes/SuperHero_Male con `skin=0`; bat: 2 nodos) y calcula la
    matriz global de bind pose de cada nodo-joint recorriendo la
    jerarquía completa desde la raíz de la escena.
  - `weight_smoothness_metric(skin_data)`: distancia L1 entre vectores de
    peso completos (dispersos sobre TODOS los joints del skin, no solo
    los 4 slots de `WEIGHTS_0`) de cada arista de la triangulación.
    Devuelve la distribución completa, no un resumen.
  - `apply_bone_rotation(skin_data, joint_name, quat)`: linear blend
    skinning completo — rota el hueso objetivo componiendo la rotación
    extra CON su rotación de bind pose existente (no la sustituye), y
    recalcula la matriz global de TODOS los joints recorriendo la
    jerarquía de nuevo, así que los huesos descendientes heredan la
    rotación del padre correctamente. Incluye la fórmula completa
    `invMeshGlobal · jointGlobal · inverseBindMatrix` (no solo
    `jointGlobal · inverseBindMatrix`) para ser correcto también si el
    nodo-malla tuviera una transformación propia no identidad (no es el
    caso en estos 3 samples, pero no había que asumirlo).
  - `verify_identity_rotation_reproduces_bind_pose(skin_data)`: el
    auto-chequeo pedido, expuesto como función reutilizable (no solo un
    script de un solo uso) — rotación de cuaternión identidad sobre
    cualquier hueso debe reproducir el bind pose exacto, porque
    `jointGlobal_bind · inverseBindMatrix` es la identidad por
    definición para cada joint. Error máximo real medido sobre los 3
    modelos: cow 1.83e-6, biped 1.02e-6, bat 6.32e-7 — muy por debajo de
    la tolerancia pedida de 1e-5. Es exactamente el tipo de bug que este
    chequeo está pensado para atrapar de forma silenciosa: glTF serializa
    MAT4 column-major, así que decodificar `inverseBindMatrices` con un
    `reshape` sin transponer produce matrices geométricamente incorrectas
    sin ningún error de Python — el auto-chequeo lo habría hecho evidente
    de inmediato (identidad NO reproduciría el bind pose) en vez de dejar
    pasar deformaciones sutilmente mal calculadas en `apply_bone_rotation`.

  **`backend/tests/test_skinning.py`** (6 tests, todos en verde):

  1. `test_identity_rotation_reproduces_bind_pose` — el auto-chequeo
     anterior, como test.
  2. `test_bind_pose_weights_sum_to_one` — regresión: suma de
     `WEIGHTS_0` por vértice ≈ 1.0 en los 3 modelos (ya se sabía por
     inspección manual del checkpoint del 2026-08-19; ahora automatizado).
  3. `test_weight_smoothness_baseline` — línea base de suavizado medida
     hoy sobre los 3 modelos (arista = par de vértices adyacentes en la
     triangulación; distancia L1 entre sus vectores de peso completos,
     rango [0,2]):

     | modelo | aristas | mean | median | p95 | p99 | max |
     |---|---|---|---|---|---|---|
     | cow | 1629 | 0.4076 | 0.1807 | 1.6116 | 1.9802 | 2.0000 |
     | biped | 22725 | 0.3753 | 0.2688 | 1.1566 | 1.6271 | 2.0000 |
     | bat | 2403 | 0.4984 | 0.2867 | 1.6533 | 1.9235 | 2.0000 |

     Los 3 modelos llegan a max=2.0 (vectores de peso completamente
     disjuntos en al menos una arista) — esto NO es indicio de mal
     suavizado: son bordes legítimos entre huesos rígidos lejanos en la
     malla (p.ej. entre dos falanges consecutivas sin necesidad de
     mezcla, lejos de cualquier articulación flexible), coherente con la
     inspección visual de heatmaps del checkpoint anterior, que mostraba
     transiciones suaves específicamente EN las articulaciones
     inspeccionadas (que es lo que importa para deformación), no una
     ausencia total de bordes duros en toda la malla.

     Umbral de regresión fijado: `p99_hoy + 0.05` por modelo (margen
     absoluto de 0.05 sobre un rango de métrica de 2.0, es decir ~2.5%
     del rango total). Justificación: el auto-weight de Blender es
     determinista para una malla+esqueleto fijos, así que el p99 debería
     ser reproducible casi bit a bit entre ejecuciones; un margen de 0.05
     absorbe ruido de punto flotante entre versiones de Blender sin dejar
     pasar una regresión real de suavizado. Limitación conocida y
     documentada en el propio test: como cow (1.9802) y bat (1.9235) ya
     tienen p99 muy cerca del máximo teórico (2.0), este chequeo concreto
     tiene poco margen de maniobra para detectar una regresión ADICIONAL
     en esos dos modelos específicamente — la red de seguridad es más
     sensible en biped (1.6271, con más margen hasta el máximo).

  4. `test_bone_rotation_deformation_sanity` (parametrizado por modelo) —
     para cada modelo, una muestra de 3-5 huesos (criterio reutilizado
     del checkpoint de reselección de heatmaps: grado 2 real a ~50% de
     distancia geométrica acumulada entre bifurcaciones reales; más un
     hueso justo tras la raíz; más un hueso hoja; más, si existe, un
     hueso justo antes de una bifurcación real hacia varias hojas en 1
     salto — firma de dedos/dedos del pie):

     - cow: `bone_2_3` (tras raíz), `bone_3_29` (mid-chain, el mismo del
       heatmap de codo/rodilla), `bone_29_15` (hoja/pie). Sin ejemplo de
       "pre-bifurcación de dedos": el esqueleto simplificado de cow no
       tiene ninguna bifurcación real hacia varias hojas en 1 salto (los
       únicos nodos de grado≥3 son 2,3,4,12, ninguno con ese patrón —
       confirmado en el checkpoint de reselección de huesos), así que esa
       categoría no aplica y se deja fuera deliberadamente.
     - biped: `bone_48_4` (tras raíz), `bone_107_206` (mid-chain codo),
       `bone_71_118` (mid-chain rodilla), `bone_116_30` (justo antes del
       nodo 30, grado 5, bifurcación real hacia los dedos del pie),
       `bone_30_3` (hoja/dedo del pie).
     - bat: `bone_13_18` (tras raíz), `bone_34_24` (mid-chain, el mismo
       del heatmap del ala), `bone_16_2` (justo antes del nodo 2, grado
       3, bifurcación real hacia 2 hojas en 1 salto), `bone_24_27`
       (hoja/punta del ala).

     Para cada hueso: rotación de flexión de 35° (dentro del rango 30-45°
     pedido) sobre el eje X local. Elección del eje: cada hueso de este
     armature tiene a su hijo desplazado a lo largo del eje Y local
     (`translation` del nodo-hijo ≈ `(0, longitud, 0)`, comprobado
     directamente en el GLB) — rotar sobre X flexiona el hueso en un
     plano perpendicular a su propio eje longitudinal (como una bisagra
     de codo/rodilla), sin introducir torsión sobre el eje del propio
     hueso (que sería rotar sobre Y). X es una elección arbitraria entre
     X/Z igualmente válida para el propósito de este test — no se busca
     verificar una pose anatómica concreta, solo ausencia de
     NaN/Inf/explosión numérica/huérfanos tras una deformación real.
     Verifica: sin NaN/Inf, bounding box deformado ≤3x la diagonal
     original, y (regresión) suma de pesos ≈1.0 en bind pose.

  **Verificación:** `pytest backend/tests/` completo → **26 passed**, 0
  failed (20 del Módulo 1 + 6 nuevos del Módulo 2).

  Módulo 2 cerrado formalmente: Armature real, auto-weight por difusión
  de calor, inspección visual (segmentación + heatmaps) y ahora métrica
  cuantitativa + test de deformación, todos verificados sobre los 3
  samples. Sin post-proceso de pesos (suavizado manual) — decisión
  tomada y documentada en el checkpoint de inspección visual del
  2026-08-20: no hacía falta a nivel visual, y la línea base cuantitativa
  de hoy no contradice esa lectura.

- **[Módulo 3 — clasificación de patas de apoyo] 2026-08-20** — Antes de
  tocar cinemática (ciclos de marcha, IK), `backend/app/limb_classification.py`
  (nuevo módulo) clasifica qué cadenas del árbol de esqueleto (ya
  calculado por `build_skeleton_tree`, Módulo 1) son candidatas a "pata
  de apoyo" — necesario para saber más adelante qué huesos mover en fase
  y qué punta debe tocar el suelo. Solo clasificación geométrica estática
  sobre la bind pose; nada de senos/cosenos ni IK todavía.

  **Criterio geométrico exacto** (`classify_support_limbs` en
  `limb_classification.py`):

  1. Una hoja del árbol es "de suelo" si su altura (coordenada Y, ejes
     glTF — el mismo espacio en el que trabaja todo `skeletonization.py`)
     está a ≤`DEFAULT_GROUND_THRESHOLD_PCT` (0.07) de la diagonal del
     bounding box por encima del Y mínimo global del modelo. Umbral
     relativo a la diagonal, mismo criterio que el resto del pipeline
     (`densify_long_edges` usa 0.10, `collapse_short_edges` /
     `simplify_chains_rdp` usan 0.005) — nunca una unidad absoluta nueva.
  2. Desde cada hoja de suelo, se sube por la jerarquía padre-hijo. En
     cada paso se comprueba si el nodo padre tiene algún OTRO hijo
     (hermano del nodo por el que veníamos subiendo) cuyo subárbol
     también contenga una hoja de suelo — es decir, si el padre es un
     punto donde de verdad divergen DOS patas distintas, no solo ruido
     de malla dentro de la propia pata — Y que el padre no esté él mismo
     cerca del suelo (si lo está, es solo el punto donde el propio pie se
     subdivide en dedos, no una bifurcación real de cadera/hombro). El
     `chain_root` resultante es el hijo justo por debajo de esa
     bifurcación real (el hueso concreto de cadera/hombro de ESA pata,
     no el nodo de cadera compartido por las dos) — el pivote que
     necesitará el futuro ciclo de marcha. Al llegar a la raíz del
     esqueleto sin encontrar una bifurcación así, la raíz se trata como
     tope de todas formas (para no correr indefinidamente en un modelo
     con una sola pata en todo el árbol, caso degenerado que no aparece
     en los 3 samples).
  3. Varias hojas de suelo con el mismo `chain_root` (dedos de un mismo
     pie) se agrupan en una única `LimbChain`.

  **Por qué excluye brazos/alas sin ningún caso especial:** en las 3
  muestras los modelos están en T-pose (o equivalente) — manos y puntas
  de ala quedan muy por encima del Y mínimo global (brazos de biped:
  rel≥0.53; ala de bat: rel≥0.33), así que sus hojas nunca entran en el
  paso 1. El criterio geométrico los deja fuera solo por altura, sin
  mirar nombre de hueso ni posición en la jerarquía.

  **Calibración del umbral (0.07, no 0.05):** el primer valor probado
  (0.05, calibrado solo mirando la altura de las HOJAS) daba a biped 3
  grupos en vez de 2 — un dedo del pie llegaba al tobillo por un camino
  de árbol distinto al del resto de dedos, con un nodo intermedio a
  rel=0.058 (justo por encima de 0.05, así que "no cerca del suelo") cuyo
  padre común con el resto del pie (rel=0.055) se interpretaba entonces
  como una bifurcación real de cadera en vez de una subdivisión interna
  del propio pie. Recalibrando mirando la altura de TODOS los nodos (no
  solo hojas) en los 3 samples: el nodo interior más alto que sigue
  siendo genuinamente parte de la zona pie/tobillo está en rel=0.058
  (biped), y el siguiente nodo por encima de eso — ya claramente parte de
  la espinilla — está en rel=0.087 (con el hueso de referencia "rodilla"
  del Módulo 2, `bone_71_118`, en rel=0.178). 0.07 separa ambos grupos
  con margen en los 3 modelos, sin necesidad de ajuste por modelo.

  **Resultado verificado sobre los 3 samples** (comparado contra lo ya
  sabido por inspección manual en checkpoints anteriores):

  | modelo | patas detectadas | chain_roots | esperado |
  |---|---|---|---|
  | cow | 4 | 31, 33, 27, 3 | 4 (cuadrúpedo) ✓ |
  | biped | 2 | 5, 88 | 2 (brazos excluidos) ✓ |
  | bat | 2 | 17, 15 | 1-2 (alas excluidas) ✓ |

  `backend/tests/test_limb_classification.py` (6 tests, todos en verde):
  nº de patas por modelo dentro del rango esperado (parametrizado);
  `chain_root`/`foot_leaf` son nodos reales del árbol y `foot_leaf` está
  entre `ground_leaves`; ninguna hoja de suelo se asigna a dos patas a la
  vez; y un chequeo explícito del criterio de exclusión pedido — en
  biped, ninguna hoja de mano/dedo (brazo) aparece dentro de
  `ground_leaves` de ninguna pata (rel<0.1 exigido; `chain_root` en
  cambio SÍ se espera a media altura — es la cadera/hombro, no se
  comprueba su altura).

  **Verificación:** `pytest backend/tests/` completo → **32 passed**, 0
  failed (26 de Módulos 1-2 + 6 nuevos de esta clasificación).

  Módulo 3 en curso: clasificación de patas cerrada y verificada. Sigue
  pendiente el ciclo de marcha/carrera paramétrico (senoidales con
  desfase de fase por extremidad), IK simple (CCD/FABRIK) para contacto
  con el suelo, y la pose de "asombro" — todo eso depende de tener esto
  verificado primero, ya lo está.

- **[Módulo 3 — IK simple (CCD) para una sola pata] 2026-08-20** —
  Cimiento previo al ciclo de marcha: `backend/app/ik_solver.py` resuelve
  IK por CCD (Cyclic Coordinate Descent) para UNA pata (un `LimbChain` de
  `limb_classification.py`), dado un objetivo 3D para su `foot_leaf`.
  Nada de coordinación multi-pata, trayectoria senoidal ni límites
  articulares todavía — es deliberadamente solo "puedo hacer que UN pie
  llegue a UN punto".

  **Reutiliza `skinning_quality.py` en vez de duplicar infraestructura**
  (tal y como pedía la tarea): se renombraron dos helpers que antes eran
  privados de ese módulo a públicos (`_global_matrices` →
  `compute_global_matrices`, `_trs_to_matrix` → `trs_to_matrix`) y se
  añadieron dos utilidades de cuaterniones que faltaban —
  `quat_conjugate` (inverso de un cuaternión unitario) y
  `matrix3_to_quat` (inversa de la conversión cuaternión→matriz ya
  existente, algoritmo estándar por casos según la traza) — porque CCD
  necesita, en cada sub-paso, la rotación global ACTUAL del padre de un
  hueso (no solo la de bind pose) para convertir una rotación calculada
  en espacio mundo a una actualización de la rotación LOCAL del hueso.

  **Por qué `apply_bone_rotation` (Módulo 2) no bastaba tal cual:** rota
  un solo hueso de una sola vez y devuelve posiciones de vértices de
  malla — CCD necesita, en cada sub-paso, (a) rotar un hueso DADO el
  estado ya acumulado de rotaciones de los huesos anteriores de la misma
  pasada, y (b) saber "dónde está el pie ahora", que no es un vértice de
  malla sino un punto virtual en la punta de la cadena de huesos.

  **El problema de "dónde está el pie" y su solución** (`tip_bone_and_offset`
  / `foot_position_given_rotations` en `ik_solver.py`): el último hueso
  de una cadena de pata es una hoja del árbol de esqueleto — no tiene
  ningún hijo en el glTF que codifique su propia longitud (a diferencia
  de un hueso intermedio, cuya longitud ES la traslación de su hijo). Se
  resuelve derivando, UNA SOLA VEZ en bind pose, el offset local fijo
  dentro del marco de ese hueso que representa la posición real del pie
  (usando `tree.nodes[foot_leaf]["pos"]` del árbol de esqueleto —
  Módulo 1 — como fuente de verdad de esa posición, ya que el propio
  build_armature.py generó el Armature a partir de esas mismas
  coordenadas); en cualquier pose posterior, la posición del pie es ese
  offset transformado por la matriz global ACTUAL del último hueso.

  **Algoritmo** (`solve_ik_ccd`, `chain_bone_names` da la cadena de
  huesos de pie a raíz — incluye el hueso que TERMINA en `chain_root`,
  el hueso concreto de cadera/hombro de esta pata): por cada hueso de la
  cadena, de pie a raíz, en cada pasada: (1) recalcula las matrices
  globales de todo el esqueleto con el estado actual; (2) el pivote de
  este hueso es la traslación de su propia matriz global (== posición
  mundo de la CABEZA de ese hueso, ver docstring — la traslación de la
  matriz global de un hueso "bone_P_C" da la posición del nodo P, no C,
  porque el origen local de un hueso ES su propia cabeza); (3) calcula la
  rotación en espacio mundo que llevaría pivote→pie sobre pivote→objetivo
  (eje = producto vectorial normalizado, ángulo = arco-coseno del
  producto escalar; se salta el hueso esta pasada si los vectores ya
  están alineados o son casi antiparalelos — eje indefinido, no aparece
  con los objetivos alcanzables usados en los tests); (4) convierte esa
  rotación de mundo a una actualización de la rotación LOCAL del hueso
  vía composición de cuaterniones con la rotación global actual del
  padre: `nueva_local = conj(G_padre) · R_mundo · G_padre · local_actual`.

  **Auto-chequeo obligatorio** (`verify_zero_displacement_converges_immediately`,
  igual patrón que `verify_identity_rotation_reproduces_bind_pose` del
  Módulo 2): un objetivo que coincide EXACTAMENTE con la posición del pie
  en bind pose debe converger SIN rotar nada (`iterations_used == 0`).
  Verificado en las 8 patas de los 3 modelos: error 1e-17 a 5e-16, muy
  por debajo de cualquier tolerancia razonable.

  **Objetivos de test alcanzables** (`test_ik_solver.py`,
  `_reachable_target`): en vez de inventar una posición 3D (la tarea
  pedía explícitamente evitarlo), cada objetivo se deriva rotando el
  hueso más próximo a `chain_root` un ángulo conocido (20°, -15° y 15°,
  sobre los ejes X y Z) y leyendo por cinemática directa dónde queda el
  pie — así el objetivo es, por construcción, una pose que la pata SÍ
  puede alcanzar con exactamente una rotación. Elección de eje: mismo
  criterio que `test_skinning.py` (`_FLEX_AXIS`) — los huesos de este
  armature apuntan a lo largo del eje Y local, así que X/Z flexionan sin
  torsión sobre el propio eje del hueso. Se probó primero con objetivos
  generados por desplazamiento radial directo hacia `chain_root` (más
  simple, pero **resultó ser irrealizable para patas de un solo hueso** —
  bat `chain_root=15=foot_leaf`: un hueso rígido solo puede mover la
  punta sobre una esfera de radio fijo alrededor de su cabeza, así que
  acercar el pie en línea recta al pivote es geométricamente imposible
  para esa pata concreta; el solver correctamente no convergía, error
  ~0.16-0.32 tras 200 iteraciones). Los objetivos por rotación conocida
  no tienen ese problema por construcción, para cadenas de cualquier
  longitud (1 a 14 huesos en estos 3 samples).

  **`DEFAULT_MAX_ITERATIONS = 500`:** CCD converge en pocas iteraciones
  para la mayoría de combinaciones pata/objetivo probadas (1-43), pero
  al menos una (cow, `chain_root=27`, flexión de -15° sobre X) necesitó
  356 — comportamiento conocido de CCD "de libro" (sin amortiguación ni
  límites articulares): para ciertas geometrías de cadena y direcciones
  de objetivo converge mucho más despacio sin que eso indique un bug (el
  error baja de forma monótona hasta el objetivo). 500 da margen sobre
  el peor caso observado; si una futura pata necesitara más, es señal de
  que hace falta amortiguación (damping) o una cota de ángulo por paso —
  mejora de una fase posterior, no de este cimiento.

  `backend/tests/test_ik_solver.py` (6 tests, todos en verde): el
  auto-chequeo de arriba para las 8 patas de los 3 modelos, y
  convergencia (`error < 1e-4`, `iterations_used <= 500`) para 3
  objetivos alcanzables por pata (24 combinaciones pata×objetivo en
  total).

  **Verificación:** `pytest backend/tests/` completo → **38 passed**, 0
  failed (32 de Módulos 1-2-3(clasificación) + 6 nuevos de este IK).

  Cimiento de IK cerrado y verificado. Siguiente paso del Módulo 3:
  coordinación de varias patas + trayectoria senoidal con desfase de fase
  (ciclo de marcha/carrera) — depende de tener esto verificado primero,
  ya lo está.

- **[Módulo 3 — trayectoria del pie de una sola pata] 2026-08-20** —
  Siguiente cimiento hacia el ciclo de marcha: `backend/app/gait_cycle.py`
  genera la posición objetivo 3D del pie de UNA pata en cualquier fase
  `phase` de un ciclo, sin coordinar varias patas ni calcular la
  dirección de zancada automáticamente todavía (eso depende de saber qué
  es "delante" del modelo — tarea de coordinación multi-pata).

  `foot_target_at_phase(bind_foot_position, chain_root_position,
  stride_direction, phase, stride_amplitude_pct=0.3,
  lift_height_pct=0.15)`: componente horizontal a lo largo de
  `stride_direction` = `stride_amplitude_pct · alcance · cos(2π·phase)`
  (alcance = `|chain_root_position - bind_foot_position|`, mismo criterio
  relativo al modelo que el resto del proyecto); componente vertical
  (+Y) = `lift_height_pct · alcance · max(0, sin(2π·phase))` — el pie
  solo se eleva sobre el suelo durante la mitad del ciclo (fase de
  "swing"), en la otra mitad ("stance") queda exactamente a la altura de
  bind pose. `stride_direction` se normaliza y se exige horizontal
  (componente Y ~0 tras normalizar, tolerancia 1e-6) — `ValueError` claro
  si no lo es, en vez de forzarlo en silencio.

  **Auto-chequeos obligatorios** (`verify_phase_periodicity`,
  `verify_never_below_ground` — mismo patrón `verify_*` que Módulos 2 y
  3): `phase=0` y `phase=1` coinciden con error 0.0 exacto (la
  periodicidad de `cos`/`sin` en 2π ya lo garantiza sin necesidad de
  envolver `phase` a mano); y ninguna de 1000 fases muestreadas produce
  una Y por debajo de la de bind pose (margen mínimo observado: 0.0,
  exactamente el límite, nunca negativo) — comprobado explícitamente en
  vez de fiarse solo de que la fórmula lleva un `max(0, ...)`.

  **Elección de pata y dirección de zancada para el test contra el
  solver de IK** (punto 3 de la tarea, el más exigente: ≥20 fases por
  todo el ciclo, no solo puntos sueltos):

  - Pata: la PRIMERA que devuelve `classify_support_limbs` por modelo
    (determinista, mismo orden en cada ejecución). Se comparó
    explícitamente contra "la de mayor alcance" antes de decidir: para
    cow, la pata de MAYOR alcance (`chain_root=27`) es precisamente una
    de las dos (de 4) que peor converge — no llega a converger en varias
    fases ni con 500 iteraciones (el límite de `ik_solver.py`), mientras
    que la primera (`chain_root=31`) converge con margen cómodo (máx.
    162 de 500). "Primera" no fue solo más simple de implementar, resultó
    ser también la más práctica en este caso concreto.
  - Dirección de zancada: `(0, 0, 1)` (eje Z), la misma para los 3
    modelos. Se probó primero el eje X (`(1,0,0)`): funciona sin
    problema para las patas elegidas de cow y biped, pero para la pata
    elegida de bat una fase concreta (`phase=0.0`, el extremo de máxima
    amplitud hacia adelante) necesitaba 606 iteraciones — por encima del
    presupuesto de `DEFAULT_MAX_ITERATIONS` (500), mismo tipo de
    convergencia lenta "de libro" ya documentado en el checkpoint de
    `ik_solver.py` (CCD sin amortiguación, no un bug). Con el eje Z las
    3 patas elegidas convergen con margen cómodo (máx. 180 de 500
    iteraciones sobre 30 fases en los 3 modelos).

  `backend/tests/test_gait_cycle.py` (11 tests, todos en verde):
  periodicidad y suelo-nunca-traspasado para las 3 patas elegidas;
  `ValueError` para `stride_direction` no horizontal o nulo; y, el test
  más exigente, `solve_ik_ccd` converge en las 30 fases muestreadas
  (`i/30` para `i` en `0..29`, cubre `phase≈0` máxima amplitud adelante,
  `phase≈0.5` máxima amplitud atrás y `phase≈0.25` máxima elevación) para
  cada una de las 3 patas elegidas — 90 combinaciones fase×modelo en
  total, cero fallos.

  **Verificación:** `pytest backend/tests/` completo → **49 passed**, 0
  failed (38 de Módulos 1-2-3(clasificación+IK) + 11 nuevos de esta
  trayectoria). Nota de rendimiento: el suite completo pasó de ~8s a
  ~65s — la mayor parte es este test nuevo (90 resoluciones de CCD, cada
  una hasta 500 iteraciones en el peor caso); aceptable para un test de
  verificación, no se ha optimizado más allá de eso.

  Cimiento de trayectoria de una sola pata cerrado y verificado.
  Siguiente paso del Módulo 3: coordinar varias patas (desfase de fase
  entre ellas) y calcular `stride_direction` automáticamente a partir de
  la orientación del modelo — depende de tener esto verificado primero,
  ya lo está.

- **[Módulo 3 — amplitud de zancada segura, fix de chain_root=27]
  2026-08-20** — El hallazgo pendiente del checkpoint anterior (cow,
  `chain_root=27`, no converge en varias fases del ciclo con
  `stride_amplitude_pct=0.3` fijo) resuelto: con esa amplitud, la
  distancia pedida entre `chain_root` y el objetivo llega al **92.1%**
  de la longitud física máxima real de la cadena en `phase=0.0` (y al
  87.0-91.9% en otras 3 fases) — ahí CCD converge extremadamente
  despacio o no converge en absoluto en 500 iteraciones (geometría casi
  degenerada, cadena casi totalmente estirada).

  **`max_chain_bone_length(limb, hierarchy, tree)`** (nuevo en
  `gait_cycle.py`): suma las longitudes de CADA hueso de la cadena
  (reutilizando `ik_solver.chain_bone_names`), a diferencia de `reach`
  (la distancia en línea recta `chain_root_position` ->
  `bind_foot_position` que ya usaba `foot_target_at_phase` como escala)
  — son iguales solo si la pata está perfectamente estirada en bind
  pose. Para `chain_root=27`: `reach=3.426`, `max_chain_length=3.992`
  (la pata ya está al 85.8% de su extensión total EN BIND POSE, antes de
  añadir ninguna zancada).

  **`safe_stride_amplitude_pct(...)`** (nuevo): búsqueda binaria sobre
  la amplitud (muestreando la fase igual que `verify_never_below_ground`
  — no hay forma cerrada simple, el punto más lejano de `chain_root`
  depende de cómo se combinan el offset horizontal y el vertical, no
  colineales en general) para encontrar la mayor amplitud ≤ la pedida
  tal que la distancia a `chain_root` no supere `safe_fraction ·
  max_chain_length` en ninguna fase. Si la amplitud pedida ya cumple, se
  devuelve sin tocar — clave para no romper las patas que ya iban bien.

  **Calibración de `safe_fraction` — el primer valor probado (0.85, el
  que pedía la tarea) NO sirvió**: `chain_root=31` (la pata de cow que
  YA convergía bien, 158 de 500 iteraciones, sin recorte) tiene su
  propia distancia máxima natural al 86.7% de su longitud máxima con la
  amplitud pedida (0.3) — POR ENCIMA de 0.85 — así que un `safe_fraction`
  de 0.85 la recortaba también (a amplitud 0.238), violando el requisito
  de no tocar las patas que ya iban bien. Subido a **0.87** (justo por
  encima de ese 86.7%): `chain_root=31` vuelve a devolver 0.3 sin
  recortar (158 iteraciones, idénticas a antes), y `chain_root=27` se
  recorta a amplitud ≈0.093, convergiendo en las 30 fases con **máx. 325
  de 500 iteraciones** (65% del presupuesto — ya no "pegado al límite").
  Probado también con 0.92 y 0.95: el recorte es casi nulo (amplitud
  final 0.2975-0.3) y las mismas 4 fases de `chain_root=27` siguen sin
  converger ni con 500 iteraciones — no basta con subir el umbral, hay
  que quedarse cerca de la banda que de verdad excluye las fases
  problemáticas.

  **Limitación honesta documentada en el propio docstring**: el % de la
  longitud máxima alcanzado NO predice perfectamente la dificultad de
  convergencia por sí solo — `chain_root=31` llega al 86.7% y converge
  en 158 iteraciones, mientras que `chain_root=27` ya falla en fases con
  un 87.0%. La geometría concreta de cada cadena (qué huesos necesitan
  doblarse y en qué dirección) importa además del porcentaje puro. Aun
  así, el recorte por este criterio relativo resuelve el caso conocido
  sin tocar el que no lo necesitaba, que es el objetivo de esta tarea —
  no una garantía general de convergencia rápida para cualquier pata
  futura.

  **Decisión de diseño (dónde vive el recorte)**: `foot_target_at_phase`
  se mantiene como fórmula geométrica pura, sin conocer nada de
  cinemática ni de si el resultado es alcanzable.
  `safe_stride_amplitude_pct` es un paso EXPLÍCITO PREVIO que quien
  genere la trayectoria de una pata llama UNA VEZ antes del bucle de
  fases (no dentro de él) — mismo patrón que los `verify_*` ya
  existentes: visible en el código de quien lo usa, no un efecto
  secundario oculto dentro de la fórmula.

  **`backend/tests/test_gait_cycle.py`** ampliado a 16 tests (antes 11):
  nuevo test de regresión `test_safe_amplitude_matches_expected_clipping`
  (las patas que ya iban bien devuelven amplitud 0.3 sin recortar; la
  problemática se recorta a algo entre 0 y 0.3) y `chain_root=27` de cow
  añadido explícitamente al conjunto de patas de
  `test_ik_converges_across_full_cycle` (ya no se evita) con un techo de
  iteraciones esperado por pata (margen generoso, no un valor exacto —
  solo para detectar una regresión de rendimiento real):

  | pata | ¿ya iba bien? | iteraciones máx. observadas | techo del test |
  |---|---|---|---|
  | cow chain_root=31 | sí | 158 | 250 |
  | cow chain_root=27 | no (el fix de esta tarea) | 325 | 400 |
  | biped chain_root=5 | sí | ~7-8 | 60 |
  | bat chain_root=17 | sí | 180 | 300 |

  **Verificación:** `pytest backend/tests/` completo → **54 passed**, 0
  failed (49 de antes + 5 nuevos: 4 combinaciones extra de
  `test_safe_amplitude_matches_expected_clipping`/`test_ik_converges_across_full_cycle`
  con el mismo `chain_root=27` sumado a las 3 patas ya existentes).

  Amplitud de zancada segura cerrada y verificada. Todavía pendiente del
  Módulo 3: coordinación de varias patas moviéndose a la vez, desfase de
  fase entre ellas, dirección de zancada automática (a partir de la
  orientación del modelo) y límites articulares.

- **[Módulo 3 — fallo direccional de CCD, cow chain_root=3] 2026-08-21**
  — Verificación independiente confirmó un segundo hallazgo pendiente:
  `chain_root=3` de cow (otra pata delantera) no converge en varias
  fases (phase=0.500-0.567, "zancada hacia atrás") con
  `stride_amplitude_pct=0.3` SIN recortar — pese a que
  `safe_stride_amplitude_pct` no la recorta, porque su distancia pedida
  (~81% de la longitud física máxima) no supera el umbral de recorte
  (`safe_fraction=0.87`). Confirmado exactamente como lo describía el
  hallazgo: `phase=0.000` (zancada hacia ADELANTE, dist_pct=80.2%)
  converge en 354 iteraciones; `phase=0.500` (zancada hacia ATRÁS,
  dist_pct=81.3% — magnitud casi idéntica) no converge ni en 500. Esto
  prueba que el problema es DIRECCIONAL, no de magnitud — recortar la
  amplitud de forma uniforme (como hace `safe_stride_amplitude_pct`) NO
  puede arreglarlo: para hacerlo tendría que recortar tanto que también
  arruinaría la zancada hacia adelante, que no tiene ningún problema (se
  comprobó explícitamente: con `safe_fraction=0.80` la amplitud queda en
  0.2414 y AÚN ASÍ casi no converge en 500 iteraciones; con 0.75 la
  amplitud colapsa a 0.0, matando la zancada completa en ambas
  direcciones solo para arreglar una).

  **Investigación de la causa raíz** (instrumentación directa del bucle
  de CCD, imprimiendo eje/ángulo elegido en cada sub-paso de las
  primeras iteraciones, para `phase=0.0` que converge vs `phase=0.5` que
  no): en la fase que falla, los dos huesos más próximos a `chain_root`
  (`bone_3_29`, el "muslo", y `bone_2_3`, el hueso de cadera/hombro que
  termina en `chain_root`) rotan ángulos casi nulos en cada pasada
  (máx. 1.18° y 0.41° respectivamente, sobre las primeras 5 pasadas),
  frente a 5.39° y 0.95° en la fase que converge bien. Con esos dos
  huesos casi inmóviles, todo el trabajo de cerrar la distancia recae en
  el hueso más distal (`bone_29_15`, el más corto de los tres, 1.04 de
  longitud sobre una cadena de 3.94), que no da abasto — CCD evalúa a
  cada hueso por el ÁNGULO necesario visto desde SU PROPIO pivote, y en
  esta dirección concreta ese ángulo resulta pequeño para los dos huesos
  proximales aunque el ERROR global de posición siga siendo grande (el
  vector pivote→pie y pivote→objetivo están casi alineados en dirección
  aunque no en magnitud) — un punto ciego conocido de CCD "de libro"
  (greedy, sin mirar el error global), no oscilación: el error decrece
  de forma monótona y suave a lo largo de las 724 iteraciones que
  termina necesitando (se reduce aproximadamente a la mitad cada ~100
  pasadas: 0.026 → 0.009 → 0.004 → 0.0016 → 0.0007 → 0.0003 → 0.0001 →
  converge), confirmado explícitamente muestreando el error cada 100
  iteraciones hasta 900.

  **Mecanismos alternativos probados y descartados** (antes de decidir
  el fix):
  - Amortiguar el ángulo aplicado por paso (multiplicar por un factor
    <1): empeora las cosas — con `damping=0.5` el error tras 500
    iteraciones sube a 0.0105 (peor que sin amortiguar, 0.00067); tiene
    sentido, amortiguar solo hace más lento algo que ya era lento sin
    resolver el punto ciego geométrico.
  - Invertir el orden de recorrido de CCD (raíz→pie en vez de pie→raíz,
    o alternar): no es una mejora general. Probado sobre las 8 patas de
    los 3 modelos con 30 fases cada una: raíz→pie SÍ arregla
    `chain_root=3` (583 iteraciones en vez de 724) pero EMPEORA
    `chain_root=27` (668 en vez de 556) — ninguno de los dos órdenes
    domina al otro, depende de la pata/fase concreta, así que cambiar el
    orden global habría cambiado qué pata falla, no eliminado el
    problema.
  - **Elegido: subir `DEFAULT_MAX_ITERATIONS`** (igual que ya se hizo
    dos veces antes en este módulo, de 50→200→500, por la misma razón:
    convergencia lenta pero monótona, no un límite de alcance real).
    Verificado con presupuesto amplio (1500) sobre las **8 patas de los
    3 modelos**, 30 fases cada una, con la amplitud real de
    `safe_stride_amplitude_pct`: CERO fallos en las 240 combinaciones
    pata×fase, peor caso 724 iteraciones (`chain_root=3`). Subido a
    **1000** (~35% de margen sobre 724).

  **Verificación final por pata** (8 de 8, todas convergen en las 30
  fases con `DEFAULT_MAX_ITERATIONS=1000`):

  | pata | amplitud (tras `safe_stride_amplitude_pct`) | iteraciones máx. |
  |---|---|---|
  | cow chain_root=31 | 0.300 (sin recortar) | 158 |
  | cow chain_root=33 | 0.300 (sin recortar) | 83 |
  | cow chain_root=27 | 0.093 (recortada) | 325 |
  | cow chain_root=3 | 0.300 (sin recortar) | **724** ← peor caso |
  | biped chain_root=5 | 0.300 (sin recortar) | 8 |
  | biped chain_root=88 | 0.300 (sin recortar) | 9 |
  | bat chain_root=17 | 0.300 (sin recortar) | 180 |
  | bat chain_root=15 | 0.300 (sin recortar) | 0 |

  Ninguna otra pata de biped o bat mostró el mismo problema direccional
  (punto 5 de la tarea) — el hallazgo parece específico de la geometría
  de `chain_root=3` en cow (hueso "muslo" desproporcionadamente largo,
  2.06 de 3.94 de longitud total de cadena, más del 50%).

  **`backend/tests/test_gait_cycle.py`** ampliado de 4 a **8 patas
  probadas** (las 4 de cow + las 2 de biped + las 2 de bat — ya no una
  sola por modelo, precisamente para que un problema direccional como
  este no pueda volver a pasar desapercibido con una sola pata
  "representativa"): 24 tests (antes 16).

  **Verificación:** `pytest backend/tests/` completo → **62 passed**, 0
  failed.

  **Depuración visual** (`backend/scripts/_plot_leg_reach_debug.py`,
  nuevo, matplotlib puro sin Blender — no forma parte de los tests):
  dibuja en 2D (plano `stride_direction`/Y, origen en `chain_root`) la
  cadena de huesos en bind pose + los 30 objetivos del ciclo,
  verde/rojo según si `solve_ik_ccd` converge. Generado para
  `chain_root=3` antes (`--max-iterations 500`,
  `samples/_debug/cow_root3_before_fix.png`, 27/30, los 3 puntos rojos
  agrupados en el lado de "zancada hacia atrás") y después
  (`cow_root3_after_fix.png`, 30/30) del fix, y para `chain_root=27`
  (`cow_root27_after_fix.png`, muestra visualmente el arco de objetivos
  mucho más pequeño tras el recorte de amplitud — el otro tipo de fix,
  por magnitud en vez de por presupuesto de iteraciones). Añadido
  `matplotlib` a `requirements.txt` (ya estaba instalado transitivamente,
  ahora es una dependencia directa).

  Fallo direccional de `chain_root=3` cerrado y verificado. Todavía
  pendiente del Módulo 3: coordinación de varias patas moviéndose a la
  vez, desfase de fase entre ellas, dirección de zancada automática y
  límites articulares.

- **[Módulo 3 — detección automática de dirección de zancada] 2026-08-21**
  — `detect_stride_direction(limbs, tree)` en `gait_cycle.py`: hasta
  ahora `stride_direction` se pasaba a mano en todos los tests. Dos
  casos según el nº de patas (usa `chain_root_position` de cada pata, no
  `foot_leaf` — más estable, no depende de la pose concreta del pie):

  - **2 patas** (biped Y bat en estos samples — no solo biped; bat
    también tiene exactamente 2, ver nota más abajo): dirección
    horizontal perpendicular a la línea entre las dos
    `chain_root_position`, proyectada al plano X-Z.
  - **3+ patas** (cow, único caso con ≥3 en estos samples): PCA sobre
    (X,Z) de TODOS los `chain_root_position` — el eje de mayor varianza.
    Con solo 2 patas esto degeneraría al eje de la propia línea que las
    une (la dirección EQUIVOCADA, a lo largo en vez de perpendicular), de
    ahí el caso especial de arriba.

  **Corrección respecto al enunciado de la tarea**: se pedía verificar
  "cow/bat (≥3 patas)" asumiendo que bat tiene 3 o más — no es así,
  `classify_support_limbs` da exactamente 2 patas para bat (las dos
  traseras; alas excluidas, ver Módulo 3 — clasificación de patas). Bat
  usa por tanto la rama de 2 patas (perpendicular a la línea), igual que
  biped, no la rama PCA. Verificado igualmente para los 3 modelos.

  **Signo NO resuelto — limitación deliberada, documentada en el
  docstring**: no hace falta saber qué extremo es "adelante" todavía,
  porque `foot_target_at_phase` es simétrico respecto al signo de
  `stride_direction` (invertirlo solo desplaza la fase medio periodo,
  no cambia la forma de la trayectoria ni si converge). Resolver el
  signo necesita saber dónde está la cabeza/cola, no solo dónde están
  las patas — tarea de coordinación multi-pata, después.

  **Verificación visual** (`backend/scripts/_plot_stride_direction_debug.py`,
  nuevo, matplotlib sin Blender): vista cenital (X-Z) de las 3 patas +
  flecha de dirección detectada desde el centroide de las
  `chain_root_position`, con ventana de vista dimensionada por percentil
  (no min/max, para no dejar que unos pocos puntos extremos —dedos de
  una mano totalmente extendida en T-pose, p. ej.— dominen la escala).
  Comprobado a ojo sobre los 3 modelos (`samples/_debug/{modelo}_stride_direction.png`):

  - cow: flecha a lo largo del eje delantero-trasero del cuerpo (hacia
    las patas delanteras, cerca de cabeza/pecho) ✓.
  - bat: flecha hacia el racimo de nodos de cabeza/orejas/nariz,
    perpendicular al eje de las alas (que se extienden en diagonal, no a
    lo largo de este eje) ✓.
  - biped: flecha perpendicular a la línea entre las dos caderas ✓.

  Ningún eje salió equivocado (solo el signo es arbitrario, como se
  esperaba) — no hizo falta ningún fix de bug de orientación, solo dos
  iteraciones de ajuste de escala de la propia ventana del render (ver
  historial de commits del script) para que la flecha fuera visible con
  suficiente contexto corporal en los 3 modelos.

  **`backend/tests/test_gait_cycle.py`** ampliado con 6 tests nuevos
  (30 en total, antes 24): horizontalidad exacta para los 3 modelos
  (`test_stride_direction_is_horizontal`), y un chequeo cruzado contra
  un recálculo INDEPENDIENTE hecho desde cero en el propio test
  (`_independent_stride_direction` — PCA vía SVD en vez de autovalores
  de covarianza para el caso de cow, mismo cálculo pero camino de código
  distinto; no un vector esperado escrito a mano), comparando el ángulo
  entre ambos vectores tratando signo positivo y negativo como
  equivalentes (<1° de diferencia exigido) — para los 3 modelos, no
  solo cow (`test_stride_direction_matches_independent_recomputation`).

  **Verificación:** `pytest backend/tests/` completo → **68 passed**, 0
  failed (62 de antes + 6 nuevos).

  Detección automática de dirección de zancada cerrada y verificada.
  Todavía pendiente del Módulo 3: asignación de fases entre patas,
  patrón de marcha (trote, alternancia...), resolución del signo de
  `stride_direction`, y límites articulares.

- **[Módulo 3 — reparto de fase entre patas] 2026-08-21** —
  `assign_limb_phase_offsets(limbs, tree, stride_direction)` en
  `gait_cycle.py`: asigna un desfase (`phase_offset`, en {0.0, 0.5}) a
  cada pata para que varias patas puedan animarse a la vez sin pisarse
  — `foot_target_at_phase(..., phase=fase_global + phase_offset)` ya es
  periódica, no hizo falta tocarla. NO conecta todavía con
  `solve_ik_ccd` en un bucle de varias patas — eso es la tarea
  siguiente.

  **Dos casos, mismo estilo de ramificación honesta que
  `detect_stride_direction`** (solo cubre 2 o 4 patas, lo que aparece en
  los 3 samples; cualquier otro nº lanza `NotImplementedError`
  explícito):

  - 2 patas (biped, bat): alternancia simple, ordenando por
    `chain_root` para que sea determinista. Cuál pata "empieza" es
    arbitrario — igual que el signo de `stride_direction`.
  - 4 patas (cow): trote por pares diagonales. `side_axis =
    normalizado(cross((0,1,0), stride_direction))`; para cada pata,
    `proj_front` = proyección de `chain_root_position` sobre
    `stride_direction` (relativa al centroide de todas las
    `chain_root_position`) y `proj_side` = proyección de
    `foot_leaf_position` sobre `side_axis` (relativa al centroide de
    todas las `foot_leaf_position`); grupo `"A"` si
    `sign(proj_front) == sign(proj_side)`, si no `"B"` — A→0.0, B→0.5.
    Assert interno (sin silenciar) de que salen exactamente 2 patas por
    grupo.

  **Hallazgo que motivó usar `foot_leaf` en vez de `chain_root` para
  `proj_side`** (verificado con las posiciones reales del modelo antes
  de escribir la función, no solo intuido): las dos patas traseras de
  cow (`chain_root=31` y `chain_root=33`) tienen EXACTAMENTE la misma
  `chain_root_position` — `(-0.2268, 3.0065, -2.7436)` para ambas,
  coordenada por coordenada. Esto tiene sentido con lo ya documentado en
  el checkpoint de `limb_classification.py`: el `chain_root` de una pata
  es el nodo justo por debajo de la bifurcación real de cadera/hombro
  compartida por ambas patas de ese lado del cuerpo, así que dos patas
  hermanas pueden colgar del mismo nodo antes de divergir más abajo en
  la jerarquía. Usar `chain_root_position` para `proj_side` habría
  colapsado la proyección lateral a un valor idéntico para ambas patas
  traseras (`sign(0)` es ambiguo/inestable), rompiendo el agrupamiento
  por pares. `foot_leaf_position` no tiene este problema — es
  literalmente el punto de apoyo en el suelo, nunca compartido entre dos
  patas distintas.

  **Verificación visual** (`backend/scripts/_plot_phase_offsets_debug.py`,
  nuevo, matplotlib sin Blender, mismo patrón que
  `_plot_stride_direction_debug.py`): vista cenital (X-Z), cada pata
  coloreada según su `phase_offset` (azul=0.0, rojo=0.5). Comprobado a
  ojo sobre los 3 modelos (`samples/_debug/{modelo}_phase_offsets.png`):
  en cow, los dos pares de colores quedan en DIAGONAL de verdad
  (delantera-derecha + trasera-izquierda en un color, delantera-
  izquierda + trasera-derecha en el otro) — no "los dos de un lado" ni
  "delante vs atrás", que habría sido un agrupamiento con sentido
  numérico pero conceptualmente equivocado para un trote. Biped y bat
  alternan correctamente entre sus 2 patas.

  **`backend/tests/test_gait_cycle.py`** ampliado con 4 tests nuevos
  (34 en total, antes 30): alternancia de biped/bat (el resultado es
  exactamente `{0.0, 0.5}` como conjunto, sin asumir qué pata recibe
  cuál); agrupamiento diagonal de cow verificado contra un recálculo
  INDEPENDIENTE hecho desde cero en el propio test
  (`_independent_cow_diagonal_pairs`, mismo patrón que
  `_independent_stride_direction`, no reutiliza la función bajo
  prueba); e invarianza al orden de entrada de `limbs` (el agrupamiento
  relativo no cambia si se invierte la lista, aunque el valor absoluto
  0.0/0.5 de cada grupo sí pueda invertirse).

  **Verificación:** `pytest backend/tests/` completo → **72 passed**, 0
  failed (68 de antes + 4 nuevos).

  Reparto de fase entre patas cerrado y verificado. Todavía pendiente
  del Módulo 3: conectar este patrón de fases a un bucle real de varias
  patas moviéndose a la vez con `solve_ik_ccd`, resolución del signo de
  `stride_direction`, límites articulares y la pose de "asombro".

- **[Módulo 3 — pose de marcha completa, varias patas a la vez]
  2026-08-21** — `solve_gait_cycle_pose` en `gait_cycle.py`: dado un
  `global_phase` único, calcula la pose de TODAS las patas de un modelo
  a la vez, cada una en su propia fase local (`global_phase +
  phase_offsets[chain_root]`), resuelta con `solve_ik_ccd` y combinada
  en un único dict de rotaciones para todo el esqueleto. Nada de límites
  articulares ni pose de "asombro" todavía.

  **Paso previo separado, `compute_safe_amplitudes(limbs, tree,
  hierarchy, stride_direction)`**: `max_chain_bone_length` +
  `safe_stride_amplitude_pct` para cada pata, UNA VEZ (no por fase) —
  mismo criterio de separación de responsabilidades que ya defendía el
  docstring del módulo para `safe_stride_amplitude_pct` en sí (paso
  explícito previo al bucle de fases, nunca un recorte implícito
  repetido en cada llamada).

  **Independencia entre patas, verificada, no solo asumida**: las patas
  son cadenas de huesos disjuntas (`classify_support_limbs` garantiza
  implícitamente que ningún hueso pertenece a dos `LimbChain` distintas
  — cada una es una rama separada del árbol de esqueleto), así que
  resolverlas una a una con `solve_ik_ccd` y combinar los
  `local_rotations` al final es válido; no hace falta un solver
  conjunto. Cada `IKResult.local_rotations` ya trae la rotación de bind
  pose para los huesos FUERA de su propia cadena, así que combinar es
  simplemente: empezar el dict en bind pose completo, y para cada pata
  sobrescribir solo las entradas de sus propios huesos
  (`chain_bone_names` + `name_to_node_index`). Se comprobó
  explícitamente (no solo se asumió) que resolver varias patas a la vez
  no necesita más iteraciones que resolverlas por separado — en las 3×24
  combinaciones modelo×fase probadas, cero fallos y ninguna pata excedió
  su presupuesto de iteraciones ya conocido.

  **Verificación visual** (`backend/scripts/_plot_gait_cycle_debug.py`,
  nuevo, matplotlib sin Blender, mismo patrón de estilo que los scripts
  anteriores): un subplot por pata, altura (Y) del pie resuelto frente a
  `global_phase` en 40 puntos. Comprobado a ojo sobre los 3 modelos
  (`samples/_debug/{modelo}_gait_cycle_heights.png`):

  - cow: las curvas de `chain_root=31` y `chain_root=27` (mismo grupo
    diagonal, `phase_offset=0.0`) son PRÁCTICAMENTE IDÉNTICAS entre sí
    (pico en `phase≈0.23`), y las de `chain_root=33`/`chain_root=3`
    (el otro par, `phase_offset=0.5`) también lo son entre ellas (pico
    en `phase≈0.73`) — desfasadas exactamente medio periodo respecto al
    primer par. Confirma visualmente, no solo por los números de
    `assign_limb_phase_offsets`, que el trote diagonal funciona de
    verdad en la trayectoria resuelta.
  - biped: alternancia limpia entre las 2 patas, picos desfasados medio
    periodo.
  - bat: `chain_root=17` muestra el patrón de swing esperado;
    `chain_root=15` sale COMPLETAMENTE PLANO — consistente con un
    hallazgo ya documentado (checkpoint del `chain_root=15` de bat en
    módulos anteriores: esta pata tiene `chain_root == foot_leaf`, un
    solo hueso, `reach=0` por construcción, así que
    `safe_stride_amplitude_pct` no tiene ninguna distancia sobre la que
    aplicar amplitud — el pie se queda fijo en su posición de bind pose
    durante todo el ciclo). No es un bug nuevo, es la extensión esperada
    de algo ya sabido.

  **`backend/tests/test_gait_cycle.py`** ampliado con 5 tests nuevos
  (39 en total, antes 34): convergencia de TODAS las patas en >=20 fases
  globales por modelo (`test_all_limbs_converge_across_full_cycle` —
  comprobado explícitamente que combinar patas no degrada la
  convergencia, no solo asumido por la independencia teórica);
  preservación de huesos ajenos a cualquier pata en bind pose exacta
  (`test_combined_rotations_preserve_non_limb_bones`, cow: columna,
  cabeza, cola...); y confirmación de que el desfase se aplica de
  verdad, no solo que todo converge a algún punto (`test_
  phase_zero_offset_limbs_at_forward_extreme`, cow, `global_phase=0.0`
  — verificado por cinemática directa sobre el dict COMBINADO, no
  confiando solo en `IKResult.final_error` de cada pata por separado).

  **Verificación:** `pytest backend/tests/` completo → **77 passed**, 0
  failed (72 de antes + 5 nuevos).

  Pose de marcha con varias patas a la vez cerrada y verificada.
  Todavía pendiente del Módulo 3: resolución del signo de
  `stride_direction` (qué extremo es "adelante"), límites articulares
  anatómicos, y la pose de "asombro".

- **[Módulo 3 — ejes de bisagra por articulación] 2026-08-21** — Primer
  cimiento de límites articulares: `joint_limits.compute_hinge_axes`
  (nuevo módulo `backend/app/joint_limits.py`, y nuevo archivo de test
  `backend/tests/test_joint_limits.py` — pieza distinta del proyecto).
  Para cada hueso de una `LimbChain`, calcula su eje de bisagra NATURAL
  en bind pose (el eje alrededor del cual esa articulación CONCRETA se
  dobla, no uno global para toda la pata). Todavía NO aplica ningún
  límite de ángulo ni toca `solve_ik_ccd` — eso depende de tener
  primero ejes verificados que tengan sentido.

  **Dos diseños descartados con datos reales, documentados en el
  docstring para no reintentarlos**:
  1. Un `side_axis` único por pata (análogo al de
     `assign_limb_phase_offsets`): la alineación con el eje local real
     de cada articulación varía entre 10° y 89° en biped — inservible.
  2. Un plano de mejor ajuste (SVD) sobre TODOS los nodos de la
     cadena: funciona en cow (patas cortas, casi planas) pero falla en
     biped, cuya cadena incluye falanges de un dedo del pie que no
     bisagran en el mismo plano que la rodilla.

  **Diseño que sí funciona**: por cada hueso "bone_P_C", eje =
  `normalizado(cross(incoming, outgoing))` donde `incoming = pos[P] -
  pos[GP]` (del abuelo al padre) y `outgoing = pos[C] - pos[P]` (del
  padre al hijo) — la normal al plano de flexión LOCAL de esa
  articulación concreta en su postura de reposo.

  **Caso 1 — exclusión a propósito (cadera/hombro pegada a la raíz)**:
  si `GP = hierarchy[P]` es `None` (P es la propia raíz del esqueleto),
  no hay "entrante" del que derivar nada — es la articulación más
  proximal, anatómicamente más "bola" que "bisagra". Verificado sobre
  los 3 modelos: excluye `bone_2_27` y `bone_2_3` en cow (las dos patas
  delanteras cuelgan directamente de la raíz; las traseras NO, pivotan
  en el nodo 4, un nivel más abajo) y `bone_13_17` en bat. La pata
  `chain_root=15` de bat (un solo hueso, `bone_13_15`) queda con el
  dict VACÍO — su único hueso cae en este caso, coherente con ser una
  pata de un solo hueso sin ninguna bisagra propiamente dicha.

  **Caso 2 — geometría casi degenerada, con umbral verificado
  empíricamente**: si el ángulo entrante/saliente está fuera de
  `[10°, 170°]` (`cross` numéricamente inestable ahí), el hueso se
  marca "pendiente" y hereda el eje del vecino resuelto más cercano en
  la misma cadena (buscando hacia ambos lados en `chain_bone_names`).
  Con `degenerate_angle_threshold_deg=10.0` (el valor pedido),
  recalculando los ángulos reales de biped se confirmó EXACTAMENTE lo
  ya reportado: 3 huesos degenerados —
  `bone_32_5` (8.27°, hereda de `bone_5_71`), `bone_192_240` (9.66°,
  hereda de `bone_240_267`) y `bone_141_174` (3.72°, hereda de
  `bone_174_274`) — los tres con eje heredado EXACTAMENTE igual (no
  solo aproximado) al de su vecino, verificado en
  `test_degenerate_joints_inherit_from_neighbor` re-calculando los
  ángulos desde cero en el propio test, no hardcodeados de memoria.

  **Verificación visual** (`backend/scripts/_plot_hinge_axes_debug.py`,
  nuevo, matplotlib sin Blender): esqueleto en bind pose proyectado
  sobre el plano de mayor variación de LAS PATAS (PCA restringido a los
  nodos de las cadenas, no de todo el cuerpo — primera versión usaba
  todo el esqueleto y en biped el plano salía dominado por el brazo
  extendido en T-pose, irrelevante para las bisagras de las piernas;
  corregido antes de dar la tarea por buena), con una flecha por
  pivote a lo largo de su eje. Comprobado a ojo sobre los 3 modelos
  (`samples/_debug/{modelo}_hinge_axes.png`): en cow, las flechas de
  cada pata muestran variación razonable pero ninguna gira en una
  dirección descabellada respecto a sus vecinas ni respecto al eje
  lateral aproximado del cuerpo; en biped, la zona de dedos del pie
  (muy densificada) muestra bastante ruido visual por la cantidad de
  huesos superpuestos, pero las articulaciones grandes (cadera, rodilla,
  tobillo) se ven razonables; en bat, `chain_root=17` muestra su único
  eje resuelto con sentido, `chain_root=15` no muestra ninguna flecha
  (dict vacío, esperado).

  **`backend/tests/test_joint_limits.py`** (9 tests, todos en verde):
  3 huesos de cow bien definidos (identificados inspeccionando los
  ángulos reales antes de escribir el test, todos >20°) verificados
  contra una fórmula directa recalculada en el propio test; exclusión
  del pivote cadera/hombro confirmada en cow y bat; herencia de los 3
  huesos degenerados de biped confirmada (re-detectados en el propio
  test, no hardcodeados) con eje EXACTAMENTE igual al de un vecino; y
  norma unitaria de todos los ejes devueltos en los 3 modelos.

  **Verificación:** `pytest backend/tests/` completo → **86 passed**, 0
  failed (77 de antes + 9 nuevos).

  Ejes de bisagra calculados y verificados. Todavía pendiente del
  Módulo 3 (y de este sub-tema de límites articulares en concreto):
  APLICAR un límite de ángulo de verdad alrededor de estos ejes dentro
  de `solve_ik_ccd` (esta tarea solo calcula los ejes, no restringe
  ninguna rotación todavía) — más resolución del signo de
  `stride_direction` y la pose de "asombro".

- **[Módulo 3 — ejes de bisagra en marco local del padre] 2026-08-21**
  — `joint_limits.hinge_axes_in_local_frame(skin_data, hinge_axes)`:
  convierte cada eje de `compute_hinge_axes` (fijado en el
  espacio-mundo de la BIND POSE) al marco LOCAL de su hueso padre en
  bind pose. Todavía NO aplica ningún límite de ángulo ni toca
  `solve_ik_ccd` — eso sigue siendo la tarea siguiente, ahora sí con el
  marco de referencia correcto verificado.

  **Por qué hace falta (el motivo real de esta tarea)**: un eje fijado
  en coordenadas de MUNDO solo es válido mientras la pata está en bind
  pose. En cuanto el ciclo de marcha empiece a mover la pata, ese eje
  "congelado en el mundo" deja de tener sentido — la bisagra de la
  rodilla debe girar CON el muslo (co-rotar con el hueso padre), no
  quedarse fija en una dirección absoluta. Expresado en el marco LOCAL
  del padre en bind pose, el eje de mundo válido en CUALQUIER pose
  futura se recupera con una simple multiplicación:
  `rotación_global_actual_del_padre @ eje_local` — exactamente el tipo
  de recomposición que `solve_ik_ccd` ya hace en cada sub-paso de CCD
  para otras cosas (mismo concepto de `parent_index` que ya usa su
  propio bucle).

  **Algoritmo**: `local_axis = parent_rotation.T @ world_axis`, donde
  `parent_rotation` es la matriz de rotación 3x3 (extraída de
  `compute_global_matrices` sobre bind pose) del nodo PADRE de ese
  hueso — la transpuesta de una rotación pura es su inversa, evita
  invertir explícitamente. `compute_global_matrices` se llama UNA VEZ
  para las matrices de bind pose de todo el esqueleto, no por hueso.

  **Test que de verdad importa: co-rotación con una pose distinta de
  bind pose** (`test_hinge_axis_co_rotates_with_ancestor_perturbation`,
  cow, 2 huesos): antepone una rotación de 30° sobre Y en la rotación
  LOCAL de la RAÍZ del esqueleto entero (así toda rotación global
  descendiente queda multiplicada por la misma rotación por la
  izquierda, sin ambigüedad de qué nodo perturbar), recalcula las
  matrices globales de esa pose PERTURBADA, y confirma que
  `nueva_rotación_global_del_padre @ eje_local` coincide (atol=1e-6, el
  margen que ya usa el resto del proyecto para composiciones largas de
  cuaterniones) con rotar el `world_axis` ORIGINAL directamente por esa
  misma rotación de 30° — calculado de forma completamente
  independiente (rotación de vector vía cuaternión, no reutilizando
  ninguna matriz de la función bajo prueba). Confirma que el eje local
  sirve para recuperar la dirección de mundo válida en una pose
  CUALQUIERA, no solo en la propia bind pose de la que se derivó —
  exactamente lo que hará falta cuando `solve_ik_ccd` esté resolviendo
  otras articulaciones de la misma pata (tarea siguiente).

  **Segundo test de verificación cruzada**
  (`test_local_axis_reconstructs_world_axis_via_independent_global_rotation`,
  cow, los mismos 3 huesos bien definidos de la tarea anterior):
  recalcula la rotación global de bind pose del nodo padre recorriendo
  a mano la cadena de padres desde `root_node_index` y componiendo
  cuaterniones con `quat_multiply` — sin pasar por
  `compute_global_matrices` en absoluto — y compara, rotando el eje
  local por esa vía, contra `parent_rotation @ local_axis` (con el
  `parent_rotation` que sí usa la función bajo prueba). Confirma que no
  se cogió el nodo equivocado como "padre" ni se invirtió mal la
  rotación, por una ruta de cálculo genuinamente distinta. Ambos tests
  necesitaron `atol=1e-6` en vez de `1e-8` (primer intento): la
  composición manual de cuaterniones a lo largo de cadenas largas
  acumula el mismo nivel de ruido de punto flotante ya visto y
  documentado en checkpoints anteriores del proyecto (p. ej. el
  auto-chequeo de `verify_identity_rotation_reproduces_bind_pose` del
  Módulo 2, error ~1e-6), no un bug.

  Sin script de depuración visual nuevo para esta tarea (decisión
  explícita, no un descuido): a diferencia de los ejes en sí mismos
  (ambiguos/visuales, merecían un render para juzgar a ojo si tenían
  sentido anatómico), esto es una transformación de marco de referencia
  puramente matemática con una propiedad exacta y verificable
  numéricamente — el test de co-rotación ya da una verificación más
  precisa que cualquier plot.

  **`backend/tests/test_joint_limits.py`** ampliado con 8 tests nuevos
  (17 en total, antes 9): reconstrucción del eje de mundo por una ruta
  independiente (3 huesos de cow), norma unitaria de los ejes locales
  en los 3 modelos, y co-rotación bajo perturbación del ancestro (2
  huesos de cow, la prueba clave de esta tarea).

  **Verificación:** `pytest backend/tests/` completo → **94 passed**, 0
  failed (86 de antes + 8 nuevos).

  Ejes de bisagra en marco local verificados, incluida la propiedad de
  co-rotación que es la razón de ser de esta tarea. Todavía pendiente
  del Módulo 3: APLICAR el límite de ángulo de verdad dentro de
  `solve_ik_ccd` usando estos ejes locales (esta tarea tampoco lo
  hace), resolución del signo de `stride_direction`, y la pose de
  "asombro".

- **[Módulo 3 — CORRECCIÓN: pivote de cadera mal excluido en patas
  traseras] 2026-08-21** — Bug real en `compute_hinge_axes`
  (checkpoint del `bfe4e26`), encontrado prototipando la integración
  con `ik_solver.solve_ik_ccd` fuera de este entorno (sin Blender,
  pygltflib/trimesh/numpy puro) — NO por un test que fallara.

  **El bug**: el criterio de exclusión original (`if grandparent_node
  is None: continue`) asumía que el pivote de cadera/hombro de una pata
  cuelga SIEMPRE directamente de la raíz del esqueleto. Cierto para las
  patas delanteras de cow (`bone_2_27`, `bone_2_3`) y para bat
  (`bone_13_17`), pero FALSO para las patas TRASERAS de cow: su pivote
  real es `bone_4_31`/`bone_4_33`, y el nodo `4` (pelvis) SÍ tiene padre
  propio en la jerarquía (no es la raíz) — así que con el criterio
  antiguo NO se excluían, se trataban como bisagra estricta con un eje
  calculado igual que cualquier otro hueso. Mismo problema en biped:
  `bone_32_5` (cadera) caía en la rama de "geometría degenerada"
  (ángulo 8.27°) y heredaba un eje de `bone_5_71` en vez de excluirse.
  Verificado y reproducido directamente antes de tocar nada:
  `chain_bone_names(limb, hierarchy)[-1] not in compute_hinge_axes(...)`
  era `False` para `chain_root=31`, `chain_root=33` (cow) y ambas patas
  de biped — solo bat coincidía con el criterio correcto por casualidad
  (su pivote SÍ cuelga literalmente de la raíz).

  **Impacto verificado (fuera de este entorno)**: con un CCD restringido
  a los ejes calculados, sin ningún grado de libertad de "bola" en el
  pivote de cadera, la convergencia se rompía para varias fases reales
  del ciclo de marcha (dirección de zancada real de
  `detect_stride_direction`, amplitudes de `safe_stride_amplitude_pct`):
  `chain_root=31` fallaba en **14 de 24 fases**, `chain_root=33` en
  **3 de 24** — **0 fallos tras el fix**, verificado independientemente.
  Consistente con lo esperable: sin poder rotar libremente en la
  cadera, CCD pierde precisamente el grado de libertad que más alcance
  aporta a toda la pata.

  **El fix**: el pivote más proximal de una pata se identifica por
  DEFINICIÓN — es `chain_bone_names(limb, hierarchy)[-1]` (el hueso que
  termina en `limb.chain_root`, ver `limb_classification.LimbChain`),
  no por la profundidad de su propio abuelo topológico. Nueva
  condición: excluir si `bone_name == bone_names[-1]` **O**
  `grandparent_node is None` (esta segunda condición se mantiene, sin
  coste, por si algún modelo futuro presenta un caso intermedio que la
  primera no cubriera — en los 3 samples actuales nunca aporta una
  exclusión que la primera no cubra ya).

  **Aprendizaje explícito, documentado en el propio docstring de
  `compute_hinge_axes`**: los tests originales
  (`test_hip_shoulder_pivot_excluded`) solo comprobaban que la función
  SE COMPORTABA como decía su propio criterio (`GP is None` →
  excluido) — no comprobaban que ese criterio en sí fuera correcto para
  TODAS las topologías de pata presentes en los samples. Un test que
  verifica fielmente una regla de diseño equivocada pasa igual de verde
  que uno que verifica una regla correcta. La propiedad general que de
  verdad hacía falta (`chain_bone_names(...)[-1]` nunca en el resultado,
  sin excepciones, para CUALQUIER pata) se añadió DESPUÉS del fix, como
  `test_pivot_exclusion_matches_chain_root_bone` — es el test que
  habría cazado esto antes de llegar a un prototipo de integración.

  **Ajustes en tests existentes**:
  - `test_hip_shoulder_pivot_excluded`: antes solo cubría cow (patas
    delanteras) y bat con nombres hardcodeados; ahora es genérico y
    parametrizado por los 3 modelos, derivando el pivote de cada pata
    de `chain_bone_names(...)[-1]` en vez de conocerlo de memoria.
  - `test_degenerate_joints_inherit_from_neighbor`: `bone_32_5` ya no
    se espera que herede (se excluye, es el pivote de `chain_root=5`)
    — filtrado explícitamente antes de la detección de huesos
    degenerados; los que sí heredan quedan solo `bone_192_240` y
    `bone_141_174`.
  - `_COW_WELL_DEFINED_BONES` (dos tests que la usan): `bone_4_31`
    (25.1°, usado en 2 tests como "hueso bien definido") es ahora el
    pivote de `chain_root=31` y ya no tiene eje calculado — sustituido
    por `bone_12_34` de `chain_root=33` (95.2°, igual de bien definido).

  **`backend/tests/test_joint_limits.py`**: 21 tests (antes 17) — el
  test de exclusión ampliado a los 3 modelos (+1 combinación) y el
  nuevo `test_pivot_exclusion_matches_chain_root_bone` (+3, uno por
  modelo).

  **Verificación:** `pytest backend/tests/` completo → **98 passed**, 0
  failed (94 de antes + 4 nuevos/ampliados).

  Bug de exclusión de pivote corregido y verificado en los 3 modelos.
  Sigue pendiente del Módulo 3: APLICAR el límite de ángulo de verdad
  dentro de `solve_ik_ccd` (ahora con el criterio de exclusión ya
  correcto), resolución del signo de `stride_direction`, y la pose de
  "asombro".

- **[Módulo 3 — restricción de eje de bisagra dentro de `solve_ik_ccd`]
  2026-08-21** — `solve_ik_ccd` acepta ahora un parámetro opcional
  `hinge_axes_local: dict[str, np.ndarray] | None = None` (resultado de
  `joint_limits.hinge_axes_in_local_frame`): si un hueso de la cadena
  aparece en ese dict, su rotación en cada sub-paso de CCD se restringe
  a girar SOLO alrededor de su eje de bisagra (1 grado de libertad) en
  vez de la rotación libre de 3 grados de libertad de antes. El pivote
  de cadera/hombro (excluido de `compute_hinge_axes` por diseño, ver
  checkpoint de corrección anterior) sigue rotando libre siempre. Con
  `hinge_axes_local=None` (el default), el comportamiento es EXACTAMENTE
  el de antes — verificado explícitamente, no solo asumido por el
  default.

  **Alcance deliberado**: esta tarea SOLO restringe el EJE de rotación.
  NO incluye un límite de ÁNGULO (rango de flexión/extensión dentro de
  esa bisagra) — decisión consciente de no mezclar ambas cosas en el
  mismo cambio, queda pendiente para una tarea posterior.

  **Cálculo restringido, por hueso con eje conocido**: (1)
  `current_axis = G_padre_rotación @ hinge_axes_local[bone_name]`,
  normalizado — el eje de mundo válido EN ESE MOMENTO, co-rota con el
  padre (exactamente la propiedad verificada en el checkpoint de
  `hinge_axes_in_local_frame`). (2) `to_effector`/`to_target` se
  proyectan sobre el plano perpendicular a `current_axis` antes de
  normalizarlos — si alguna proyección es casi nula (los vectores
  pivote→pie/objetivo caen casi paralelos al propio eje de bisagra, sin
  componente de flexión que resolver desde ese pivote), se salta el
  hueso esta pasada. (3) Ángulo CON SIGNO alrededor de `current_axis`
  vía `arctan2(sin, cos)` en vez del `arccos` sin signo del camino
  libre — una bisagra necesita saber en qué SENTIDO girar sobre su
  único eje. El resto del sub-paso (composición de cuaterniones,
  actualización del dict, recálculo de `effector`/`globals_`) es
  idéntico para ambos caminos.

  **Verificado exactamente como se especificó, sin fallos**: 0 fallos
  en las 8 patas de los 3 modelos, 24 fases del ciclo cada una
  (dirección de zancada real de `detect_stride_direction`, amplitudes
  de `safe_stride_amplitude_pct`) — coincide con la verificación
  independiente hecha antes de esta tarea (fuera de este entorno).
  Iteraciones máximas observadas con restricción activa: cow
  `chain_root=3` 738 (vs 724 sin restringir, mismo orden de magnitud),
  bat `chain_root=17` 243 (vs 180 sin restringir) — algo más lento en
  algunos casos al perder grados de libertad, pero dentro del
  presupuesto de `DEFAULT_MAX_ITERATIONS` (1000) con margen.

  **Verificación directa de la restricción** (`test_constrained_rotation_axis_matches_hinge`,
  2 huesos de cow): fuerza un objetivo alcanzable rotando UN hueso
  concreto 25° sobre su propio eje de bisagra (mundo, bind pose),
  resuelve con `max_iterations=1`, extrae la rotación LOCAL delta
  aplicada (`new_local · conj(old_local)`) y confirma que su eje es
  paralelo/antiparalelo (coseno ≈ ±1.0) al eje local esperado — no
  cualquier otro eje.

  **Verificación visual** (`backend/scripts/_plot_constrained_pose_debug.py`,
  nuevo, matplotlib sin Blender): silueta COMPLETA de cada pata
  (todas las articulaciones, no solo el pie) en 5 fases del ciclo, con
  y sin restricción de bisagra, superpuestas (vista lateral X-Y).
  Comprobado a ojo sobre los 3 modelos
  (`samples/_debug/{modelo}_constrained_vs_unconstrained.png`): en los
  3 modelos las siluetas restringida y sin restringir se superponen muy
  de cerca en las 4 patas de cow, las 2 de biped (algo más de dispersión
  visual en el racimo de dedos del pie, denso pero no descabellado) y
  las 2 de bat — ningún doblez de rodilla hacia el lado contrario ni
  trayectoria descabellada en ningún caso.

  **`backend/tests/test_ik_solver.py`** ampliado con 8 tests nuevos (14
  en total, antes 6; los 6 originales siguen pasando SIN modificarlos,
  la prueba de que el default preserva compatibilidad):
  `test_unconstrained_behavior_unchanged` (resultados IDÉNTICOS bit a
  bit entre no pasar el parámetro y pasar `hinge_axes_local=None`
  explícito, 3 modelos); `test_hinge_constrained_converges_across_full_cycle`
  (8 patas × 24 fases, cero fallos, 3 modelos); y
  `test_constrained_rotation_axis_matches_hinge` (2 huesos de cow, la
  verificación directa de la restricción).

  **Verificación:** `pytest backend/tests/` completo → **106 passed**,
  0 failed (98 de antes + 8 nuevos).

  Restricción de eje de bisagra aplicada y verificada dentro de
  `solve_ik_ccd`. Todavía pendiente del Módulo 3: límite de ÁNGULO
  (rango de flexión/extensión) dentro de cada bisagra, resolución del
  signo de `stride_direction`, y la pose de "asombro".

- **[Módulo 3 — límite de ÁNGULO dentro de cada bisagra] 2026-08-21** —
  `solve_ik_ccd` acepta ahora `hinge_max_angle_deg: float =
  DEFAULT_HINGE_MAX_ANGLE_DEG` (90.0): recorta el ángulo total
  acumulado (respecto a bind pose) al que cada bisagra con eje conocido
  (`hinge_axes_local`) puede llegar, dentro de `[-hinge_max_angle_deg,
  +hinge_max_angle_deg]` — sigue restringiendo el EJE (tarea anterior) y
  AHORA también el RANGO. El pivote de cadera/hombro (excluido de
  `compute_hinge_axes` por diseño) sigue rotando libre siempre, sin
  tope. Con `hinge_axes_local=None` (default), sin cambio de
  comportamiento — no aplica, ni siquiera se evalúa.

  **Hallazgo que motivó esta tarea, verificado antes de escribir nada**
  (medido el rango de ángulo con signo que cada bisagra recorre en un
  ciclo completo, en las 8 patas de los 3 modelos, con la restricción de
  EJE ya activa pero SIN ningún tope de ángulo): varios huesos de DEDOS
  giran muy por encima de lo anatómicamente razonable durante un ciclo
  de marcha normal — `bone_28_13` en cow llega a **226.2°** (no 350°
  como sugería la instrucción de la tarea; el hallazgo original medía
  sin la restricción de EJE activa, con eje SÍ restringido pero sin
  tope de ángulo el máximo real medido es 226.2° — de todas formas muy
  por encima de cualquier rango anatómico razonable, el número exacto
  cambia pero la conclusión no), varios huesos de biped por encima de
  200° (`bone_21_102` y otros, mencionados en el enunciado, no
  re-verificados exactamente en esta tarea porque el test de "dientes
  reales" se centró en cow por ser el caso más extremo y mejor
  caracterizado). Invisible en la verificación visual de la tarea
  anterior porque son huesos pequeños cerca de la punta del pie, cuya
  rotación apenas desplaza la silueta general de la pata.

  **Por qué se descartó calibrar el tope "a partir de lo que CCD ya
  necesita, más margen"** (el enfoque obvio, análogo a
  `DEFAULT_MAX_ITERATIONS` o `degenerate_angle_threshold_deg`): para los
  huesos que más lo necesitan (los dedos), ese comportamiento observado
  YA ES el problema — calibrar el tope a partir de él lo validaría en
  vez de arreglarlo. Se necesitaba un valor FIJO ajeno al comportamiento
  observado, no derivado de él.

  **Diseño elegido: tope fijo de ±90°, igual para TODAS las bisagras**
  (no calibrado por hueso, a propósito — deliberadamente simple): 2-3x
  el rango que ya usan de forma razonable los huesos que se comportan
  bien (`bone_31_10`: ~30°, `bone_3_29`: ~35°, `bone_17_22` de bat:
  ~36°), y muy por debajo de los giros de 200°+ que corta de raíz.

  **Nuevo helper público, `joint_limits.signed_hinge_angle_deg(skin_data,
  node_index, local_rotation_quat, hinge_axis_local)`**: ángulo con
  signo (grados) de una rotación local respecto a la de BIND POSE de ese
  nodo, medido alrededor de `hinge_axis_local`. Se apoya en una
  propiedad exacta: cada incremento LOCAL que `solve_ik_ccd` aplica a un
  hueso restringido a eje es, por construcción, una rotación PURA
  alrededor de ese eje fijo (co-rotando con el padre), así que el delta
  ACUMULADO (`local_rotation_quat · conj(bind_rotation)`) también lo es,
  y su ángulo con signo se extrae de forma exacta y estable con
  `2·arctan2(dot(delta_xyz, eje), delta_w)` — deliberadamente NO
  `arccos` (pierde el signo, impreciso cerca de 180°).

  **Import circular evitado con import local**: `joint_limits.py`
  importa de `ik_solver.py` (`chain_bone_names`, `name_to_node_index`)
  a nivel de módulo; `ik_solver.solve_ik_ccd` necesita
  `signed_hinge_angle_deg` de `joint_limits.py` — un `import` a nivel de
  módulo en `ik_solver.py` habría creado un ciclo. Se resolvió con un
  `import` LOCAL dentro del cuerpo de `solve_ik_ccd` (se ejecuta solo al
  llamar la función, momento en el que ambos módulos ya están
  completamente cargados, sin importar el orden de import inicial) —
  patrón estándar para este caso, no una solución improvisada.

  **Algoritmo del recorte, por hueso con eje conocido, ANTES de aplicar
  la rotación de esta pasada**: (1) `current_total_deg =
  signed_hinge_angle_deg(...)` del estado actual; (2) `new_total_deg =
  current_total_deg + grados(signed_angle)` (lo que CCD querría
  alcanzar sumando el incremento de esta pasada); (3)
  `new_total_clamped_deg = clip(new_total_deg, -90, 90)`; (4)
  `actual_delta_rad = radianes(new_total_clamped_deg -
  current_total_deg)` — el incremento AJUSTADO tras el recorte, el único
  que se aplica de verdad. Si el hueso ya está en el límite y CCD
  querría seguir empujando en la misma dirección, `actual_delta_rad` es
  ~0 y se salta el hueso esta pasada (mismo criterio que ya se usaba
  para ángulos sin restringir ~0).

  **`backend/tests/test_ik_solver.py`** ampliado con 5 tests nuevos (19
  en total, antes 14; los 14 originales siguen pasando sin modificarlos
  — el default preserva compatibilidad):

  1. `test_hinge_angle_cap_still_converges_across_full_cycle`
     (parametrizado por los 3 modelos, 8 patas × 24 fases): con
     `hinge_max_angle_deg=90.0`, **0 fallos**, peor caso de iteraciones
     por pata:

     | pata | max iteraciones (con tope de ángulo) |
     |---|---|
     | cow chain_root=31 | 166 |
     | cow chain_root=33 | 87 |
     | cow chain_root=27 | 321 |
     | cow chain_root=3 | **738** ← peor caso, dentro del presupuesto de 1000 |
     | biped chain_root=5 | 7 |
     | biped chain_root=88 | 7 |
     | bat chain_root=17 | 243 |
     | bat chain_root=15 | 0 |

  2. `test_hinge_angle_cap_has_real_teeth` (cow, `chain_root=27`,
     `bone_28_13`): resuelve el mismo ciclo (24 fases, amplitud segura)
     dos veces, con `hinge_max_angle_deg=1000.0` (sin tope efectivo) y
     con `90.0`, midiendo `signed_hinge_angle_deg` de `bone_28_13` en
     cada fase con ambos resultados. Números reales medidos: SIN tope
     efectivo, ángulo máximo `|226.2|°` (secuencia completa por fase:
     -22.2, 30.4, 55.4, 74.1, 88.7, 99.1, 104.7, **226.2**, -124.3,
     -111.1, -94.0, -72.2, -38.8, -38.4, -37.5, -34.8, -1.3, 1.8, 0.0,
     -4.2, -11.5, -19.4, -21.6, -22.1) — confirma el hallazgo, no lo da
     por hecho. CON tope de 90°, ángulo máximo exactamente `90.0°`
     (secuencia: mismos valores hasta que se satura en ±90 en las fases
     donde el sin-tope se disparaba: ..., 88.6, 90.0, 90.0, 90.0, -90.0,
     -90.0, -90.0, -72.2, ...) — nunca excede `90.0 + 1.0°` (margen de
     tolerancia numérica del test). Prueba de que el tope tiene dientes
     de verdad, no un parámetro ignorado en silencio.

  3. `test_hinge_angle_cap_blocks_out_of_range_target` (cow,
     `chain_root=31`): objetivo con `stride_amplitude_pct=3.0` (300%,
     muy por encima de la amplitud segura, a propósito) en `phase=0.0`
     — con `hinge_max_angle_deg=90.0` NO converge
     (`result.converged is False`, error final medido 5.487, 1000/1000
     iteraciones agotadas) en vez de exceder el tope para alcanzar el
     objetivo de todos modos. Confirma que el límite de ángulo tiene
     PRIORIDAD sobre alcanzar el objetivo cuando entran en conflicto.

  **Verificación visual** (`backend/scripts/_plot_angle_capped_pose_debug.py`,
  nuevo — extiende el patrón de `_plot_constrained_pose_debug.py` sin
  tocarlo, añadiendo una TERCERA silueta superpuesta: sin restringir
  (punteado), solo-eje (discontinuo, `hinge_max_angle_deg=1000.0`) y
  eje+ángulo≤90° (sólido)): comprobado a ojo sobre los 3 modelos
  (`samples/_debug/{modelo}_angle_capped_vs_axis_only.png`) — en los 3
  modelos las 3 siluetas se superponen de cerca en la mayoría de fases,
  con la variante eje+ángulo divergiendo visiblemente de las otras dos
  solo en las fases donde el tope satura de verdad (esperado, es
  precisamente lo que el tope está diseñado para hacer) — ningún doblez
  descabellado ni trayectoria sin sentido en ninguna pata de los 3
  modelos.

  **Verificación:** `pytest backend/tests/` completo → **111 passed**,
  0 failed (106 de antes + 5 nuevos).

  Límite de ÁNGULO dentro de cada bisagra aplicado y verificado. Con
  esto, el sub-tema de límites articulares (eje + ángulo) del Módulo 3
  queda cerrado. Todavía pendiente del Módulo 3: resolución del signo
  de `stride_direction` (qué extremo es "adelante"), y la pose de
  "asombro".

- **[Módulo 3 — signo de `stride_direction`, decisión de no
  perseguirlo] 2026-08-21** — Tarea de SOLO DOCUMENTACIÓN, sin cambios
  de código: investigación de si merece la pena un clasificador
  columna-vs-extremidad para resolver el signo de `stride_direction`
  (qué extremo de la línea detectada por `detect_stride_direction` es
  "adelante", hacia la cabeza, y cuál "atrás", hacia la cola) — decisión
  de NO perseguirlo, documentada aquí para que no se repita la
  investigación en el futuro sin releer esto primero.

  **Hallazgo 1 (verificado con datos reales, los 3 modelos): la
  información SÍ existe en cuadrúpedos/alados, pero NO en biped por un
  límite duro de la pose, no del algoritmo.** Se probó un heurístico
  simple: la "columna" (nodo no-pata topológicamente más lejano de la
  raíz del esqueleto, excluyendo cualquier nodo perteneciente a una
  `LimbChain` — es decir, cabeza/cuello/cola en cow y bat, y
  cabeza/cuello en biped) comparada contra `stride_direction` vía
  coseno del vector raíz→columna:

  | modelo | coseno(columna, stride_direction) | interpretación |
  |---|---|---|
  | cow | -0.975 | casi perfectamente alineado (antiparalelo) |
  | bat | -0.909 | casi perfectamente alineado (antiparalelo) |
  | biped | -0.081 | prácticamente SIN relación |

  Para biped se comprobó también contra el eje VERTICAL (Y): coseno
  **-0.991** — la columna de un biped de pie apunta hacia ARRIBA
  (cabeza sobre las caderas), no hacia adelante ni atrás en ningún
  sentido horizontal. Esto es un límite DURO de la información
  disponible en una pose estática de pie (T-pose o similar): ningún
  clasificador, por sofisticado que sea, puede extraer de la geometría
  del esqueleto en bind pose una señal horizontal de "adelante" que
  simplemente no está presente en el dato de entrada para un biped
  erguido — no es una limitación de heurístico, es una limitación de la
  pose misma.

  **Hallazgo 2 (verificado con datos reales, bat): incluso en el
  subconjunto donde la señal SÍ existe, el heurístico de ramificación es
  frágil ante proporciones distintas.** El diseño de "nodo no-pata más
  lejano de la raíz" depende implícitamente de que la columna/cola sea
  la rama topológicamente más larga entre los nodos no clasificados como
  pata. En bat, las alas (que `classify_support_limbs` NO clasifica
  como patas de apoyo — están demasiado altas en la T-pose, ver
  checkpoint de clasificación de patas — y quedan mezcladas con la
  columna en el conjunto "no-pata") están a solo **1 salto topológico
  menos** que el verdadero extremo columna/cola. El heurístico funcionó
  en este caso concreto (coseno -0.909, arriba) pero por poco margen: un
  modelo con alas más largas o una cola más corta, en proporción,
  invertiría fácilmente cuál rama gana como "la más lejana" — el diseño
  no es robusto a variación de proporciones entre criaturas, solo
  funciona porque en bat concretamente la cola gana por un margen
  topológico pequeño.

  **Decisión: no se persigue.** Construir un clasificador
  columna-vs-extremidad sería una pieza nueva del tamaño de
  `limb_classification.classify_support_limbs` (nuevo módulo, nuevos
  tests, nueva inspección visual) para un heurístico que, en el mejor
  caso, solo cubre cuerpos horizontales tipo cuadrúpedo/alado, de forma
  frágil ante proporciones (Hallazgo 2) — y que en el caso de biped
  (un tercio de los samples disponibles) no puede funcionar NUNCA, sin
  importar cuánto se refine el heurístico, porque la información
  necesaria no existe en la pose de entrada (Hallazgo 1). El coste no
  se justifica frente al beneficio.

  El signo de `stride_direction` queda sin resolver como **límite
  ACEPTADO Y PERMANENTE de este enfoque geométrico**, no como tarea
  pendiente de una fase posterior — no debe reaparecer en un futuro
  "Estado actual" como pendiente del Módulo 3. Si en algún momento
  posterior hiciera falta de verdad resolver el signo (p. ej. al añadir
  traslación de la raíz por el mundo en un módulo futuro, donde la
  dirección de avance real del personaje sí importa), la vía correcta
  probablemente sea una señal DISTINTA a la geometría del esqueleto en
  bind pose — un override manual del usuario (p. ej. "esta dirección es
  adelante"), no un heurístico geométrico más elaborado sobre el mismo
  dato de entrada que ya ha demostrado no contener la información
  necesaria para biped.

  Sin cambios de código en esta tarea (ninguna investigación tocó
  `.py`, solo lectura/inspección con scripts temporales fuera del
  repo). `pytest backend/tests/` sigue en el mismo estado que el
  checkpoint anterior: **111 passed**, 0 failed.

- **[Módulo 3 — pose de "asombro" y CIERRE del Módulo 3] 2026-08-21** —
  Última pieza pendiente del módulo: `gait_cycle.surprise_pose_phase_offsets(limbs)`,
  una función pequeña (una línea de cuerpo: `{limb.chain_root: 0.0 for
  limb in limbs}`) que reutiliza el 100% de `solve_gait_cycle_pose` ya
  verificado — el ÚNICO cambio respecto a la marcha normal es el
  `phase_offsets` que se le pasa.

  **Por qué "todas las patas en fase" da una pose de sobresalto**: en
  una marcha real en equilibrio (o en `assign_limb_phase_offsets`), el
  reparto alterna/diagonaliza precisamente para que nunca todas las
  patas estén en el aire a la vez — un cuerpo necesita siempre alguna
  pata de apoyo. Poner TODAS las patas en la MISMA fase rompe esa
  restricción a propósito: en `global_phase=0.25` todas se extienden
  hacia arriba/adelante simultáneamente, una postura físicamente
  imposible de sostener en una marcha real en equilibrio, pero que se
  lee como un sobresalto o salto congelado en el aire — no como "otro
  instante cualquiera de caminar". Generaliza a cualquier nº de patas
  sin ninguna heurística nueva (a diferencia de
  `assign_limb_phase_offsets`, que necesita ramificar explícitamente
  entre 2 y 4 patas con `NotImplementedError` para el resto) y no
  depende del signo sin resolver de `stride_direction` (todas las patas
  se mueven hacia el MISMO lado relativo a la vez, da igual cuál extremo
  sea "adelante" de verdad).

  **`global_phase=0.25` confirmado como pico de elevación en los 3
  modelos, no asumido**: `max(0, sin(2π·phase))` de `foot_target_at_phase`
  tiene su único máximo exacto en `phase=0.25` — una propiedad de la
  fórmula, no del modelo — pero se confirmó igualmente resolviendo la
  pose de asombro completa en 40 fases para los 3 modelos antes de
  escribir el test: el pico de altura del pie de CADA pata cae
  exactamente en `phase=0.25` (`bat chain_root=15`, la pata de un solo
  hueso con `reach=0` ya documentada en checkpoints anteriores, es la
  única excepción — se queda plana en TODAS las fases, esperado).

  **`backend/tests/test_gait_cycle.py`** ampliado con 2 tests nuevos (45
  en total, antes 39): `test_surprise_pose_all_legs_converge`
  (parametrizado por los 3 modelos, mismo patrón que
  `test_all_limbs_converge_across_full_cycle` pero con
  `surprise_pose_phase_offsets` — 0 fallos en las 8 patas) y
  `test_surprise_pose_offsets_are_all_zero` (trivial pero explícito:
  confirma 0.0 para cada `chain_root`, los 3 modelos).

  **Verificación visual** (`backend/scripts/_plot_surprise_pose_debug.py`,
  nuevo — mismo patrón de estilo que los scripts de depuración
  anteriores, silueta lateral completa de cada pata): compara, en la
  MISMA `global_phase=0.25`, la pose de asombro (sólido) contra la
  marcha normal alternada/diagonal (discontinuo). Comprobado a ojo sobre
  los 3 modelos (`samples/_debug/{modelo}_surprise_pose.png`):

  - **cow**: el más claro de los 3 — en la marcha normal (discontinuo)
    dos patas están arriba (~Y 3.0-3.6, grupo de fase que coincide con
    asombro en esta fase) y dos abajo (~Y 0.3-0.5, el otro grupo
    diagonal, en stance); en la pose de asombro (sólido) las 4 patas
    quedan arriba, sin ninguna cerca del suelo — el contraste "todas
    arriba a la vez" contra "dos arriba, dos abajo" de la marcha normal
    es inmediatamente reconocible como sobresalto.
  - **biped**: `chain_root=5` (offset 0.0 en AMBOS repartos, por ser la
    pata que `assign_limb_phase_offsets` ordena primera — sus dos líneas
    coinciden, esperado) sirve de referencia; `chain_root=88` muestra la
    diferencia real: discontinuo cerca de Y=0 (stance, pie apoyado) vs
    sólido subiendo hasta el pico (~Y 0.92) — visible con claridad.
  - **bat**: el contraste MENOS dramático de los 3 (medido, no solo
    impresión visual): altura del pie de `chain_root=17` en
    `global_phase=0.25` es 0.564 con offsets normales (fase local 0.75,
    stance) vs 0.618 con offsets de asombro (fase local 0.25, pico) —
    una diferencia de solo 0.055 sobre una longitud de pata de ~1.15,
    frente a la diferencia de ~2.5-3.0 de cow. Explicable por la propia
    geometría/proporciones de esta pata concreta de bat
    (`lift_height_pct · alcance` da un desplazamiento vertical modesto
    en términos absolutos aquí), no un bug — `chain_root=15` (pata de un
    solo hueso, `reach≈0`) se mantiene plana en ambos casos, como se
    esperaba. El efecto sigue estando en la dirección correcta (más alto
    en asombro que en marcha normal en esa fase), solo que menos
    pronunciado que en cow/biped.

  **Reconciliación del roadmap (Módulo 3, sección "Roadmap por
  módulos")**: el criterio de verificación mencionaba
  `pytest backend/tests/test_locomotion.py`, un archivo que nunca
  existió — el módulo terminó organizado en 4 archivos temáticos más
  pequeños en vez de uno solo (`test_limb_classification.py`,
  `test_ik_solver.py`, `test_joint_limits.py`, `test_gait_cycle.py`),
  decisión tomada sobre la marcha en checkpoints anteriores y nunca
  revertida porque no había ninguna ganancia real en reorganizar tests
  ya verificados solo para que el nombre coincidiera con el roadmap
  original. Se actualizó el TEXTO del roadmap para reflejar la
  organización real, sin tocar ni renombrar ningún test (mucho más
  arriesgado sin beneficio).

  **Confirmación explícita del criterio "los pies/patas no atraviesan
  el plano del suelo"** (pedido antes de cerrar el módulo, no asumido):
  cubierto por `gait_cycle.verify_never_below_ground` (auto-chequeo
  obligatorio sobre `foot_target_at_phase`, muestrea 1000 fases y
  confirma que la Y del objetivo nunca baja de la Y de bind pose del
  pie — ejecutado como test, `test_never_below_ground`, para los 3
  modelos) a nivel del OBJETIVO que se le pide al IK. La posición REAL
  resuelta por `solve_ik_ccd` (que podría en teoría no coincidir
  exactamente con el objetivo) se confirma aparte, dentro de
  `_CONVERGENCE_TOLERANCE`/`tolerance` (1e-4), en los tests de
  convergencia de `test_ik_solver.py` y `test_gait_cycle.py` — entre
  ambos, el criterio queda cubierto de extremo a extremo (objetivo
  nunca bajo el suelo + posición real siempre a ≤1e-4 del objetivo),
  no solo a nivel de la fórmula que genera el objetivo.

  **Verificación:** `pytest backend/tests/` completo → **117 passed**,
  0 failed (111 de antes + 6 nuevos: `test_surprise_pose_all_legs_converge`
  y `test_surprise_pose_offsets_are_all_zero`, cada uno parametrizado
  por los 3 modelos).

  **MÓDULO 3 — CIERRE FORMAL.** Compuesto por: clasificación de patas de
  apoyo, IK CCD por pata, trayectoria de ciclo con amplitud segura,
  dirección de zancada automática, reparto de fase entre patas, pose de
  marcha con varias patas a la vez, límites articulares (eje + ángulo de
  cada bisagra) dentro de `solve_ik_ccd`, y ahora la pose de "asombro".
  El signo de `stride_direction` queda como límite aceptado y permanente
  del enfoque geométrico (no pendiente — checkpoint 2026-08-21 dedicado).
  Sin comando de verificación único (`test_locomotion.py` nunca existió,
  ver reconciliación de roadmap arriba); el cierre se apoya en
  `pytest backend/tests/` completo (117 passed) repartido en los 4
  archivos temáticos ya mencionados.

  Empieza Módulo 4 — micro-movimientos: respiración, parpadeo, ruido de
  baja frecuencia en dedos/cola/orejas. Sin empezar todavía, espera
  instrucción atómica del director técnico-creativo.

- **[Módulo 4 — respiración] 2026-08-21** — Primera pieza de Módulo 4:
  `backend/app/micro_movements.py` (nuevo módulo),
  `breathing_local_rotation(t, side_axis, breaths_per_minute=15.0,
  max_amplitude_deg=1.5)` — cuaternión de rotación sinusoidal MUY
  pequeña, pensado para componerse con la rotación LOCAL de bind pose de
  la RAÍZ del esqueleto (`skin_data.root_node_index`).

  **Por qué la raíz entera y no un hueso de "pecho" específico**: se
  descartó explícitamente (decisión ya tomada con el director, no
  reabierta) por el mismo motivo ya documentado para el signo de
  `stride_direction` — heurísticos de ramificación son frágiles.
  Comprobado también aquí antes de descartarlo: seguir "la rama con más
  descendientes no-pata" desde la raíz se desvía hacia brazos/cabeza
  (alta ramificación de dedos) en vez de seguir la columna real. La
  respiración es, en cambio, una aproximación deliberada de "balanceo
  sutil de todo el torso" rotando la raíz entera — documentada como tal,
  no como animación anatómica precisa de caja torácica.

  **Por qué `skin_data.root_node_index` y no el nodo raíz TOPOLÓGICO del
  árbol de esqueleto (`build_skeleton_tree`)**: son nodos DISTINTOS.
  `skin_data.root_node_index` es el nodo "SkeletonArmature" del glTF
  exportado — el ancestro común de todos los huesos (y de los nodos de
  malla, "Cow"/"Eyes"/etc., que cuelgan como hermanos de los huesos de
  nivel superior) — mismo nodo que ya usa
  `test_hinge_axis_co_rotates_with_ancestor_perturbation`
  (`test_joint_limits.py`, Módulo 3) para simular una perturbación del
  "ancestro común de toda la pata". El nodo raíz topológico del árbol de
  esqueleto (p. ej. nodo `2` en cow), en cambio, no es un nodo del glTF
  en sí — es solo la CABEZA compartida de varios huesos "bone_2_X" que
  cuelgan directamente de `root_node_index` (ver checkpoint del Módulo 3
  sobre exclusión del pivote de cadera: cada extremidad tiene su propio
  hueso "bone_2_X", no hay un único hueso que "sea" el nodo topológico
  raíz). Rotar `root_node_index` mueve el marco de referencia de TODOS
  ellos a la vez, que es justo el efecto de "balanceo de todo el cuerpo"
  buscado.

  **Verificación de la calibración de `max_amplitude_deg=1.5`, con
  datos reales de los 3 modelos (no dada por hecho de memoria)**:
  desplazamiento aproximado en la posición del pie ≈
  `radians(max_amplitude_deg) · (dist_raíz_a_chain_root +
  max_chain_bone_length)` (usa `gait_cycle.max_chain_bone_length`, ya
  verificado en Módulo 3), comparado contra la longitud de cadena de esa
  misma pata:

  | pata | dist_raíz→chain_root | max_chain_length | desplazamiento | % de la longitud de cadena |
  |---|---|---|---|---|
  | cow chain_root=31 | 5.031 | 3.768 | 0.230 | 6.11% |
  | cow chain_root=33 | 5.031 | 4.663 | 0.254 | 5.44% |
  | cow chain_root=27 | 0.556 | 3.992 | 0.119 | 2.98% |
  | cow chain_root=3 | 0.837 | 3.940 | 0.125 | 3.17% |
  | biped chain_root=5 | 0.746 | 1.217 | 0.051 | 4.22% |
  | biped chain_root=88 | 0.594 | 1.394 | 0.052 | 3.73% |
  | bat chain_root=17 | 1.270 | 1.635 | 0.076 | 4.65% |
  | bat chain_root=15 | 1.584 | 1.584 | 0.083 | 5.24% |

  Rango real 2.98%-6.11% en las 8 patas — coincide con lo esperado
  (5-8%, algo conservador incluso) y queda claramente por debajo de las
  amplitudes de zancada normales (30%+ de la misma referencia, ver
  `gait_cycle.foot_target_at_phase`). `test_breathing_displacement_is_subtle`
  usa un margen del 15% (generoso sobre el 6.11% máximo observado) para
  que una regresión real en un modelo futuro falle en vez de pasar en
  silencio.

  **`breaths_per_minute=15.0`**: valor único, NO calibrado por especie
  — documentado como simplificación deliberada, ya que el proyecto no
  tiene ninguna fuente de datos biológicos por especie; inventar un
  número distinto por modelo sería fingir precisión zoológica sin base
  real. Un valor único razonable de "reposo tranquilo" es más honesto.

  **`backend/tests/test_micro_movements.py`** (nuevo archivo, 11
  tests): `test_breathing_amplitude_never_exceeds_max` (≥50 valores de
  `t` en 3 periodos completos, ángulo extraído vía `2·arccos(|w|)`
  nunca excede `max_amplitude_deg`); `test_breathing_is_periodic`
  (6 valores de `t`, `breathing_local_rotation(t)` y
  `breathing_local_rotation(t + periodo)` dan el mismo cuaternión o su
  negado); `test_breathing_identity_at_t_zero` (cuaternión exacto
  `[0,0,0,1]` en `t=0`, tolerancia 1e-12); y
  `test_breathing_displacement_is_subtle` (parametrizado por los 3
  modelos, la tabla de arriba reproducida como test, no solo como
  checkpoint).

  **Limitación conocida y ACEPTADA de esta pieza (documentada, no
  resuelta aquí)**: esta función NO integra todavía con el ciclo de
  marcha activo. Combinar la rotación de la raíz con
  `solve_gait_cycle_pose` sin más podría deslizar ligeramente los pies
  durante la fase de "stance" (el objetivo de IK del pie no cambia, pero
  el origen de la cadena sí se mueve al rotar la raíz). Queda pendiente
  para una integración posterior — no bloquea seguir con el resto de
  Módulo 4 (parpadeo, ruido de baja frecuencia en dedos/cola/orejas),
  que no dependen de esto.

  **Verificación visual** (`backend/scripts/_plot_breathing_debug.py`,
  nuevo): aplica `breathing_local_rotation` a la rotación de bind pose
  de la raíz en 6 instantes repartidos en un periodo completo,
  recalcula posiciones de todos los huesos vía `compute_global_matrices`
  y dibuja la silueta completa superpuesta. Primer intento con vista
  cruda (X, Y) para cow dio un aspecto visualmente alarmante (patas y
  cuernos cruzados en forma de "X", con una silueta pareciendo
  "distorsionada" en el instante de mayor amplitud) — investigado ANTES
  de aceptarlo como problema: confirmado numéricamente que el
  desplazamiento máximo real entre bind pose y el instante más extremo
  es de solo **0.14** unidades (sobre un modelo de ~5 unidades de alto),
  y que la MISMA silueta en forma de "X" aparece renderizando SOLO bind
  pose sin ninguna respiración — es el aspecto NORMAL del esqueleto de
  cow proyectado en el plano (X, Y) crudo (X no es el eje principal de
  extensión corporal de cow), no una distorsión introducida por la
  tarea. Corregido cambiando la proyección a
  (`stride_direction`, Y) — mismo criterio ya usado en
  `_plot_surprise_pose_debug.py` — para una vista lateral legible.
  Comprobado a ojo sobre los 3 modelos
  (`samples/_debug/{modelo}_breathing.png`): en los 3, las 6 siluetas se
  superponen casi exactamente, con una variación gradual y apenas
  perceptible entre instantes — ningún salto brusco, ninguna pose
  descolocada, consistente con la calibración de arriba.

  **Verificación:** `pytest backend/tests/` completo → **128 passed**,
  0 failed (117 de antes + 11 nuevos de `test_micro_movements.py`).

  Respiración cerrada y verificada. Pendiente dentro de Módulo 4:
  integración con locomoción activa (evitar deslizamiento de pies,
  limitación conocida y aceptada de esta pieza, no resuelta aquí),
  parpadeo, y ruido de baja frecuencia en dedos/cola/orejas — sin
  empezar todavía, espera instrucción atómica.

- **[Módulo 4 — bloqueo de parpadeo] 2026-08-22** — Tarea de SOLO
  DOCUMENTACIÓN, sin cambios de código: verificación de por qué el
  parpadeo (párpado cerrándose) no es viable con los assets de prueba
  actuales, para dejarlo registrado como límite y no reabrir la
  investigación en el futuro sin releer esto primero.

  **Verificación propia (no aceptado de memoria de un resumen ajeno)**:

  1. Morph targets (blend shapes) en los 3 GLB de muestra — iterando
     `gltf.meshes[*].primitives[*].targets` con `pygltflib` directamente
     sobre `samples/{cow,biped,bat}_unrigged.glb`:

     | modelo | nº de meshes | targets por primitiva | total |
     |---|---|---|---|
     | cow | 1 | [0, 0, 0] | 0 |
     | biped | 3 | [0, 0, 0] | 0 |
     | bat | 2 | [0, 0, 0, 0, 0, 0] | 0 |

     **0 morph targets en los 3 modelos** — confirma exactamente el
     resultado ya obtenido de forma independiente.

  2. Tamaño de los 3 esqueletos vía `build_skeleton_tree` (mismo pipeline
     que el resto del proyecto): cow 28 nodos, biped 182 nodos (coincide
     exactamente con el nº final ya documentado en el checkpoint de
     cierre del Módulo 1), bat 30 nodos. Ningún módulo existente
     (`limb_classification.py` ni ningún otro) tiene mecanismo para
     identificar un "hueso de párpado" — búsqueda directa de
     `parpado`/`eyelid`/`blink`/`morph` en `backend/app/` sin resultados.
     Los esqueletos son producto de contracción de malla (Módulo 0/1),
     sin nombres semánticos de origen autoral que pudieran servir de
     atajo.

  **Decisión**: el parpadeo real necesita morph targets/blend shapes o
  un hueso de párpado dedicado — ninguno de los dos existe en los assets
  de prueba actuales, y ningún módulo de este proyecto produce ni
  consume morph targets hasta ahora. Es un **límite DURO de los datos de
  entrada disponibles** (mecanismo que no existe en el dato), de la
  misma naturaleza — aunque no la misma causa geométrica — que el límite
  ya documentado y aceptado del signo de `stride_direction` (checkpoint
  de cierre del Módulo 3): no es un algoritmo pendiente de mejorar, es
  que la pieza necesaria no está en la entrada.

  Retomar esto en el futuro necesitaría un **módulo de morph targets
  aparte**, completamente fuera del alcance actual de auto-rigging por
  huesos — no es "hacerlo mejor" con el enfoque actual, es "hacer otra
  cosa distinta" (generación/detección de blend shapes faciales, un
  problema de otra naturaleza que la esqueletización geométrica que usa
  todo el proyecto hasta ahora).

  El bloqueo de parpadeo queda como **límite documentado y aceptado**,
  no como pendiente activo — no debe reaparecer en un futuro "Estado
  actual" como tarea por hacer del Módulo 4.

  Sin cambios de código en esta tarea (verificación con `pygltflib` y
  `build_skeleton_tree` desde fuera de los tests, sin tocar ningún
  `.py` del repo). `pytest backend/tests/` sigue en el mismo estado que
  el checkpoint anterior: **128 passed**, 0 failed.
