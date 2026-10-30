"""Parser de Markdown (pbcore.parse_md / doc_to_md / render_blocks): ida e volta, blocos novos (código, lista
numerada, introdução, listas com * e +), links seguros e escape de HTML.
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


class BlocosNovos(unittest.TestCase):
    def setUp(self):
        self.doc = core.parse_md(read("runbook-blocos.md"))

    def test_lista_numerada(self):
        ol = [b for b in all_blocks(self.doc) if b["t"] == "ol"]
        self.assertTrue(ol and ol[0]["items"][0].startswith("Abrir a console"))
        self.assertEqual(ol[1].get("start"), 4)          # lista continuada depois do bloco de código

    def test_bloco_de_codigo(self):
        code = [b for b in all_blocks(self.doc) if b["t"] == "code"]
        self.assertTrue(code)
        self.assertEqual(code[0].get("lang"), "bash")
        self.assertIn('edrctl isolate --host "$HOST"', code[0]["text"])
        self.assertIn("\n", code[0]["text"])

    def test_introducao_preservada(self):
        md = core.doc_to_md(self.doc)
        self.assertIn("O texto entre o título e a primeira seção", md)

    def test_lista_com_asterisco_e_mais(self):
        sec = next(s for s in self.doc["sections"] if s["title"] == "Pré-requisitos")
        self.assertEqual([b["t"] for b in sec["blocks"]], ["ul"])
        self.assertEqual(len(sec["blocks"][0]["items"]), 3)


class Seguranca(unittest.TestCase):
    def html(self, md):
        doc = core.parse_md("# T\n\n## S\n\n" + md + "\n")
        return core.render_blocks(doc["sections"][0]["blocks"])

    def test_link_javascript_vira_texto(self):
        h = self.html("Veja [x](javascript:alert(1)) e [y](data:text/html,oi).")
        self.assertNotIn("<a", h)
        self.assertIn("[x](javascript:alert(1))", h)

    def test_links_permitidos(self):
        h = self.html("[site](https://exemplo.com/a?b=1&c=2) [mail](mailto:soc@exemplo.com) [pb](#/pb-02/doc)")
        self.assertIn('<a href="https://exemplo.com/a?b=1&amp;c=2" target="_blank" rel="noopener noreferrer">site</a>', h)
        self.assertIn('href="mailto:soc@exemplo.com"', h)
        self.assertIn('<a href="#/pb-02/doc">pb</a>', h)

    def test_html_escapado(self):
        h = self.html('<script>alert(1)</script> <img src=x onerror="alert(1)">')
        self.assertNotIn("<script", h)
        self.assertNotIn("<img", h)

    def test_codigo_nao_interpreta_nada(self):
        h = self.html('```html\n<img src=x onerror="alert(1)">\n**negrito** [l](https://x)\n## não é seção\n```')
        self.assertIn("&lt;img src=x onerror=\"alert(1)\"&gt;", h)
        self.assertNotIn("<strong>", h)
        self.assertNotIn("<a ", h)
        self.assertIn('class="code-copy"', h)
        doc = core.parse_md("# T\n\n## S\n\n```\n## dentro\n```\n")
        self.assertEqual(len(doc["sections"]), 1)

    def test_codigo_inline_nao_vira_link(self):
        self.assertIn("<code>[a](https://x)</code>", self.html("use `[a](https://x)` aqui"))


class IdaEVoltaDosBlocos(unittest.TestCase):
    def roundtrip(self, md):
        once = core.doc_to_md(core.parse_md(md))
        self.assertEqual(core.doc_to_md(core.parse_md(once)), once)
        return once

    def test_codigo_com_crases_dentro(self):
        md = self.roundtrip("# T\n\n## S\n\n````md\nexemplo:\n```bash\nls\n```\n````\n")
        self.assertIn("````md", md)
        code = core.parse_md(md)["sections"][0]["blocks"][0]
        self.assertEqual(code["text"], "exemplo:\n```bash\nls\n```")

    def test_tabela_depois_de_lista(self):
        md = self.roundtrip("# T\n\n## S\n\n- item\n| A | B |\n| --- | --- |\n| 1 | 2 |\n")
        self.assertEqual([b["t"] for b in core.parse_md(md)["sections"][0]["blocks"]], ["ul", "table"])

    def test_introducao(self):
        md = self.roundtrip("# T\n\nVersão 1.0\n\nIntrodução.\n\n1. um\n2. dois\n\n## S\n\ntexto\n")
        doc = core.parse_md(md)
        self.assertEqual([b["t"] for b in doc["intro"]], ["p", "ol"])
        self.assertEqual(doc["byline"], "Versão 1.0")

    def test_continuacao_de_item(self):
        md = self.roundtrip("# T\n\n## S\n\n- primeiro\n  continua\n  - sub-item\n- segundo\n")
        items = core.parse_md(md)["sections"][0]["blocks"][0]["items"]
        self.assertEqual(items, ["primeiro\ncontinua\n- sub-item", "segundo"])
        self.assertIn("primeiro<br>continua<br>- sub-item", core.render_blocks(core.parse_md(md)["sections"][0]["blocks"]))


if __name__ == "__main__":
    unittest.main()
