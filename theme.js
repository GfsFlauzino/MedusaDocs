/* Aplica o tema (claro/escuro) antes da primeira pintura, a partir do que ficou salvo no navegador.
   O visual é fixo: só o tema, a logo e o nome do workspace mudam. */
(function () {
  try {
    var root = document.documentElement;
    var t = localStorage.getItem("medusa-theme");
    root.dataset.theme = t || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
    var b = JSON.parse(localStorage.getItem("medusa-brand") || "null");
    if (b && b.name) document.title = b.name;
  } catch (e) { document.documentElement.dataset.theme = "light"; }
})();
