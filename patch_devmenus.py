#!/usr/bin/env python3
"""Make a copy of Black & White's runblack.exe whose developer key menus can be switched on while playing.

Usage:
    python patch_devmenus.py INPUT [-o OUTPUT]

INPUT is the game's runblack.exe and is only read. The patched copy is written to OUTPUT, by default
runblack_devmenus.exe in the current directory. The script only accepts runblack.exe from the
unofficial 1.42 patch, decrypted (checked by SHA-256), and checks every patched site still holds the original
bytes before changing it.

Python 3 standard library only. See README.md for what the patch does.
"""

import argparse
import hashlib
import struct
import sys
from pathlib import Path

DEFAULT_OUTPUT_NAME = "runblack_devmenus.exe"

# runblack.exe from the unofficial 1.42 patch, the only build this patch was made and checked against.
EXPECTED_SHA256 = "3f58bc02a6c421b4e66ef08716646bf0e1fa55ab292786edb521d7596ed48aba"
EXPECTED_SIZE = 8663040

IMAGE_BASE = 0x400000

# ---------------------------------------------------------------------------------------------------
# Addresses in the original program (virtual addresses).
# ---------------------------------------------------------------------------------------------------
# fmt: off
HOOK_SITE = 0x63F2C6        # in the game's key handler, where an ordinary in-world key starts the
                             # bindable-action lookup
HOOK_RESUME = 0x63F2CE       # first instruction after the two we move into the stub
KEY_EXIT = 0x63F695          # the key handler's shared "done" exit (pops, add esp 8, ret 8)
PRINT_DEBUG_TEXT = 0x63ED40  # cdecl (const char* text, int append): writes the developers' on-screen text
GAME_PTR = 0xD0195C          # the global game object pointer
SHIFT_MASK_WORD = 0x9A161C   # the word the key handler reads its Shift mask from

MENU_JEREMY = 0x640CC0       # (key, mods), callee pops 8
MENU_TIM = 0x640FA0          # (key, mods), caller pops (cdecl)
MENU_GEORGE = 0x641080       # (key, mods), callee pops 8
MENU_TOM = 0x641570          # (key, mods), caller pops (cdecl)
MENU_UNNAMED = 0x641010      # (key, mods), callee pops 8; only reacts to A

CAVE = 0x8A8960              # unused zero bytes at the end of .text (raw data, past VirtualSize)
CAVE_END = 0x8A9000
STATE = 0xFBFE00             # one byte in the unused tail of .data's last page: selected menu, 0 = off

MOD_SHIFT, MOD_CTRL, MOD_ALT = 0x10, 0x20, 0x40   # the game's own modifier bits (read from .rdata)

# DirectInput scan codes, which the game uses as its key numbers.
K = dict(N1=0x02, N3=0x04, N5=0x06, N0=0x0B, W=0x11, R=0x13, I=0x17, O=0x18, A=0x1E, S=0x1F,
         F=0x21, H=0x23, K=0x25, Z=0x2C, C=0x2E, B=0x30, M=0x32)
# fmt: on


