"""Tests de la línea de comandos."""
from merchbot.__main__ import build_parser


def test_subcomandos():
    parser = build_parser()
    assert parser.parse_args(["web", "--port", "9000"]).port == 9000
    assert parser.parse_args(["telegram"]).comando == "telegram"
    assert parser.parse_args(["cargar-demo"]).comando == "cargar-demo"


def test_sin_subcomando_no_falla_el_parseo():
    assert build_parser().parse_args([]).comando is None
