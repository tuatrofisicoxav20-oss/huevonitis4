"""U4 — thumbnails persistentes del banco: generación, invalidación y diff."""
import os
import time

import pytest

from core.inkcore import thumb_cache as tc

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


@pytest.fixture
def bank(tmp_path):
    """Banco falso: 3 PNGs de glifo de 120×100."""
    srcs = []
    for ch in "abc":
        p = tmp_path / f"{ch}.png"
        Image.new("RGBA", (120, 100), (10, 10, 10, 255)).save(p)
        srcs.append(p)
    return tmp_path, srcs


def test_ensure_thumb_creates_64px(bank):
    bank_dir, srcs = bank
    tp = tc.ensure_thumb(bank_dir, srcs[0], 64)
    assert tp is not None and tp.exists()
    assert tp.parent == bank_dir / ".thumbs" / "64"
    with Image.open(tp) as img:
        assert max(img.size) <= 64
        assert img.mode == "RGBA"


def test_ensure_thumb_is_idempotent(bank):
    bank_dir, srcs = bank
    tp = tc.ensure_thumb(bank_dir, srcs[0])
    mtime1 = tp.stat().st_mtime_ns
    tp2 = tc.ensure_thumb(bank_dir, srcs[0])
    assert tp2 == tp
    assert tp.stat().st_mtime_ns == mtime1, "sin cambios en la fuente NO regenera"


def test_ensure_thumb_regenerates_on_source_change(bank):
    bank_dir, srcs = bank
    tp = tc.ensure_thumb(bank_dir, srcs[0])
    mtime1 = tp.stat().st_mtime_ns
    # Fuente más nueva que el thumb → stale → regenerar
    future = time.time() + 60
    os.utime(srcs[0], (future, future))
    assert tc.is_stale(srcs[0], tp)
    tc.ensure_thumb(bank_dir, srcs[0])
    assert tp.stat().st_mtime_ns > mtime1


def test_ensure_thumb_missing_source(bank):
    bank_dir, _ = bank
    assert tc.ensure_thumb(bank_dir, bank_dir / "nope.png") is None


def test_build_thumbs_batch_and_progress(bank):
    bank_dir, srcs = bank
    seen = []
    n = tc.build_thumbs(bank_dir, srcs, progress_cb=lambda i, t: seen.append((i, t)))
    assert n == 3
    assert seen == [(1, 3), (2, 3), (3, 3)]
    # Segunda pasada: nada que regenerar
    assert tc.build_thumbs(bank_dir, srcs) == 0


def test_build_thumbs_cancel(bank):
    bank_dir, srcs = bank
    n = tc.build_thumbs(bank_dir, srcs, should_cancel=lambda: True)
    assert n == 0


def test_prune_orphans(bank):
    bank_dir, srcs = bank
    tc.build_thumbs(bank_dir, srcs)
    # 'c' sale del banco → su thumb es huérfano
    removed = tc.prune_orphans(bank_dir, srcs[:2])
    assert removed == 1
    assert tc.thumb_path(bank_dir, srcs[0]).exists()
    assert not tc.thumb_path(bank_dir, srcs[2]).exists()


def test_diff_paths():
    add, rm, keep = tc.diff_paths({"a", "b"}, {"b", "c"})
    assert add == {"c"} and rm == {"a"} and keep == {"b"}
    add, rm, keep = tc.diff_paths(set(), {"x"})
    assert add == {"x"} and not rm and not keep
