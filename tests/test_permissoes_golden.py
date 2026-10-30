"""As permissões de hoje não podem mudar por acidente: compara o status HTTP de cada rota × papel com a
matriz gravada a partir da tag base (tests/golden/permissoes-2.1.json)."""
import json, sys, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "tools"))
import gen_permission_golden as G  # noqa: E402
import helpers as H  # noqa: E402

GOLDEN = HERE / "golden" / "permissoes-2.1.json"
# mudanças intencionais de comportamento (documentadas no CHANGELOG): (chave, papel) → status novo
ALLOWED = {("POST /api/import#replace", "editor"): 403}


class PermissoesGolden(unittest.TestCase):
    def test_matriz_igual_a_da_base(self):
        golden = json.loads(GOLDEN.read_text("utf-8"))["statuses"]
        routes = sorted({k.split("#")[0] for k in golden if k != "POST /api/import#replace"})
        got = G.collect(H.APP_DIR, routes=routes)
        diffs = []
        for key, exp in golden.items():
            for role, st in exp.items():
                now = got.get(key, {}).get(role)
                if now != st and ALLOWED.get((key, role)) != now:
                    diffs.append(f"{key} [{role}]: base {st}, agora {now}")
        self.assertEqual(diffs, [], "permissões mudaram:\n" + "\n".join(diffs))


if __name__ == "__main__":
    unittest.main()
