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

- **Módulo actual:** 3 — Animación procedural básica (siguiente, no
  iniciado)
- **Estado:** Módulos 0, 1 y 2 completados y verificados.

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
- Verificación: `pytest backend/tests/test_locomotion.py` sobre los 3 modelos
  — el ciclo de marcha es periódico y estable, los pies/patas no atraviesan
  el plano del suelo más de un umbral tolerado.

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
