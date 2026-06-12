"""Tests de la lógica pura del Command Palette (U7).

Cubre fuzzy_score (subsecuencia, bonus y keywords) y rank_commands
(orden por score + top-8). Sin tkinter: solo las funciones puras y la
dataclass Command de ui/components/palette.py.
"""
from __future__ import annotations

from ui.components.palette import MAX_RESULTS, Command, fuzzy_score, rank_commands


def _cmd(label: str, keywords: str = "", id_: str = "") -> Command:
    return Command(id=id_ or label.lower().replace(" ", "_"),
                   label=label, keywords=keywords)


# ── fuzzy_score ──────────────────────────────────────────────────────────────

class TestFuzzyScore:
    def test_subsecuencia_matchea(self):
        assert fuzzy_score("exp", "Exportar PDF") > 0
        # Subsecuencia no contigua: x-p-d-f dentro de "Exportar PDF"
        assert fuzzy_score("xpdf", "Exportar PDF") > 0

    def test_case_insensitive(self):
        assert fuzzy_score("EXP", "exportar") > 0
        assert fuzzy_score("EXP", "exportar") == fuzzy_score("exp", "EXPORTAR")

    def test_no_match_devuelve_cero(self):
        assert fuzzy_score("zz", "banco") == 0.0
        # Caracteres presentes pero en orden incorrecto: no es subsecuencia
        assert fuzzy_score("ob", "banco") == 0.0
        assert fuzzy_score("abc", "") == 0.0

    def test_inicio_de_palabra_gana_a_interior(self):
        # "ban" arranca palabra en "abrir banco"; en "urbano" cae en el interior
        assert fuzzy_score("ban", "abrir banco") > fuzzy_score("ban", "urbano")

    def test_consecutivos_ganan_a_dispersos(self):
        # Mismos 3 caracteres: contiguos ("anc" en banco) vs salteados
        assert fuzzy_score("anc", "banco") > fuzzy_score("anc", "baznzc")

    def test_prefijo_exacto_gana(self):
        assert fuzzy_score("ban", "banco") > fuzzy_score("ban", "abrir banco")
        assert fuzzy_score("ban", "banco") > fuzzy_score("ban", "urbano")

    def test_keywords_cuentan(self):
        # "pdf" no es subsecuencia del label, pero sí de las keywords
        assert fuzzy_score("pdf", "Exportar documento") == 0.0
        assert fuzzy_score("pdf", "Exportar documento", keywords="pdf hoja") > 0

    def test_match_por_label_pesa_mas_que_por_keywords(self):
        por_label = fuzzy_score("banco", "banco")
        por_keywords = fuzzy_score("banco", "Glifos", keywords="banco")
        assert 0 < por_keywords < por_label

    def test_query_vacia_matchea_todo_con_score_base(self):
        base = fuzzy_score("", "cualquier cosa")
        assert base > 0
        assert fuzzy_score("", "otro texto") == base
        assert fuzzy_score("", "") == base


# ── rank_commands ────────────────────────────────────────────────────────────

class TestRankCommands:
    def test_ordena_por_score_descendente(self):
        cmds = [_cmd("Abrir banco"), _cmd("Urbano"), _cmd("Banco")]
        ranked = rank_commands("ban", cmds)
        assert [c.label for c in ranked] == ["Banco", "Abrir banco", "Urbano"]

    def test_excluye_los_que_no_matchean(self):
        cmds = [_cmd("Exportar PDF"), _cmd("Capturar página")]
        ranked = rank_commands("xpdf", cmds)
        assert [c.label for c in ranked] == ["Exportar PDF"]
        assert rank_commands("zzzz", cmds) == []

    def test_top_8_maximo(self):
        cmds = [_cmd(f"Comando {i:02d}", id_=f"c{i}") for i in range(12)]
        ranked = rank_commands("comando", cmds)
        assert len(ranked) == MAX_RESULTS == 8

    def test_query_vacia_devuelve_los_primeros_8_en_orden(self):
        cmds = [_cmd(f"Acción {i:02d}", id_=f"a{i}") for i in range(12)]
        ranked = rank_commands("", cmds)
        # Sort estable: a igual score (base) se conserva el orden de entrada
        assert ranked == cmds[:8]

    def test_keywords_influyen_en_el_ranking(self):
        cmds = [_cmd("Imprimir"), _cmd("Exportar", keywords="pdf")]
        ranked = rank_commands("pdf", cmds)
        assert [c.label for c in ranked] == ["Exportar"]

    def test_limit_personalizado(self):
        cmds = [_cmd(f"Item {i}", id_=f"i{i}") for i in range(6)]
        assert len(rank_commands("item", cmds, limit=3)) == 3

    def test_devuelve_los_objetos_command_originales(self):
        cmd = Command(id="abrir", label="Abrir banco", icon="folder",
                      shortcut="Ctrl+B", fn=None, keywords="glifos")
        assert rank_commands("abrir", [cmd]) == [cmd]
