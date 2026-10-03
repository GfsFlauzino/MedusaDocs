/* Aplica tema (claro/escuro) e cor da marca antes da primeira pintura, a partir do que ficou salvo no navegador. */
(function () {
  try {
    var root = document.documentElement;
    var t = localStorage.getItem("medusa-theme");
    root.dataset.theme = t || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    var b = JSON.parse(localStorage.getItem("medusa-brand") || "null");
    if (b && b.vars) for (var k in b.vars) root.style.setProperty(k, b.vars[k]);
    if (b && b.name) document.title = b.name;
  } catch (e) { document.documentElement.dataset.theme = "light"; }
})();
