"""Caracterização do parser de Markdown (pbcore.parse_md / doc_to_md).

Os casos marcados com expectedFailure descrevem o que o parser ainda NÃO faz (listas numeradas, blocos de
código, texto entre o título e a primeira seção). A Fase 3 implementa e remove as marcas.
"""
import hashlib, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pbcore as core  # noqa: E402

FIX = HERE / "fixtures" / "md"


def read(name):
    return (FIX / name).read_text("utf-8")


def all_blocks(doc):
    for s in doc["sections"]:
        yield from s["blocks"]
        for x in s["subs"]: yield from x["blocks"]


class IdaEVolta(unittest.TestCase):
    def test_estavel_depois_da_primeira_gravacao(self):
        for f in sorted(FIX.glob("*.md")):
            with self.subTest(arquivo=f.name):
                once = core.doc_to_md(core.parse_md(f.read_text("utf-8")))
                twice = core.doc_to_md(core.parse_md(once))
                self.assertEqual(once, twice)

    def test_playbook_do_template_padrao_nao_muda(self):
        text = read("padrao-pb-01.md")
        h = lambda s: hashlib.sha256(s.encode()).hexdigest()
        self.assertEqual(h(core.doc_to_md(core.parse_md(text))), h(text))

    def test_tabelas_e_listas_simples(self):
        doc = core.parse_md(read("padrao-pb-01.md"))
        kinds = {b["t"] for b in all_blocks(doc)}
        self.assertTrue({"table", "ul", "p"} <= kinds)


class CasosQueAindaFalham(unittest.TestCase):
    def setUp(self):
        self.doc = core.parse_md(read("runbook-blocos.md"))

    @unittest.expectedFailure
    def test_lista_numerada(self):
        ol = [b for b in all_blocks(self.doc) if b["t"] == "ol"]
        self.assertTrue(ol and ol[0]["items"][0].startswith("Abrir a console"))

    @unittest.expectedFailure
    def test_bloco_de_codigo(self):
        code = [b for b in all_blocks(self.doc) if b["t"] == "code"]
        self.assertTrue(code)
        self.assertEqual(code[0].get("lang"), "bash")
        self.assertIn('edrctl isolate --host "$HOST"', code[0]["text"])
        self.assertIn("\n", code[0]["text"])

    @unittest.expectedFailure
    def test_introducao_preservada(self):
        md = core.doc_to_md(self.doc)
        self.assertIn("O texto entre o título e a primeira seção", md)

    @unittest.expectedFailure
    def test_lista_com_asterisco_e_mais(self):
        sec = next(s for s in self.doc["sections"] if s["title"] == "Pré-requisitos")
        self.assertEqual([b["t"] for b in sec["blocks"]], ["ul"])
        self.assertEqual(len(sec["blocks"][0]["items"]), 3)


if __name__ == "__main__":
    unittest.main()