# ---------------------------------------------------------------------------------------------------
# A very small two-pass assembler: a list of byte strings and label-relative fixups.
# ---------------------------------------------------------------------------------------------------
class Asm:
    def __init__(self, origin):
        self.origin = origin
        self.items = []  # (kind, payload)
        self.labels = {}

    def label(self, name):
        self.items.append(("label", name))

    def raw(self, data):
        self.items.append(("raw", bytes(data)))

    def rel32(self, opcode, target):
        """opcode bytes followed by a rel32 to a label name or an absolute address."""
        self.items.append(("rel", (bytes(opcode), target)))

    def abs32(self, prefix, target, suffix=b""):
        """prefix bytes, then the absolute address of a label (or an int), then suffix bytes."""
        self.items.append(("abs", (bytes(prefix), target, bytes(suffix))))

    def _size(self, kind, payload):
        if kind == "label":
            return 0
        if kind == "raw":
            return len(payload)
        if kind == "rel":
            return len(payload[0]) + 4
        return len(payload[0]) + 4 + len(payload[2])

    def size(self):
        return sum(self._size(k, p) for k, p in self.items)

    def assemble(self):
        addr = self.origin
        for kind, payload in self.items:
            if kind == "label":
                if payload in self.labels:
                    raise ValueError(f"duplicate label {payload}")
                self.labels[payload] = addr
            addr += self._size(kind, payload)
        out = bytearray()
        addr = self.origin

        def resolve(t):
            if isinstance(t, tuple):
                return self.labels[t[0]] + t[1]
            return self.labels[t] if isinstance(t, str) else t

        for kind, payload in self.items:
            size = self._size(kind, payload)
            if kind == "raw":
                out += payload
            elif kind == "rel":
                op, target = payload
                out += op + struct.pack("<i", resolve(target) - (addr + size))
            elif kind == "abs":
                prefix, target, suffix = payload
                out += prefix + struct.pack("<I", resolve(target)) + suffix
            addr += size
        return bytes(out)


def cstr(text):
    return text.encode("ascii") + b"\0"


