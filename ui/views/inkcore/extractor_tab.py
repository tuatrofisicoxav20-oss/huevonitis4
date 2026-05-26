"""ExtractorTabMixin — tab 📷 Extractor de InkCoreView."""
import logging
import threading
from pathlib import Path
from tkinter import filedialog

import customtkinter as ctk

import config
from core.inkcore.extractor import ExtractionOptions
from ui import theme

logger = logging.getLogger(__name__)

try:
    from PIL import Image, ImageEnhance, ImageTk
    _PIL_OK = True
except ImportError:
    _PIL_OK = False


class ExtractorTabMixin:
    """Tab de extracción individual de glifos; mezclado en InkCoreView."""

    def _on_auto_mode_toggle(self):
        """Modo auto OCR-first: TrOCR/Tesseract leen la imagen y dan el texto guía."""
        auto = bool(self._auto_mode_var.get())
        if auto:
            # text_color_disabled explícito: sin esto, CTkTextbox pinta el texto
            # con un gris por defecto que sobre BG_SECONDARY queda casi negro/invisible.
            self._ref_text.configure(
                state="disabled",
                fg_color=theme.BG_SECONDARY,
                text_color_disabled=theme.TEXT_MUTED,
            )
            self._adj_ref_label.configure(text_color=theme.TEXT_MUTED)
            # Indicar qué motor OCR se usará
            try:
                import transformers  # noqa: F401
                ocr_name = "TrOCR (handwriting)"
                color = theme.ACCENT_GREEN
            except ImportError:
                ocr_name = "Tesseract PSM 6 (texto continuo)"
                color = theme.ACCENT_ORANGE
            self._ref_example_label.configure(
                text=f"Modo automático: OCR leerá la imagen con {ocr_name}.",
                text_color=color,
            )
        else:
            self._ref_text.configure(state="normal", fg_color=theme.BG_TERTIARY)
            self._adj_ref_label.configure(text_color=theme.TEXT_SECONDARY)
            self._ref_example_label.configure(
                text="Ejemplo: hola mundo abcdefg  /  segunda línea: ñoño piña",
                text_color=theme.TEXT_MUTED,
            )

    # ── Modo auto: heurísticas + diálogo de confirmación ──────────

    @staticmethod
    def _looks_suspect(text: str) -> bool:
        """Detecta si el OCR devolvió algo que probablemente sea un error.

        Casos típicos:
          • Texto muy corto (1-2 chars) → probable basura
          • Palabras improbables tipo "humanization" en una imagen del alfabeto
          • Solo 1 "palabra" larga (sin espacios) y > 10 chars: muy raro
        """
        if not text:
            return True
        clean = text.strip()
        if len(clean) < 2:
            return True
        # Una palabra continua muy larga (>15 chars) sin espacios suele ser
        # alucinación del modelo TrOCR (intentando "leer" un grid de letras).
        if " " not in clean and len(clean) > 15:
            return True
        # Si ningún char es alfanumérico → basura
        if not any(c.isalnum() for c in clean):
            return True
        return False

    _QUICK_TEMPLATES = [
        ("a-z", "a b c d e f g h i j k l m n ñ o p q r s t u v w x y z"),
        ("A-Z", "A B C D E F G H I J K L M N Ñ O P Q R S T U V W X Y Z"),
        ("0-9", "0 1 2 3 4 5 6 7 8 9"),
        ("a-z + 0-9", "a b c d e f g h i j k l m n ñ o p q r s t u v w x y z\n0 1 2 3 4 5 6 7 8 9"),
    ]

    def _ask_user_ref_text(self, predicted: str, conf: float) -> str:
        """Modal: muestra el OCR sugerido + plantillas rápidas; usuario edita y confirma."""
        win = ctk.CTkToplevel(self)
        win.title("Confirmar texto de la imagen")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.geometry("520x460")
        win.grab_set()

        ctk.CTkLabel(
            win, text="📝 Confirma el texto de tu imagen",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(16, 4))

        if conf > 0:
            color = theme.ACCENT_ORANGE if conf < 0.75 else theme.ACCENT_GREEN
            ctk.CTkLabel(
                win,
                text=f"OCR detectó (confianza {conf:.0%}). Edita si no es correcto:",
                font=theme.FONT_SMALL, text_color=color,
            ).pack(pady=(0, 4))
        else:
            ctk.CTkLabel(
                win, text="OCR no pudo leer la imagen. Escribe el texto manualmente:",
                font=theme.FONT_SMALL, text_color=theme.ACCENT_RED,
            ).pack(pady=(0, 4))

        textbox = ctk.CTkTextbox(
            win, font=theme.FONT_BODY,
            fg_color=theme.BG_TERTIARY,
            text_color=theme.TEXT_PRIMARY,
            border_color=theme.ACCENT_BLUE, border_width=1,
            height=120,
        )
        textbox.pack(fill="x", padx=20, pady=8)
        if predicted:
            textbox.insert("1.0", predicted)
        textbox.focus_set()

        ctk.CTkLabel(
            win, text="💡 Plantillas rápidas:",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(anchor="w", padx=20, pady=(8, 4))

        tpl_frame = ctk.CTkFrame(win, fg_color="transparent")
        tpl_frame.pack(fill="x", padx=20)

        def _fill(template):
            textbox.delete("1.0", "end")
            textbox.insert("1.0", template)
            textbox.focus_set()

        for label, content in self._QUICK_TEMPLATES:
            ctk.CTkButton(
                tpl_frame, text=label, width=88, height=28,
                fg_color=theme.ACCENT_BLUE, hover_color=theme.ACCENT_BLUE_HOVER,
                font=theme.FONT_SMALL,
                command=lambda c=content: _fill(c),
            ).pack(side="left", padx=4, pady=4)

        result = {"text": None}

        def _confirm():
            result["text"] = textbox.get("1.0", "end").strip()
            win.destroy()

        def _cancel():
            result["text"] = None
            win.destroy()

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(12, 16))
        ctk.CTkButton(
            btn_row, text="Cancelar", command=_cancel,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY,
            width=110, height=36,
        ).pack(side="left")
        ctk.CTkButton(
            btn_row, text="✓ Procesar con este texto", command=_confirm,
            fg_color=theme.ACCENT_GREEN, hover_color=theme.ACCENT_GREEN_HOVER,
            font=("Segoe UI", 11, "bold"),
            width=240, height=36,
        ).pack(side="right")

        textbox.bind("<Control-Return>", lambda e: _confirm())
        win.wait_window()
        return result["text"] or ""

    # ── Image loading ──────────────────────────────────────────────

    def _load_image(self):
        path = filedialog.askopenfilename(
            title="Cargar imagen de apunte",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.bmp *.tiff *.webp")],
        )
        if not path:
            return
        self._image_path = path
        name = Path(path).name
        self._img_name_label.configure(text=f"✓ {name}", text_color=theme.ACCENT_GREEN)
        self._extract_error.configure(text="")
        logger.info("Imagen cargada: %s", path)
        if _PIL_OK:
            try:
                self._original_img = Image.open(path).convert("RGB")
                self._apply_preview()
            except Exception as e:
                logger.warning("No se pudo abrir imagen para preview: %s", e)
                self._img_preview.configure(text=name)
                # Sin este toast, el usuario veía "✓ cargada" pero el preview
                # quedaba en blanco sin saber por qué — ahora se le avisa.
                self.toast(
                    f"Imagen cargada pero no se pudo generar preview: {e}",
                    "warning",
                )
        else:
            self._img_preview.configure(text=name)
            self.toast("PIL no disponible — no se mostrará preview", "warning")

    def _apply_preview(self, *_):
        if not _PIL_OK or self._original_img is None:
            return
        img = self._original_img.copy()
        rot = float(self._rotation_slider.get())
        if abs(rot) > 0.1:
            img = img.rotate(rot, expand=False, fillcolor=(255, 255, 255))
        br = float(self._brightness_slider.get())
        if abs(br) > 0.5:
            factor = 1.0 + br / 100.0
            img = ImageEnhance.Brightness(img).enhance(max(0.1, factor))
        co = float(self._contrast_slider.get())
        if abs(co) > 0.5:
            factor = 1.0 + co / 100.0
            img = ImageEnhance.Contrast(img).enhance(max(0.1, factor))
        img.thumbnail((380, 200), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        self._img_preview.configure(image=photo, text="")
        self._img_preview._image_ref = photo

    # ── Extraction ─────────────────────────────────────────────────

    def _extract(self):
        logger.info("_extract() llamado")
        if not self._image_path:
            logger.warning("_extract: sin imagen")
            self._extract_error.configure(
                text="⚠ Primero debes cargar una imagen con el botón '📷 Cargar imagen'"
            )
            self.toast("Carga una imagen primero", "warning")
            return

        auto_mode = bool(getattr(self, "_auto_mode_var", None) and self._auto_mode_var.get())
        ref = self._ref_text.get("1.0", "end").strip()
        logger.info("_extract: auto=%s, texto de referencia = %r", auto_mode, ref[:80])
        if not auto_mode and not ref:
            logger.warning("_extract: texto de referencia vacío y modo manual")
            self._extract_error.configure(
                text="⚠ Activa 'Modo automático' o escribe el texto de referencia"
            )
            self.toast("Activa modo automático o escribe el texto", "warning")
            return

        self._extract_error.configure(text="")

        # MODO AUTOMÁTICO MEJORADO: OCR-first.
        # 1) Predecimos el texto sobre la imagen COMPLETA con TrOCR (o Tesseract
        #    PSM 6 como fallback). Esto es muchísimo más preciso que clasificar
        #    cada glifo aislado con tesseract single-char.
        # 2) Usamos ese texto como reference_text para el flujo legacy, que ya
        #    está optimizado para alinear bboxes a chars conocidos.
        if auto_mode:
            from core.inkcore.auto_text import predict_text_from_image
            self._extract_status.configure(
                text="🔎 Detectando texto en la imagen…",
                text_color=theme.ACCENT_BLUE,
            )
            self.update_idletasks()
            try:
                predicted, source, conf = predict_text_from_image(self._image_path)
            except Exception as exc:
                logger.error("predict_text_from_image error: %s", exc, exc_info=True)
                predicted, source, conf = "", "", 0.0
            logger.info("auto-mode OCR (%s) conf=%.2f → %r",
                        source, conf, predicted[:80])

            # Si la confidence es baja o el resultado parece raro,
            # abrimos un diálogo editable con plantillas rápidas.
            # TrOCR falla en letras aisladas (alfabeto manuscrito en grid):
            # devuelve "a p.a.d gr. Fig. humanization" en lugar de "a b c d…".
            need_confirm = (
                conf < 0.75
                or not predicted
                or self._looks_suspect(predicted)
            )
            if need_confirm:
                self._extract_status.configure(text="", text_color=theme.TEXT_MUTED)
                ref = self._ask_user_ref_text(predicted, conf)
                if not ref:
                    self._extract_error.configure(
                        text="⚠ Extracción cancelada — sin texto de referencia"
                    )
                    self.toast("Cancelado", "info")
                    return
            else:
                ref = predicted
                self.toast(f"OCR ({source}) detectó: {ref[:40]}…", "info")

        # Pipeline ensemble es opcional incluso en modo auto (el OCR-first ya
        # garantiza el texto). Lo respetamos si el usuario lo activó manualmente.
        use_p = bool(self._use_pipeline_var.get())
        cfg = self._get_pipeline_config() if use_p else None
        opts = ExtractionOptions(
            remove_lines=self._remove_lines_var.get(),
            brightness=float(self._brightness_slider.get()),
            contrast=float(self._contrast_slider.get()),
            rotation_deg=float(self._rotation_slider.get()),
            use_pipeline=use_p,
            pipeline_config=cfg,
            min_quality=float(self._min_quality_slider.get()) if use_p else config.MIN_GLYPH_QUALITY,
        )
        logger.info("_extract: opts=%s, iniciando hilo", opts)

        # Refresca el chip para que refleje exactamente la corrida en curso
        try:
            self._refresh_pipeline_chip()
        except Exception:
            pass

        self._extract_progress.pack(fill="x", padx=12, pady=2)
        self._extract_progress.start()
        self._extract_btn.configure(state="disabled")
        self._extract_status.configure(
            text="Procesando imagen...", text_color=theme.ACCENT_ORANGE,
        )
        self.toast("Extrayendo glifos...", "info")

        image_path = self._image_path

        def worker():
            logger.info("worker: iniciando extracción")
            try:
                glyphs = self._pipeline.extract(image_path, ref, opts)
                logger.info("worker: extracción completada — %d glifos", len(glyphs))
            except Exception as exc:
                logger.error("worker: error en extracción: %s", exc, exc_info=True)
                glyphs = []
            try:
                self.after(0, lambda: self._on_extracted(glyphs))
            except Exception as e:
                logger.error("worker: error al programar callback: %s", e)

        threading.Thread(target=worker, daemon=True).start()
        logger.info("_extract: hilo iniciado")

    def _on_extracted(self, glyphs: list):
        if not self.winfo_exists():
            return
        self._extract_progress.stop()
        self._extract_progress.pack_forget()
        self._extract_btn.configure(state="normal")
        self._extracted = glyphs
        self._show_extracted_grid()
        if glyphs:
            gold   = sum(1 for g in glyphs if g.tier == "Gold")
            silver = sum(1 for g in glyphs if g.tier == "Silver")
            bronze = sum(1 for g in glyphs if g.tier == "Bronze")
            line1 = (f"✓ {len(glyphs)} glifos  —  "
                     f"🥇 Gold: {gold}  🥈 Silver: {silver}  🥉 Bronze: {bronze}")

            ensemble = getattr(self._pipeline.extractor, "_last_ensemble_result", None)
            extra = ""
            if ensemble is not None:
                stats = getattr(ensemble, "stats", {}) or {}
                timings = getattr(ensemble, "timings_ms", {}) or {}
                det_counts = stats.get("detector_counts", {})
                det_str = ", ".join(f"{k}:{v}" for k, v in det_counts.items()) or "—"
                discarded = stats.get("glyphs_discarded", 0)
                total_ms = timings.get("total_ms", 0)
                extra = (f"\nEnsemble · detectores [{det_str}] · "
                         f"fusionados {stats.get('fused_count', 0)} · "
                         f"descartados {discarded} · {total_ms} ms")
            self._extract_status.configure(
                text=line1 + extra,
                text_color=theme.ACCENT_GREEN,
            )
            self.toast(f"{len(glyphs)} glifos extraídos", "success")

            # Auto-abrir debug overlay si el pipeline lo generó
            if ensemble is not None and getattr(ensemble, "debug_image_path", None):
                try:
                    self._open_debug_overlay(ensemble.debug_image_path)
                except Exception as _e:
                    logger.warning("No se pudo abrir debug overlay: %s", _e)
        else:
            self._extract_status.configure(
                text="Sin glifos — sube brillo/contraste, o prueba sin 'Quitar líneas'",
                text_color=theme.ACCENT_RED,
            )
            self.toast("Sin glifos. Revisa el log: ~/.local/share/huevonitis4/app.log", "warning")

    def _open_debug_overlay(self, path: str):
        if not _PIL_OK or not Path(path).exists():
            return
        win = ctk.CTkToplevel(self)
        win.title("Debug overlay — pipeline ensemble")
        win.configure(fg_color=theme.BG_PRIMARY)
        ctk.CTkLabel(
            win, text="Verde: todos los detectores · Amarillo: parcial · Rojo: descartado",
            font=theme.FONT_SMALL, text_color=theme.TEXT_SECONDARY,
        ).pack(pady=(10, 4))
        img = Image.open(path)
        max_w = 1000
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)
        photo = ImageTk.PhotoImage(img)
        lbl = ctk.CTkLabel(win, image=photo, text="")
        lbl.pack(padx=12, pady=8)
        lbl._photo_ref = photo
        ctk.CTkButton(
            win, text="Cerrar", command=win.destroy,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY, width=100,
        ).pack(pady=(0, 12))
        win.geometry(f"{img.width + 32}x{img.height + 100}")

    def _refresh_detector_chip(self) -> None:
        """Alias retrocompatible — delega al nuevo _refresh_pipeline_chip."""
        self._refresh_pipeline_chip()

    def _refresh_pipeline_chip(self) -> None:
        """Muestra qué detectores + labelers están activos en el ensemble."""
        chip = getattr(self, "_detector_chip", None)
        if chip is None:
            return
        try:
            det_vars = getattr(self, "_detector_vars", {}) or {}
            lab_vars = getattr(self, "_labeler_vars", {}) or {}
            dets = [name for name, var in det_vars.items() if var.get()]
            labs = [name for name, var in lab_vars.items() if var.get()]
            if not dets and not labs:
                # Fallback al detector configurado (compat flow legacy)
                det_name = getattr(config, "GLYPH_DETECTOR", "classic_cv")
                chip.configure(text=f"  ⚙ {det_name}  ")
                return
            parts = []
            if dets:
                parts.append("D:" + "+".join(d.replace("_labeler", "").replace("_det", "") for d in dets))
            if labs:
                parts.append("L:" + "+".join(l.replace("_labeler", "") for l in labs))
            chip.configure(text="  ⚙ " + "  ".join(parts) + "  ")
        except Exception:
            pass

    def _save_to_bank(self):
        if not self._extracted:
            self.toast("No hay glifos para guardar", "warning")
            return
        total = len(self._extracted)
        # Pre-chequeo: glifos cuyo PNG temporal ya no existe se descartarían
        # silenciosamente dentro de bank.add_glyph (devuelve None). Detectarlos
        # antes nos permite avisarle al usuario en vez de mostrar "0 guardados".
        missing = [g for g in self._extracted if not Path(g.image_path).exists()]
        if missing:
            logger.warning(
                "_save_to_bank: %d/%d glifos sin PNG temporal (probable cleanup previo)",
                len(missing), total,
            )
        try:
            saved = self._pipeline.save_glyphs_to_bank(self._extracted)
        except Exception as exc:
            logger.exception("_save_to_bank: error guardando glifos: %s", exc)
            self.toast(f"Error al guardar: {exc}", "error")
            return
        dupes = total - saved - len(missing)
        logger.info(
            "_save_to_bank: total=%d saved=%d dupes=%d missing=%d",
            total, saved, dupes, len(missing),
        )
        if saved == 0:
            if missing and not dupes:
                self.toast(
                    f"Nada guardado: {len(missing)} PNG temporales ya no existen "
                    "(re-extrae para reintentar)", "warning",
                )
            elif dupes == total:
                self.toast(f"Nada nuevo: los {total} glifos ya estaban en el banco", "warning")
            else:
                self.toast("Nada guardado — revisa el log", "warning")
        else:
            msg = f"{saved} glifos guardados"
            extras = []
            if dupes:
                extras.append(f"{dupes} duplicados")
            if missing:
                extras.append(f"{len(missing)} sin archivo")
            if extras:
                msg += f"  ({', '.join(extras)})"
            self.toast(msg, "success")
            # save_glyphs_to_bank llama _cleanup_temp_dir() internamente, así
            # que los PNG temporales ya no existen. Reemplazamos las rutas en
            # self._extracted con las entradas permanentes del banco para que
            # un segundo clic en "Guardar en banco" detecte correctamente los
            # glifos como "ya en el banco" (duplicados) en vez de "archivo no existe".
            self._update_extracted_to_bank_paths()
        try:
            self._refresh_bank()
        except Exception as exc:
            logger.exception("_save_to_bank: _refresh_bank falló: %s", exc)

    def _update_extracted_to_bank_paths(self) -> None:
        """Reemplaza rutas temporales de self._extracted con rutas permanentes del banco.

        Después de save_glyphs_to_bank + _cleanup_temp_dir los PNGs en _temp_extract
        ya no existen. Busca las entradas correspondientes en el banco (por char,
        índice más reciente) y actualiza self._extracted para que apunten a archivos
        válidos. Evita el bug de "segundo clic falla con archivo no existe".
        """
        bank_all = self._pipeline.bank.get_all()
        bank_by_char: dict[str, list] = {}
        for e in bank_all:
            bank_by_char.setdefault(e.char, []).append(e)

        assigned: set[str] = set()
        new_extracted = []
        for g in self._extracted:
            cands = sorted(
                bank_by_char.get(g.char, []),
                key=lambda e: e.index,
                reverse=True,
            )
            best = next((e for e in cands if e.image_path not in assigned), None)
            if best:
                assigned.add(best.image_path)
                new_extracted.append(best)
        self._extracted = new_extracted
        self._show_extracted_grid()

    # ── Preprocess preview ─────────────────────────────────────────

    def _show_preprocess_preview(self):
        if not self._image_path:
            self.toast("Carga una imagen primero", "warning")
            return
        opts = ExtractionOptions(
            remove_lines=self._remove_lines_var.get(),
            brightness=float(self._brightness_slider.get()),
            contrast=float(self._contrast_slider.get()),
            rotation_deg=float(self._rotation_slider.get()),
        )
        # Deshabilitar el botón mientras corre el thread: sin esto, clicks
        # repetidos lanzan threads concurrentes que abren múltiples ventanas
        # de preview y compiten por los mismos sliders/imagen.
        try:
            self._preview_btn.configure(state="disabled", text="Procesando…")
        except (AttributeError, Exception):
            pass
        self.toast("Generando preview de preprocesamiento…", "info")
        image_path = self._image_path

        def _restore():
            try:
                self._preview_btn.configure(state="normal", text="🔍 Ver preprocesamiento")
            except (AttributeError, Exception):
                pass

        def worker():
            try:
                preview = self._pipeline.extractor.get_preprocessed_preview(image_path, opts)
            except Exception as exc:
                logger.exception("get_preprocessed_preview falló: %s", exc)
                preview = None
            def _done():
                _restore()
                self._open_preview_window(preview)
            try:
                self.after(0, _done)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _open_preview_window(self, img):
        if not self.winfo_exists():
            return
        if img is None:
            self.toast("No se pudo generar preview", "error")
            return
        win = ctk.CTkToplevel(self)
        win.title("Preview de preprocesamiento")
        win.configure(fg_color=theme.BG_PRIMARY)
        win.grab_set()

        ctk.CTkLabel(
            win, text="Original  |  Máscara limpia",
            font=theme.FONT_SUBHEADING, text_color=theme.TEXT_SECONDARY,
        ).pack(pady=(12, 4))

        max_w = 900
        if img.width > max_w:
            ratio = max_w / img.width
            img = img.resize((max_w, int(img.height * ratio)), Image.LANCZOS)

        if _PIL_OK:
            photo = ImageTk.PhotoImage(img)
            lbl = ctk.CTkLabel(win, image=photo, text="")
            lbl.pack(padx=16, pady=8)
            lbl._photo_ref = photo

        ctk.CTkLabel(
            win,
            text="Izquierda: imagen procesada  |  Derecha: máscara binaria (tinta detectada)",
            font=theme.FONT_SMALL, text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 4))
        ctk.CTkButton(
            win, text="Cerrar", command=win.destroy,
            fg_color=theme.BG_TERTIARY, text_color=theme.TEXT_PRIMARY, width=100,
        ).pack(pady=(0, 12))
        win.geometry(f"{img.width + 32}x{img.height + 120}")
