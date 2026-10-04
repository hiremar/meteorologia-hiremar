/* Camada das descargas atmosféricas (raios), desenhada no navegador (Leaflet).
 *
 * Recebe uma lista [[lat, lon, faixa], ...], com faixa 0 = mais recente
 * (vermelho) até 3 = mais antiga (azul), e desenha um "raio" (zigue-zague)
 * em cada ponto.
 *
 * Por que num <canvas> e não um marcador por raio? Em dia de muita convecção
 * são milhares de pontos. Milhares de marcadores deixam o celular lento;
 * um canvas é uma única "folha" onde pintamos tudo de uma vez.
 */
if (!L.CamadaRaios) {
  L.CamadaRaios = L.Layer.extend({
    initialize: function (pontos, opcoes) {
      this._p = pontos;
      L.setOptions(this, opcoes);
    },

    onAdd: function (map) {
      this._map = map;
      this._canvas = L.DomUtil.create("canvas", "leaflet-zoom-hide");
      this._canvas.style.pointerEvents = "none";      // cliques "atravessam" a camada
      map.getPanes().overlayPane.appendChild(this._canvas);
      map.on("moveend zoomend resize", this._desenhar, this);
      this._desenhar();
    },

    onRemove: function (map) {
      L.DomUtil.remove(this._canvas);
      map.off("moveend zoomend resize", this._desenhar, this);
    },

    _desenhar: function () {
      var map = this._map, tam = map.getSize(), cv = this._canvas;
      L.DomUtil.setPosition(cv, map.containerPointToLayerPoint([0, 0]));
      var dpr = window.devicePixelRatio || 1;          // telas de celular têm mais pixels
      cv.width = tam.x * dpr; cv.height = tam.y * dpr;
      cv.style.width = tam.x + "px"; cv.style.height = tam.y + "px";
      var ctx = cv.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, tam.x, tam.y);

      // tamanho do raio (px) conforme o zoom: pequeno de longe, maior de perto
      var z = map.getZoom();
      var t = z <= 4 ? 8 : (z <= 6 ? 11 : 15);
      var area = map.getBounds().pad(0.05);            // só desenha o que está na tela
      var cores = this.options.cores;

      // do mais antigo (3, azul) para o mais novo (0, vermelho): o vermelho fica por cima
      for (var f = 3; f >= 0; f--) {
        ctx.beginPath();
        for (var k = 0; k < this._p.length; k++) {
          var p = this._p[k];
          if (p[2] !== f || !area.contains([p[0], p[1]])) continue;
          var c = map.latLngToContainerPoint([p[0], p[1]]);
          this._raio(ctx, c.x, c.y, t);
        }
        ctx.fillStyle = cores[f];
        ctx.fill();
        ctx.lineWidth = 0.8;
        ctx.strokeStyle = "rgba(0,0,0,0.7)";            // contorno escuro: aparece em qualquer fundo
        ctx.stroke();
      }
    },

    // Desenha um raio de altura t, centrado em (x, y).
    // Cada par é um "canto" do desenho, em frações da altura (−0,5 = topo, +0,5 = base).
    _raio: function (ctx, x, y, t) {
      var F = [[0.10, -0.5], [-0.30, 0.05], [0.00, 0.05], [-0.15, 0.5],
               [0.30, -0.10], [0.02, -0.10], [0.22, -0.5]];
      ctx.moveTo(x + F[0][0] * t, y + F[0][1] * t);
      for (var i = 1; i < F.length; i++) ctx.lineTo(x + F[i][0] * t, y + F[i][1] * t);
      ctx.closePath();
    }
  });
}