def build_cave():
    # fmt: off
    a = Asm(CAVE)
    JE, JNE, JA, JZ = b"\x0f\x84", b"\x0f\x85", b"\x0f\x87", b"\x0f\x84"
    CALL, JMP = b"\xe8", b"\xe9"

    # ---- hook: entered by the jump at HOOK_SITE. esi = key, edi = modifier word. -----------------
    a.label("hook")
    a.raw(b"\x60")                              # pushad
    a.raw(b"\x0f\xb7\xd7")                      # movzx edx, di            ; edx = modifiers
    a.raw(b"\x8b\xc2")                          # mov eax, edx
    a.raw(b"\x83\xe0" + bytes([MOD_SHIFT | MOD_CTRL | MOD_ALT]))   # and eax, 0x70
    a.raw(b"\x83\xf8" + bytes([MOD_CTRL | MOD_ALT]))               # cmp eax, 0x60 (Ctrl+Alt, no Shift)
    a.rel32(JNE, "routed_keys")
    a.raw(b"\x83\xfe" + bytes([K["N0"]]))       # cmp esi, DIK_0
    a.rel32(JE, "turn_off")
    a.raw(b"\x8d\x46\xfe")                      # lea eax, [esi-2]          ; DIK_1..DIK_5 -> 0..4
    a.raw(b"\x83\xf8\x04")                      # cmp eax, 4
    a.rel32(JA, "routed_keys")
    a.raw(b"\x40")                              # inc eax                   ; menu number 1..5
    a.abs32(b"\x3a\x05", STATE)                 # cmp al, [state]
    a.rel32(JE, "turn_off")                     # same menu again: switch off
    a.abs32(b"\xa2", STATE)                     # mov [state], al
    a.raw(b"\x6a\x00")                          # push 0                    ; modifiers
    a.raw(b"\x6a" + bytes([K["H"]]))            # push DIK_H                ; show the menu's help page
    a.rel32(CALL, "call_menu")
    a.rel32(JMP, "consumed")

    a.label("turn_off")
    a.abs32(b"\xc6\x05", STATE, b"\x00")        # mov byte [state], 0
    a.raw(b"\x6a\x00")                          # push 0                    ; replace the text
    a.abs32(b"\x68", "msg_off")                 # push msg_off
    a.rel32(CALL, PRINT_DEBUG_TEXT)
    a.raw(b"\x83\xc4\x08")                      # add esp, 8
    a.rel32(JMP, "consumed")

    # While a menu is selected, keys on its list go to it instead of the game.
    a.label("routed_keys")
    a.abs32(b"\x0f\xb6\x05", STATE)             # movzx eax, byte [state]
    a.raw(b"\x85\xc0")                          # test eax, eax
    a.rel32(JZ, "pass")
    a.abs32(b"\x8b\x0c\x85", ("key_lists", -4))  # mov ecx, [eax*4 + key_lists-4]
    a.label("scan")
    a.raw(b"\x0f\xb6\x01")                      # movzx eax, byte [ecx]     ; key, 0 ends the list
    a.raw(b"\x85\xc0")                          # test eax, eax
    a.rel32(JZ, "pass")
    a.raw(b"\x3b\xc6")                          # cmp eax, esi
    a.rel32(JNE, "next")
    a.raw(b"\x0f\xb6\x41\x01")                  # movzx eax, byte [ecx+1]   ; modifiers it needs, 0 = any
    a.raw(b"\x85\xc0")                          # test eax, eax
    a.rel32(JZ, "matched")
    a.raw(b"\x85\xd0")                          # test eax, edx
    a.rel32(JNE, "matched")
    a.label("next")
    a.raw(b"\x83\xc1\x02")                      # add ecx, 2
    a.rel32(JMP, "scan")
    a.label("matched")
    a.raw(b"\x52")                              # push edx                  ; modifiers
    a.raw(b"\x56")                              # push esi                  ; key
    a.rel32(CALL, "call_menu")
    a.label("consumed")
    a.raw(b"\x61")                              # popad
    a.rel32(JMP, KEY_EXIT)

    a.label("pass")
    a.raw(b"\x61")                              # popad
    a.raw(b"\x33\xc0")                          # xor eax, eax              ; the two moved instructions
    a.abs32(b"\x66\xa1", SHIFT_MASK_WORD)       # mov ax, [shift mask]
    a.rel32(JMP, HOOK_RESUME)

    # ---- call_menu(key, mods): stdcall helper, calls the selected developer handler. -------------
    a.label("call_menu")
    a.raw(b"\xff\x74\x24\x08")                  # push dword [esp+8]        ; mods
    a.raw(b"\xff\x74\x24\x08")                  # push dword [esp+8]        ; key
    a.abs32(b"\x0f\xb6\x05", STATE)             # movzx eax, byte [state]
    a.abs32(b"\x8b\x0d", GAME_PTR)              # mov ecx, [game]           ; 'this' for Jeremy's handler
    a.raw(b"\x83\xf8\x01"); a.rel32(JE, "m_jeremy")
    a.raw(b"\x83\xf8\x02"); a.rel32(JE, "m_tim")
    a.raw(b"\x83\xf8\x03"); a.rel32(JE, "m_george")
    a.raw(b"\x83\xf8\x04"); a.rel32(JE, "m_tom")
    a.raw(b"\x83\x3c\x24" + bytes([K["H"]]))    # cmp dword [esp], DIK_H
    a.rel32(JE, "m_unnamed_help")
    a.rel32(CALL, MENU_UNNAMED)                 # pops its own 8 bytes
    a.rel32(JMP, "after")
    a.label("m_unnamed_help")
    a.raw(b"\x83\xc4\x08")                      # add esp, 8
    a.raw(b"\x6a\x00"); a.abs32(b"\x68", "msg_unnamed_title")
    a.rel32(CALL, PRINT_DEBUG_TEXT); a.raw(b"\x83\xc4\x08")
    a.raw(b"\x6a\x01"); a.abs32(b"\x68", "msg_unnamed_a")
    a.rel32(CALL, PRINT_DEBUG_TEXT); a.raw(b"\x83\xc4\x08")
    a.rel32(JMP, "after")
    a.label("m_jeremy")
    a.rel32(CALL, MENU_JEREMY)                  # pops its own 8 bytes
    a.rel32(JMP, "after")
    a.label("m_george")
    a.rel32(CALL, MENU_GEORGE)                  # pops its own 8 bytes
    a.rel32(JMP, "after")
    a.label("m_tim")
    a.rel32(CALL, MENU_TIM)
    a.raw(b"\x83\xc4\x08")                      # add esp, 8
    a.rel32(JMP, "after")
    a.label("m_tom")
    a.rel32(CALL, MENU_TOM)
    a.raw(b"\x83\xc4\x08")                      # add esp, 8
    a.label("after")
    a.raw(b"\x83\x7c\x24\x04" + bytes([K["H"]]))  # cmp dword [esp+4], DIK_H  ; help page shown?
    a.rel32(JNE, "done")
    a.abs32(b"\x0f\xb6\x05", STATE)             # movzx eax, byte [state]
    a.abs32(b"\x8b\x0c\x85", ("notes", -4))     # mov ecx, [eax*4 + notes-4]
    a.raw(b"\x85\xc9")                          # test ecx, ecx
    a.rel32(JZ, "done")
    a.raw(b"\x6a\x01")                          # push 1                    ; append a line
    a.raw(b"\x51")                              # push ecx
    a.rel32(CALL, PRINT_DEBUG_TEXT)
    a.raw(b"\x83\xc4\x08")                      # add esp, 8
    a.label("done")
    a.raw(b"\xc2\x08\x00")                      # ret 8

    # ---- data -------------------------------------------------------------------------------
    a.raw(b"\xcc" * ((-a.size()) % 4))           # pad to 4 (int3, never executed)
    a.label("key_lists")
    for name in ("keys_jeremy", "keys_tim", "keys_george", "keys_tom", "keys_unnamed"):
        a.abs32(b"", name)
    a.label("notes")
    for name in ("note_jeremy", "note_tim", "note_george", "note_tom"):
        a.abs32(b"", name)
    a.raw(b"\0\0\0\0")                          # no note for the unnamed menu

    def keys(label, entries):
        a.label(label)
        a.raw(b"".join(bytes([k, m]) for k, m in entries) + b"\0\0")

    keys("keys_jeremy", [(K["H"], 0), (K["K"], 0), (K["C"], 0), (K["I"], 0), (K["O"], 0), (K["M"], 0),
                         (K["F"], 0), (K["R"], 0), (K["W"], 0), (K["Z"], 0)])
    keys("keys_tim", [(K["H"], 0), (K["O"], 0)])
    keys("keys_george", [(K["H"], 0), (K["W"], 0), (K["S"], MOD_SHIFT | MOD_ALT), (K["A"], 0), (K["C"], 0),
                         (K["B"], 0), (K["N3"], 0)])
    keys("keys_tom", [(K["H"], 0), (K["W"], 0), (K["F"], MOD_SHIFT)])
    keys("keys_unnamed", [(K["H"], 0), (K["A"], MOD_SHIFT)])

    for label, text in (
        ("msg_off", "Developer key menus - OFF"),
        ("msg_unnamed_title", "Unnamed Profile - HELP KEY MENU"),
        ("msg_unnamed_a", "Shift + A - Computer takes over your god (no undo)"),
        ("note_jeremy", "(patch) Only W and Z change anything in this build"),
        ("note_tim", "(patch) O does nothing in this build"),
        ("note_george", "(patch) Shift + W reload, A mail, B/C weather, 3 log, Alt/Shift + S"),
        ("note_tom", "(patch) Shift + F only: deletes and rebuilds all footpath files"),
    ):
        a.label(label)
        a.raw(cstr(text))
    # fmt: on

    code = a.assemble()
    return code, a.labels


