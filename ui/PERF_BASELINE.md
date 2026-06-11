# Línea base de rendimiento UI (U0)

Medido el 2026-06-10 con `HUEVONITIS_PERF=1` + driver automatizado
(arranca → dashboard → primera apertura de "Mi Letra" → tab Banco → cierra),
banco real del usuario (346 glifos, perfil default), Fedora + Hyprland,
Intel iGPU, Python 3.14, customtkinter 5.2.2.

## Números base (ANTES de U1–U9)

| Métrica | Base | Presupuesto (U9) |
|---|---:|---:|
| Arranque frío → dashboard listo | 2 492 ms | −30% (≤ 1 745 ms) |
| Primera apertura "Mi Letra" (construye los 5 tabs + on_show) | **19 457 ms** | < 400 ms |
| Cambio al tab Banco (porción síncrona del refresh) | 3 642 ms | < 500 ms (con 600 glifos) |
| Widgets tras navigate(dashboard) | 205 | — |
| Widgets tras navigate(inkcore) | 572 | — |
| Widgets con el grid del Banco renderizado (1ª página, 78 ops) | 724 | menos por celda (celda v2) |

Notas:

- La primera apertura de "Mi Letra" es el cuello dominante: `_build` construye
  los 5 tabs de golpe (UI-02) y `on_show` recarga el banco + refresca todo.
  El grid del banco además regenera thumbnails desde los PNG completos con
  LANCZOS en el hilo principal (UI-05) — de ahí los ~19 s.
- El grid usa `ImageTk.PhotoImage` (customtkinter avisa que no escala en
  HiDPI); la celda v2 de U4 migra a `CTkImage` + thumbs en disco.
- El conteo de widgets del Banco es con la paginación actual (78 ops por
  página); el banco completo sin paginar serían ~6 widgets por glifo.

## Cómo re-medir

```bash
HUEVONITIS_PERF=1 python main.py   # imprime arranque, widgets por navigate
                                   # y bloques >50 ms al log/stdout
```

El timer de arranque lo abre `main.py` (`perf.mark("startup")`) y lo cierra el
primer `navigate("dashboard")`. `ui/perf.py::measure` sirve para instrumentar
cualquier bloque nuevo. La tabla "después" se actualiza en U9.
