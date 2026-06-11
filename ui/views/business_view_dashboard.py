"""BusinessDashboardMixin — dashboard con cards + chart animado."""
import contextlib

from core.businesscore.models import ClientJob
from ui import theme
from ui.animations import count_up


class BusinessDashboardMixin:
    """Cards de KPIs + pie chart de estados de trabajos."""

    def _refresh_dashboard(self):
        total = self._ledger.total_income()
        active = self._ledger.active_jobs_count()
        jobs = self._ledger.get_jobs()
        pending = round(sum(j.price_mxn for j in jobs
                            if j.status not in ("Pagado", "Cancelado")), 2)

        if len(self._dash_cards) >= 3:
            if self._dash_cards[0].winfo_exists():
                count_up(self._dash_cards[0], total, prefix="$", suffix=" MXN",
                         steps=22, step_ms=25, is_float=True)
            if self._dash_cards[1].winfo_exists():
                count_up(self._dash_cards[1], active,
                         steps=18, step_ms=30, is_float=False)
            if self._dash_cards[2].winfo_exists():
                count_up(self._dash_cards[2], pending, prefix="$", suffix=" MXN",
                         steps=22, step_ms=25, is_float=True)

        self._draw_status_chart(jobs)

    def _draw_status_chart(self, jobs: list[ClientJob]):
        if self._pie_anim_job is not None:
            with contextlib.suppress(Exception):
                self.after_cancel(self._pie_anim_job)
            self._pie_anim_job = None

        self._chart_canvas.delete("all")
        if not jobs:
            self._chart_canvas.create_text(250, 100, text="Sin datos",
                                           fill=theme.TEXT_MUTED)
            return

        from collections import Counter
        counts = Counter(j.status for j in jobs)
        total_count = sum(counts.values())
        if total_count == 0:
            self._chart_canvas.create_text(250, 100, text="Sin datos",
                                           fill=theme.TEXT_MUTED)
            return
        cx, cy, r = 100, 100, 80
        legend_x = 210

        arcs = []
        start_angle = 90  # comienza arriba
        for status, count in counts.items():
            extent = 360 * count / total_count
            color = theme.STATUS_COLORS.get(status, theme.TEXT_MUTED)
            arcs.append((status, count, start_angle, extent, color))
            start_angle += extent

        for i, (status, count, _sa, _ext, color) in enumerate(arcs):
            ly = 20 + i * 24
            self._chart_canvas.create_rectangle(
                legend_x, ly, legend_x + 14, ly + 14, fill=color, outline="")
            self._chart_canvas.create_text(
                legend_x + 20, ly + 7,
                text=f"{status}: {count}",
                anchor="w", fill=theme.TEXT_PRIMARY, font=theme.get_font(size=10),
            )

        self._animate_pie_arcs(arcs, cx, cy, r, 0, 0.0)

    def _animate_pie_arcs(self, arcs, cx, cy, r, arc_idx, progress):
        if not self.winfo_exists():
            return
        if arc_idx >= len(arcs):
            self._pie_anim_job = None
            return
        _, _, start_angle, extent, color = arcs[arc_idx]
        steps = max(6, int(extent / 8))
        step_ms = 12

        drawn_extent = extent * progress

        self._chart_canvas.delete(f"arc_{arc_idx}")
        if drawn_extent > 0.5:
            self._chart_canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start_angle, extent=drawn_extent,
                fill=color, outline=theme.BG_SECONDARY, width=2,
                tags=f"arc_{arc_idx}",
            )

        new_progress = progress + 1.0 / steps
        if new_progress < 1.0:
            self._pie_anim_job = self.after(
                step_ms,
                lambda: self._animate_pie_arcs(arcs, cx, cy, r, arc_idx, new_progress),
            )
        else:
            self._chart_canvas.delete(f"arc_{arc_idx}")
            self._chart_canvas.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=start_angle, extent=extent,
                fill=color, outline=theme.BG_SECONDARY, width=2,
                tags=f"arc_{arc_idx}",
            )
            self._pie_anim_job = self.after(
                step_ms,
                lambda: self._animate_pie_arcs(arcs, cx, cy, r, arc_idx + 1, 0.0),
            )
