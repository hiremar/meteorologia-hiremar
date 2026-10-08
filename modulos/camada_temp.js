/* Leitura da temperatura do topo das nuvens (GOES-19 IR) onde o mouse está.
 *
 * O Python manda uma "imagem" em tons de cinza em que cada pixel guarda a
 * temperatura: valor = Kelvin - base (255 = sem dado). Aqui o navegador desenha
 * essa imagem num canvas invisível, lê os números uma vez só e, a cada movimento
 * do mouse, converte a posição (lat/lon) no pixel certo e mostra °C e K.
 *
 * As linhas da grade são espaçadas em Mercator (igual à imagem do satélite),
 * por isso a latitude passa pela função _merc antes da regra de três.
 */
if (!L.LeituraTemperatura) {
  L.LeituraTemperatura = L.Control.extend({
    options: { position: "bottomleft" },

    initialize: function (dados, opcoes) {
      this._d = dados;               // {url, base, lat0, lat1, lon0, lon1}
      L.setOptions(this, opcoes);
    },

    onAdd: function (map) {
      var div = L.DomUtil.create("div", "legenda-mapa");
      div.innerHTML = this.options.html;
      this._leitura = div.querySelector(".leitura");
      var self = this, img = new Image();
      img.onload = function () {
        var c = document.createElement("canvas");
        c.width = img.width; c.height = img.height;
        var ctx = c.getContext("2d");
        ctx.drawImage(img, 0, 0);
        self._px = ctx.getImageData(0, 0, img.width, img.height).data;
        self._w = img.width; self._h = img.height;
      };
      img.src = this._d.url;
      this._map = map;
      map.on("mousemove", this._mover, this);
      map.on("mouseout", this._limpar, this);
      L.DomEvent.disableClickPropagation(div);
      return div;
    },

    onRemove: function (map) {
      map.off("mousemove", this._mover, this);
      map.off("mouseout", this._limpar, this);
    },

    _merc: function (lat) {
      return Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
    },

    _limpar: function () {
      this._leitura.innerHTML = "Passe o mouse sobre o mapa";
    },

    _mover: function (e) {
      if (!this._px) return;
      var d = this._d, lat = e.latlng.lat;
      var lon = ((((e.latlng.lng + 180) % 360) + 360) % 360) - 180;   // -180..180 mesmo após dar a volta
      var x = Math.floor(((lon - d.lon0) / (d.lon1 - d.lon0)) * this._w);
      var y = Math.floor(((this._merc(d.lat1) - this._merc(lat)) /
                          (this._merc(d.lat1) - this._merc(d.lat0))) * this._h);
      if (x < 0 || y < 0 || x >= this._w || y >= this._h) { this._limpar(); return; }
      var v = this._px[(y * this._w + x) * 4];          // canal vermelho = cinza
      if (v === 255) { this._leitura.innerHTML = "Sem dado do satélite aqui"; return; }
      var k = v + d.base, c = k - 273.15;
      this._leitura.innerHTML = "Topo/superfície: <b>" + c.toFixed(0).replace("-", "&minus;") +
                                " &deg;C</b> &middot; " + k.toFixed(0) + " K";
    }
  });
}
