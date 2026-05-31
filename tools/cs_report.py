"""
Render/visualización del informe HTML para compare_strategies.

Genera un informe HTML autocontenido (imágenes embebidas en base64) con la
tabla comparativa de estrategias ensemble y sus overlays de depuración.
"""


def _write_html_report(image_path: str, results: dict, overlays: dict, out: str) -> None:
    import base64
    from pathlib import Path

    def img_to_b64(path: str) -> str:
        try:
            return base64.b64encode(Path(path).read_bytes()).decode()
        except Exception:
            return ""

    orig_b64 = img_to_b64(image_path)
    ext_lower = Path(image_path).suffix.lower().lstrip(".")
    mime = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png"}.get(ext_lower, "png")

    rows_html = ""
    for strat, r in results.items():
        glyphs = r["glyphs"]
        avg_q = (sum(g.quality_score for g in glyphs) / len(glyphs)
                 if glyphs else 0.0)
        overlay_html = ""
        if strat in overlays:
            ov_b64 = img_to_b64(overlays[strat])
            if ov_b64:
                overlay_html = (
                    f'<img src="data:image/png;base64,{ov_b64}" '
                    f'style="max-width:300px;border:1px solid #444">'
                )
        chars_found = ", ".join(
            f"{g.char}({g.quality_score:.2f})" for g in glyphs[:20]
        )
        rows_html += f"""
        <tr>
          <td><b>{strat}</b></td>
          <td>{len(glyphs)}</td>
          <td>{avg_q:.3f}</td>
          <td>{r['time_ms']} ms</td>
          <td style="font-size:0.8em">{chars_found}</td>
          <td>{overlay_html}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Compare Strategies — {Path(image_path).name}</title>
<style>
  body{{font-family:sans-serif;background:#1a1a2e;color:#e0e0e0;padding:20px}}
  table{{border-collapse:collapse;width:100%}}
  th,td{{border:1px solid #444;padding:8px 12px;text-align:left}}
  th{{background:#16213e}} tr:nth-child(even){{background:#0f3460}}
  img{{border-radius:4px}}
</style></head>
<body>
<h1>Comparación de estrategias</h1>
<p><b>Imagen:</b> {image_path}</p>
<img src="data:image/{mime};base64,{orig_b64}" style="max-width:600px;margin-bottom:20px">
<table>
  <tr><th>Estrategia</th><th>Glifos</th><th>Avg Q</th><th>Tiempo</th>
      <th>Chars encontrados</th><th>Overlay</th></tr>
  {rows_html}
</table>
</body></html>"""
    Path(out).write_text(html, encoding="utf-8")