def build_patches():
    """Return the stub, its labels and the list of (description, address, original bytes, new bytes)."""
    cave, labels = build_cave()
    if CAVE + len(cave) > CAVE_END:
        raise SystemExit("internal error: the stub does not fit in the cave")
    hook_jump = b"\xe9" + struct.pack("<i", labels["hook"] - (HOOK_SITE + 5)) + b"\x90\x90\x90"
    return (
        cave,
        labels,
        [
            ("jump from the key handler into the stub", HOOK_SITE, bytes.fromhex("33c066a11c169a00"), hook_jump),
            ("stub, key tables and messages in the unused end of .text", CAVE, bytes(len(cave)), cave),
        ],
    )


def section_table(data):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe : pe + 4] != b"PE\0\0":
        raise SystemExit("not a PE file")
    count = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    base = struct.unpack_from("<I", data, pe + 24 + 28)[0]
    table = pe + 24 + opt_size
    sections = []
    for i in range(count):
        off = table + 40 * i
        name, vsize, va, rsize, raw = struct.unpack_from("<8sIIII", data, off)
        sections.append(dict(name=name.rstrip(b"\0").decode(), hdr=off, vsize=vsize, va=va, rsize=rsize, raw=raw))
    return base, sections


def va_to_offset(sections, va):
    rva = va - IMAGE_BASE
    for s in sections:
        if s["va"] <= rva < s["va"] + max(s["vsize"], s["rsize"]) and rva - s["va"] < s["rsize"]:
            return s["raw"] + rva - s["va"]
    raise SystemExit(f"address {va:#x} is not backed by file data")


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Make a copy of Black & White's runblack.exe whose developer key menus can be "
        "switched on while playing. The input is only read."
    )
    parser.add_argument("input", type=Path, help="runblack.exe from the unofficial 1.42 patch")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path(DEFAULT_OUTPUT_NAME),
        help=f"where to write the patched copy (default: {DEFAULT_OUTPUT_NAME} in the current directory)",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    src, output = args.input, args.output
    data = src.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != EXPECTED_SHA256 or len(data) != EXPECTED_SIZE:
        raise SystemExit(
            f"refusing: {src} is not runblack.exe from the unofficial 1.42 patch, decrypted (size {len(data)}, sha256 {digest})"
        )
    print(f"input: {src}")
    if src.resolve() == output.resolve():
        raise SystemExit("refusing: input and output are the same file")

    base, sections = section_table(data)
    if base != IMAGE_BASE:
        raise SystemExit("unexpected image base")
    by_name = {s["name"]: s for s in sections}
    text, sdata = by_name[".text"], by_name[".data"]
    expected_headers = [(text, 0x4A795D, 0x4A8000), (sdata, 0x5F9E00, 0x5FA000)]

    out = bytearray(data)
    cave, labels, patches = build_patches()

    # Section header edits: let the loader treat the cave and the state byte as part of their sections.
    for sec, old, new in expected_headers:
        cur = struct.unpack_from("<I", out, sec["hdr"] + 8)[0]
        if cur != old:
            raise SystemExit(f"{sec['name']} VirtualSize is {cur:#x}, expected {old:#x}")
        struct.pack_into("<I", out, sec["hdr"] + 8, new)
        print(f"  header {sec['name']} VirtualSize {old:#x} -> {new:#x} (file offset {sec['hdr'] + 8:#x})")
    # The state byte must lie in the newly covered, zero-initialised tail of .data.
    if not (sdata["va"] + 0x5F9E00 <= STATE - IMAGE_BASE < sdata["va"] + 0x5FA000):
        raise SystemExit("internal error: state byte outside the .data tail")
    # The cave must lie in the newly covered tail of .text.
    if not (text["va"] + 0x4A795D <= CAVE - IMAGE_BASE and CAVE_END - IMAGE_BASE <= text["va"] + text["rsize"]):
        raise SystemExit("internal error: cave outside the .text tail")

    for desc, va, original, new in patches:
        off = va_to_offset(sections, va)
        if bytes(out[off : off + len(original)]) != original:
            raise SystemExit(f"refusing: bytes at {va:#x} are not the expected original ({desc})")
        out[off : off + len(new)] = new
        print(f"  {va:#010x} (file {off:#x}) {len(new)} bytes: {desc}")

    output.write_bytes(out)
    print(f"wrote {output} (sha256 {hashlib.sha256(out).hexdigest()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
