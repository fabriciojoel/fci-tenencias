#!/usr/bin/env python3
"""Arma data/fondos.json (indice) y data/fondo/<id>.json (detalle) para la seccion FCI del sitio.
    python build_site_data.py data/carteras/AAAA-MM-DD.json"""
import json
import os
import shutil
import sys

import scrape

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    alias = json.load(open(os.path.join(HERE, "alias_on.json"), encoding="utf-8"))
    base = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "data")
    out = os.path.join(base, "fondo")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    idx = []
    for f in raw["fondos"]:
        mon = f["moneda"].lower()
        usd = "dolar" in mon
        tc = 1.0 if usd else scrape.mep_en(f["fecha_cartera"] or "9999")
        pu = round(f["pn"] / tc) if (f["pn"] and tc) else None
        acts, on_pct, n_on = [], 0.0, 0
        for n, rubro, pct in f["activos"]:
            tk = scrape.ticker_de(n, alias) if scrape.es_on(n) else None
            acts.append([n, rubro, pct, tk or ""])
            if scrape.es_on(n):
                on_pct += pct
                n_on += 1
        suma = f["suma_rubros"]
        ok = abs(suma - 100) <= 1.5
        det = {k: f.get(k) for k in ("id", "nombre", "gerente", "depositaria", "clasificacion", "moneda", "region",
                                     "horizonte", "fecha_cartera", "pn", "disponibilidades", "otros_activos", "pasivos",
                                     "rubros")}
        det.update({"pn_usd": pu, "tc": None if usd else tc, "suma": suma, "activos": acts})
        json.dump(det, open(os.path.join(out, "%d.json" % f["id"]), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        idx.append({"i": f["id"], "n": f["nombre"], "g": f["gerente"], "d": f.get("depositaria", ""),
                    "c": f["clasificacion"], "m": f["moneda"], "r": f.get("region", ""), "h": f.get("horizonte", ""),
                    "f": f["fecha_cartera"], "pn": f["pn"], "pu": pu, "on": round(on_pct, 2), "non": n_on,
                    "np": len(acts), "ok": ok})
    idx.sort(key=lambda x: -(x["pu"] or 0))
    json.dump({"generado": raw.get("generado"), "fondos": idx},
              open(os.path.join(base, "fondos.json"), "w", encoding="utf-8"),
              ensure_ascii=False, separators=(",", ":"))
    print("fondos:", len(idx))


if __name__ == "__main__":
    main()
