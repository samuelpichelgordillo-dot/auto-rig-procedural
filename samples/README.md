# samples/

Coloca aquí modelos GLB de prueba (licencia libre / uso permitido para desarrollo):

- Al menos 1 cuadrúpedo (p.ej. un zorro, perro o similar).
- Al menos 1 bípedo (p.ej. una figura humanoide).
- Al menos 1 modelo "atípico" (topología no estándar: sin extremidades claras,
  múltiples apéndices, etc.) — usado para probar los límites de la
  esqueletización automática en el Módulo 1.

Fuentes recomendadas con licencias libres: Khronos glTF-Sample-Models
(CC0 / Apache 2.0), Sketchfab (filtrar por licencia CC0/CC-BY), Mixamo
(personajes riggeados, útiles como referencia).

No se versionan aquí modelos grandes por defecto — añade tu propio `.gitignore`
si el repo pasa a control de versiones y los archivos pesan demasiado.

## Modelos incluidos

### `cow_unrigged.glb` — cuadrúpedo, sin esqueleto

- **Origen:** pack "LowPoly Animated Animals" de Quaternius —
  https://quaternius.itch.io/lowpoly-animated-animals
- **Archivo original:** `Cow.fbx` del pack (conservado en
  `samples/_original/Cow.fbx` para trazabilidad).
- **Licencia:** CC0 1.0 Universal (dominio público), confirmada en la propia
  página del pack (enlaza a
  http://creativecommons.org/publicdomain/zero/1.0/). No requiere atribución,
  pero se cita aquí por buenas prácticas.
- **Autor:** Quaternius (https://quaternius.com).
- **Cómo se generó:** el original venía con armature (39 huesos) y 6
  animaciones (Death, Idle, Jump, Run, Walk, WalkSlow) — no válido tal cual
  para el Módulo 1, que necesita partir de malla sin esqueleto. Se despojó el
  rig con `backend/scripts/_strip_rig.py`:

  ```
  blender --background --python backend/scripts/_strip_rig.py -- \
      samples/_original/Cow.fbx samples/cow_unrigged.glb
  ```

  El script elimina animaciones, modifiers `ARMATURE`, vertex groups
  (pesos de skinning) y los objetos `ARMATURE` (incluyendo los widgets de
  pose_bone.custom_shape), reexportando solo malla + materiales.
- **Verificado con:** `python backend/scripts/inspect_glb.py samples/cow_unrigged.glb`
  → 1616 vértices, **Huesos existentes: 0**, 3 materiales, bounding box
  `min=(-1.1248, -5.3962, -0.0680)` `max=(1.1248, 3.7762, 5.0797)`.

### `biped_unrigged.glb` — bípedo, sin esqueleto

- **Origen:** pack "Universal Base Characters" de Quaternius —
  https://quaternius.itch.io/universal-base-characters
- **Archivo original:** `Superhero_Male_FullBody.gltf` + `.bin` (variante
  "Godot - UE" del pack, conservados en `samples/_original/` para
  trazabilidad; las texturas del pack no se copiaron — no hacen falta para
  probar detección de esqueleto, solo topología).
- **Licencia:** CC0 1.0 Universal (dominio público), confirmada en la página
  del pack (enlaza a http://creativecommons.org/publicdomain/zero/1.0/).
- **Autor:** Quaternius (https://quaternius.com).
- **Cómo se generó:** el original venía con 1 armature (65 huesos) y 4
  objetos MESH (`Eyebrows`, `Eyes`, `Icosphere` —widget de hueso—,
  `SuperHero_Male`, 7281 vértices). Se despojó el rig con
  `backend/scripts/_strip_rig.py`:

  ```
  blender --background --python backend/scripts/_strip_rig.py -- \
      "samples/_original/Superhero_Male_FullBody.gltf" samples/biped_unrigged.glb
  ```

  (El import produjo errores esperados de texturas ausentes —no se copiaron
  los `.png` del pack—, sin impacto en malla/armature; Blender exporta los
  materiales igualmente, solo sin imagen asociada.)
- **Verificado con:** `python backend/scripts/inspect_glb.py samples/biped_unrigged.glb`
  → 8483 vértices, **Huesos existentes: 0**, 3 materiales, bounding box
  `min=(-0.9294, -0.1280, -0.0095)` `max=(0.9294, 0.1635, 1.8101)` (altura
  ~1.81, proporciones humanas coherentes).

### `bat_unrigged.glb` — atípico (alas + patas), sin esqueleto

- **Origen:** pack "LowPoly Animated Monsters" de Quaternius —
  https://quaternius.itch.io/lowpoly-animated-monsters
- **Archivo original:** `Bat.fbx` del pack (conservado en
  `samples/_original/Bat.fbx` para trazabilidad).
- **Licencia:** CC0 1.0 Universal (dominio público), confirmada en la página
  del pack.
- **Autor:** Quaternius (https://quaternius.com).
- **Cómo se generó:** el original venía con **2 armatures** (`BatArmature`,
  28 huesos, con cadenas de ala `Wing1`–`Wing4` por lado más patas y cabeza;
  `EyeArmature`, 2 huesos) y 5 animaciones (Attack, Attack2, Death, Flying,
  Hit) — topología atípica ideal para probar los límites de la
  esqueletización (múltiples armatures, apéndices tipo ala en vez de
  extremidad estándar). Se despojó con:

  ```
  blender --background --python backend/scripts/_strip_rig.py -- \
      samples/_original/Bat.fbx samples/bat_unrigged.glb
  ```

  `_strip_rig.py` itera sobre *todos* los objetos ARMATURE de la escena, así
  que ambos armatures (no solo el principal) se eliminaron correctamente.
- **Verificado con:** `python backend/scripts/inspect_glb.py samples/bat_unrigged.glb`
  → 2302 vértices, **Huesos existentes: 0**, 5 materiales, bounding box
  `min=(-1.2841, -1.4300, 0.4278)` `max=(1.4491, 2.8839, 4.5059)` (envergadura
  visible en el rango X/Y).

### `test_cube.glb` — cubo de prueba (generado, Módulo 0)

Cubo simple + armature de 1 hueso creado con Blender para validar
`inspect_glb.py` end-to-end durante el Módulo 0 (ver Historial de
checkpoints en `CLAUDE.md`). No es un modelo de criatura.
