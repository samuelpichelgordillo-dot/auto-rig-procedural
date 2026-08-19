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

- **Módulo actual:** 2 — Skinning (en curso)
- **Estado:** Módulo 1 completado y verificado. Módulo 2: Armature real +
  auto-weight en bruto hechos; falta post-proceso de pesos + test de
  deformación antes de poder cerrarlo.

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
  Armature (`create_armature`, factorizada de `_render_armature_debug.py`
  para no duplicarla), parentear con auto-weight y exportar.

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
