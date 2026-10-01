from src.hexlauncher.palette import BG, CYAN, CYAN_H, MUTED, WHITE


def test_palette_constants_are_hex():
    for color in (BG, CYAN, CYAN_H, MUTED, WHITE):
        assert color.startswith("#"), f"Color {color!r} should be hex"
        assert len(color) == 7, f"Color {color!r} should be 7 chars (#RRGGBB)"


def test_hover_is_darker_than_base():
    # CYAN_H debe ser un tono más oscuro de CYAN (heurística simple: H verde < H base)
    assert int(CYAN_H[3:5], 16) < int(CYAN[3:5], 16)
