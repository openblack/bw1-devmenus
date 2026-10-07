import hashlib
import os
import struct
from pathlib import Path

import pytest

import patch_devmenus as pd

PATCHED_SHA256 = "7fd837eb1aa6c92e351dad34f81ddfea1ed85b324e5c4142b9a63d769738ef8a"


def test_asm_resolves_labels_and_fixups():
    a = pd.Asm(0x1000)
    a.rel32(b"\xe9", "end")
    a.abs32(b"\x68", ("end", -1))
    a.raw(b"\x90")
    a.label("end")
    code = a.assemble()
    assert a.labels["end"] == 0x100B
    assert code[:5] == b"\xe9" + struct.pack("<i", 0x100B - 0x1005)
    assert code[5:10] == b"\x68" + struct.pack("<I", 0x100A)
    assert len(code) == a.size() == 11


def test_asm_rejects_duplicate_labels():
    a = pd.Asm(0)
    a.label("x")
    a.label("x")
    with pytest.raises(ValueError):
        a.assemble()


def test_stub_fits_in_cave_and_starts_with_hook():
    cave, labels, patches = pd.build_patches()
    assert pd.CAVE + len(cave) <= pd.CAVE_END
    assert labels["hook"] == pd.CAVE
    for _, _, original, new in patches:
        assert len(original) == len(new)


def test_hook_jump_targets_stub():
    _, labels, patches = pd.build_patches()
    _, va, _, jump = patches[0]
    assert va == pd.HOOK_SITE
    assert jump[0] == 0xE9
    assert va + 5 + struct.unpack_from("<i", jump, 1)[0] == labels["hook"]


def test_key_list_table_points_at_lists():
    cave, labels, _ = pd.build_patches()
    off = labels["key_lists"] - pd.CAVE
    names = ["keys_jeremy", "keys_tim", "keys_george", "keys_tom", "keys_unnamed"]
    assert list(struct.unpack_from("<5I", cave, off)) == [labels[n] for n in names]


def test_messages_are_null_terminated():
    cave, labels, _ = pd.build_patches()
    off = labels["msg_off"] - pd.CAVE
    assert cave[off : cave.index(b"\0", off)] == b"Developer key menus - OFF"


def test_va_to_offset():
    sections = [dict(va=0x1000, vsize=0x500, rsize=0x600, raw=0x400)]
    assert pd.va_to_offset(sections, pd.IMAGE_BASE + 0x1010) == 0x410
    with pytest.raises(SystemExit):
        pd.va_to_offset(sections, pd.IMAGE_BASE + 0x1600)


def test_section_table_rejects_non_pe():
    data = bytearray(0x100)
    struct.pack_into("<I", data, 0x3C, 0x80)
    with pytest.raises(SystemExit, match="not a PE file"):
        pd.section_table(bytes(data))


def test_input_is_required():
    with pytest.raises(SystemExit):
        pd.parse_args([])


def test_refuses_unknown_build(tmp_path):
    src = tmp_path / "runblack.exe"
    src.write_bytes(b"MZ" + bytes(100))
    out = tmp_path / "out.exe"
    with pytest.raises(SystemExit, match="unofficial 1.42"):
        pd.main([str(src), "-o", str(out)])
    assert not out.exists()


@pytest.mark.skipif(not os.environ.get("RUNBLACK_EXE"), reason="set RUNBLACK_EXE to the 1.42 runblack.exe")
def test_patches_known_build(tmp_path):
    src = Path(os.environ["RUNBLACK_EXE"])
    before = src.read_bytes()
    out = tmp_path / "runblack_devmenus.exe"
    assert pd.main([str(src), "-o", str(out)]) == 0
    assert src.read_bytes() == before
    assert hashlib.sha256(out.read_bytes()).hexdigest() == PATCHED_SHA256
    with pytest.raises(SystemExit, match="same file"):
        pd.main([str(src), "-o", str(src)])
