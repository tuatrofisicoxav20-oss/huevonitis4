# Release Checklist — Huevonitis 4

Lista a recorrer antes de etiquetar y publicar una versión.

## Pre-flight

- [ ] `python tools/doctor.py` sin errores críticos
- [ ] `pytest -q` 100% passing (no `xfail`, no `skip` salvo e2e sin fixtures)
- [ ] `ruff check .` sin errores
- [ ] No hay archivos `.pyc` ni `__pycache__/` en `git status`
- [ ] No hay rutas absolutas personales en docs o código (`grep -r "/home/" docs/ core/ ui/`)
- [ ] No hay `.env`, credenciales, ni claves trackeadas
- [ ] No hay `print()` de debug en código de producción (solo `logging`)

## Versionado

- [ ] `VERSION` actualizado
- [ ] `config.py:VERSION` actualizado
- [ ] `pyproject.toml:version` actualizado
- [ ] `install.sh:VERSION` actualizado
- [ ] Las cuatro fuentes coinciden (`grep -r "VERSION.*=.*\"" *.py *.toml VERSION install.sh`)

## Documentación

- [ ] `docs/CHANGELOG.md` actualizado con entrada para esta versión
- [ ] `docs/KNOWN_ISSUES.md` actualizado (cualquier bug nuevo o ya resuelto)
- [ ] `README.md`: contador de tests refleja el real
- [ ] `docs/ROADMAP.md`: marcar items completados con ✅
- [ ] `docs/ARCHITECTURE.md`: si hay módulos nuevos / renombrados, actualizar

## Dependencias

- [ ] `requirements.txt`, `pyproject.toml` e `install.sh` listan las mismas deps
- [ ] `requirements-optional.txt` documenta extras (PaddleOCR, TrOCR, etc.)
- [ ] Verificado en Python 3.10, 3.12, 3.13, 3.14 (al menos en CI o local)

## Limpieza del zip

- [ ] `.git/` excluido
- [ ] `__pycache__/`, `*.pyc`, `*.pyo` excluidos
- [ ] `.pytest_cache/`, `.ruff_cache/`, `.mypy_cache/` excluidos
- [ ] `build/`, `dist/`, `*.spec` excluidos (a menos que se publique el spec)
- [ ] `*.log`, archivos temporales excluidos
- [ ] No hay backups viejos en `docs/` o raíz
- [ ] `python tools/clean.py --dry-run` no muestra basura

## Empaquetado (opcional)

- [ ] `pyinstaller build/huevonitis4.spec` produce binario funcional
- [ ] `install.sh` corre limpio en Fedora/Ubuntu/Arch
- [ ] `uninstall.sh` deja el sistema limpio (con y sin opción de borrar datos)
- [ ] El binario o el script lanza la app sin errores en arranque

## Tag y push

- [ ] `git status` limpio
- [ ] Último commit tiene mensaje claro y referencia a la versión
- [ ] `git tag -a v<X.Y.Z> -m "<descripción>"`
- [ ] Push con `--tags`

## Post-release

- [ ] Verificar que el tag aparece en GitHub
- [ ] Verificar que el binario/zip descargable funciona en máquina limpia
- [ ] Crear release notes en GitHub (copiar del CHANGELOG)
- [ ] Actualizar este checklist con lo que faltó / sorprendió

---

## Reglas anti-shipping

❌ **NO** llamar release a una versión con tests fallando.
❌ **NO** crear tag mientras `git status` tiene cambios no commiteados.
❌ **NO** publicar zip que contenga `.git/` o caches.
❌ **NO** empaquetar como final si la cobertura de UI/OCR sigue baja.
❌ **NO** subir un PR sin que `pytest -q` pase localmente primero.
