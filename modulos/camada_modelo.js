/* Camada do modelo numérico desenhada no navegador (Leaflet).
 *
 * Recebe uma grade regular (lat0, dlat, nlat, lon0, dlon, nlon) com:
 *   u, v  -> desenha SETAS (cor = velocidade)      [tipo "vetor"]
 *   s     -> desenha um CAMPO COLORIDO             [tipo "escalar"]
 *
 * A cada zoom ou arrasto, apaga e redesenha: as setas ficam sempre a
 * ~34 px uma da outra na tela, então aparecem mais setas quando você aproxima.
 * O valor em cada ponto vem de interpolação bilinear entre os 4 pontos da grade.
 */
if (!L.CamadaModelo) {
  L.CamadaModelo = L.Layer.extend({
    initialize: function (grade, opcoes) {
      this._g = grade;
      L.setOptions(this, opcoes);
    },

    onAdd: function (map) {
      this._map = map;
      this._canvas = L.DomUtil.create("canvas", "leaflet-zoom-hide");
      this._canvas.style.pointerEvents = "none";
      map.getPanes().overlayPane.appendChild(this._canvas);
      map.on("moveend zoomend resize", this._desenhar, this);
      map.on("mousemove", this._ler, this);
      this._legenda = this._criarLegenda().addTo(map);
      this._desenhar();
    },

    onRemove: function (map) {
      L.DomUtil.remove(this._canvas);
      map.off("moveend zoomend resize", this._desenhar, this);
      map.off("mousemove", this._ler, this);
      if (this._legenda) map.removeControl(this._legenda);
    },

    // ---- valor da grade num ponto qualquer (interpolação bilinear) ----
    _valor: function (lat, lon, campo) {
      var g = this._g;
      var fi = (lat - g.lat0) / g.dlat, fj = (lon - g.lon0) / g.dlon;
      if (fi < 0 || fj < 0 || fi > g.nlat - 1 || fj > g.nlon - 1) return null;
      var i = Math.min(Math.floor(fi), g.nlat - 2), j = Math.min(Math.floor(fj), g.nlon - 2);
      var a = fi - i, b = fj - j, n = g.nlon, c = g[campo];
      return (1 - a) * ((1 - b) * c[i * n + j] + b * c[i * n + j + 1]) +
             a * ((1 - b) * c[(i + 1) * n + j] + b * c[(i + 1) * n + j + 1]);
    },

    // ---- valor -> cor, pela escala recebida do Python ----
    _cor: function (x, alfa) {
      var e = this.options.escala;
      if (x <= e[0][0]) return this._hex(e[0][1], alfa);
      for (var k = 1; k < e.length; k++) {
        if (x <= e[k][0]) {
          var t = (x - e[k - 1][0]) / (e[k][0] - e[k - 1][0]);
          var c1 = this._rgb(e[k - 1][1]), c2 = this._rgb(e[k][1]);
          return "rgba(" + Math.round(c1[0] + t * (c2[0] - c1[0])) + "," +
                 Math.round(c1[1] + t * (c2[1] - c1[1])) + "," +
                 Math.round(c1[2] + t * (c2[2] - c1[2])) + "," + alfa + ")";
        }
      }
      return this._hex(e[e.length - 1][1], alfa);
    },
    _rgb: function (h) { return [1, 3, 5].map(function (p) { return parseInt(h.substr(p, 2), 16); }); },
    _hex: function (h, alfa) { var c = this._rgb(h); return "rgba(" + c.join(",") + "," + alfa + ")"; },

    // ---- desenho ----
    _desenhar: function () {
      var map = this._map, tam = map.getSize(), cv = this._canvas;
      L.DomUtil.setPosition(cv, map.containerPointToLayerPoint([0, 0]));
      var dpr = window.devicePixelRatio || 1;
      cv.width = tam.x * dpr; cv.height = tam.y * dpr;
      cv.style.width = tam.x + "px"; cv.style.height = tam.y + "px";
      var ctx = cv.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, tam.x, tam.y);
      if (this.options.tipo === "vetor") this._setas(ctx, tam);
      else this._campo(ctx, tam);
    },

    _setas: function (ctx, tam) {
      var esp = this.options.espaco, comp = esp * 0.78, map = this._map;
      ctx.lineCap = "round"; ctx.lineJoin = "round";
      for (var y = esp / 2; y < tam.y; y += esp) {
        for (var x = esp / 2; x < tam.x; x += esp) {
          var ll = map.containerPointToLatLng([x, y]);
          var u = this._valor(ll.lat, ll.lng, "u");
          if (u === null) continue;
          var v = this._valor(ll.lat, ll.lng, "v");
          var vel = Math.sqrt(u * u + v * v);
          if (vel < 0.5) continue;
          // na tela o "y" cresce para baixo, por isso o sinal de v é invertido
          var dx = u / vel, dy = -v / vel;
          var x0 = x - dx * comp / 2, y0 = y - dy * comp / 2;
          var x1 = x + dx * comp / 2, y1 = y + dy * comp / 2;
          var ponta = 6, ang = Math.atan2(dy, dx);
          var caminho = function () {
            ctx.beginPath();
            ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
            ctx.moveTo(x1 - ponta * Math.cos(ang - 0.45), y1 - ponta * Math.sin(ang - 0.45));
            ctx.lineTo(x1, y1);
            ctx.lineTo(x1 - ponta * Math.cos(ang + 0.45), y1 - ponta * Math.sin(ang + 0.45));
          };
          caminho(); ctx.strokeStyle = "rgba(0,0,0,0.55)"; ctx.lineWidth = 3.4; ctx.stroke();  // contorno
          caminho(); ctx.strokeStyle = this._cor(vel, 1); ctx.lineWidth = 1.8; ctx.stroke();
        }
      }
    },

    _campo: function (ctx, tam) {
      var bloco = 6, map = this._map;
      for (var y = 0; y < tam.y; y += bloco) {
        for (var x = 0; x < tam.x; x += bloco) {
          var ll = map.containerPointToLatLng([x + bloco / 2, y + bloco / 2]);
          var s = this._valor(ll.lat, ll.lng, "s");
          if (s === null) continue;
          ctx.fillStyle = this._cor(s, 0.55);
          ctx.fillRect(x, y, bloco, bloco);
        }
      }
    },

    // ---- legenda com barra de cores + leitura do valor sob o mouse ----
    _criarLegenda: function () {
      var o = this.options, e = o.escala, min = e[0][0], max = e[e.length - 1][0];
      var paradas = e.map(function (p) {
        return p[1] + " " + ((p[0] - min) / (max - min) * 100).toFixed(1) + "%";
      }).join(",");
      var ticks = e.filter(function (p, k) { return k % 2 === 0 || k === e.length - 1; })
                   .map(function (p) { return "<span>" + p[0] + "</span>"; }).join("");
      var ctl = L.control({ position: "bottomleft" }), self = this;
      ctl.onAdd = function () {
        var d = L.DomUtil.create("div", "legenda-mapa");
        d.innerHTML = "<b>" + o.titulo + "</b> (" + o.unidade + ")" +
          "<div class='barra' style='background:linear-gradient(to right," + paradas + ")'></div>" +
          "<div class='ticks'>" + ticks + "</div><div class='leitura'></div>";
        self._leitura = d.querySelector(".leitura");
        return d;
      };
      return ctl;
    },

    _ler: function (ev) {
      if (!this._leitura) return;
      var lat = ev.latlng.lat, lon = ev.latlng.lng, txt = "";
      if (this.options.tipo === "vetor") {
        var u = this._valor(lat, lon, "u"), v = this._valor(lat, lon, "v");
        if (u !== null) {
          var vel = Math.sqrt(u * u + v * v);
          // direção meteorológica: de onde o vento VEM (0° = norte)
          var dir = (Math.atan2(-u, -v) * 180 / Math.PI + 360) % 360;
          var d10 = Math.round(dir / 10) * 10 || 360;          // aviação usa 360, não 000
          txt = "sob o cursor: " + ("00" + d10).slice(-3) + "° / " + Math.round(vel) + " kt";
        }
      } else {
        var s = this._valor(lat, lon, "s");
        if (s !== null) txt = "sob o cursor: " + s.toFixed(1) + " " + this.options.unidade;
      }
      this._leitura.textContent = txt;
    }
  });
}
