"""Harness de evaluación de REALISMO del render manuscrito (Fase R0).

A diferencia de tools/eval (que mide al extractor con IoU), este paquete mide
qué tan "humana" se ve una imagen de texto — real escaneada o sintética del
renderer — con métricas geométricas y estadísticas (R-BUG-12). El flujo:

    from tools.eval_render.metrics import metrics_from_path
    m = metrics_from_path("pagina.png")

o por CLI, comparando real contra sintético lado a lado:

    python -m tools.eval_render.compare real.png synth.png

Las métricas son la base del loop medir → cambiar UNA cosa → volver a medir
de las fases R1-R9.
"""
