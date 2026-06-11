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

## Hallazgo de entorno (medido en U1, 2026-06-11)

En esta máquina (Fedora 43, **Tk 9.0.2**, GNOME Wayland → XWayland) el primer
dibujo de CADA subventana X cuesta ~60–100 ms — reproducido con tkinter puro
(60 `tk.Frame` planos sin texto bloquean el mainloop ~6 s; con la ventana
`withdraw()` no hay bloqueo; GPU acelerada según glxinfo; desactivar
`xwayland-native-scaling` no cambió nada). Es independiente de la app: el
costo domina cualquier vista nueva y NO se arregla desde Python. La palanca
real es REDUCIR WIDGETS (lazy tabs, celdas compactas, acordeón) — que es lo
que hacen U1/U3/U4. Los presupuestos absolutos se evalúan con esto en mente;
el conteo de widgets es la métrica primaria.

## Resultados U1 (lazy tabs + patch CTkOptionMenu)

Dos causas raíz arregladas en U1:

1. **CTkOptionMenu._draw llama `self._canvas.update_idletasks()`** → flushea
   la cola de geometría de TODA la app en cada redraw (~1 s por OptionMenu
   durante construcción; medido con cProfile). Patcheado en main.py
   (workaround 3, mismo guard que CTkScrollbar).
2. **UI-02**: los 5 tabs de inkcore se construían de golpe → lazy builders.

| Métrica | Base | U1 |
|---|---:|---:|
| create_view(inkcore) | 8 336 ms | **833 ms** |
| inkcore:_build_profile_bar | 6 462 ms | **196 ms** |
| build_tab(Banco) | 2 009 ms | **295 ms** |
| Cambio a tab Banco (síncrono) | 3 642 ms | **366 ms** |
| Widgets tras navigate(inkcore) | 572 | **311** |
| navigate(inkcore) completo (sin el paint storm del entorno) | — | **870 ms** |

El "paint storm" post-navegación (~10 s con el banco real) es el costo de
entorno de arriba: se reduce ~proporcional al conteo de widgets en U3/U4.

## Cómo re-medir

```bash
HUEVONITIS_PERF=1 python main.py   # imprime arranque, widgets por navigate
                                   # y bloques >50 ms al log/stdout
```

El timer de arranque lo abre `main.py` (`perf.mark("startup")`) y lo cierra el
primer `navigate("dashboard")`. `ui/perf.py::measure` sirve para instrumentar
cualquier bloque nuevo. La tabla "después" se actualiza en U9.
