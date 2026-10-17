#!/usr/bin/env python3
"""Para los nombres de ON de la CNV que no cruzan con el sheet (alias_pendientes.json), busca candidatos en el
catalogo publico de MAE (ticker + descripcion + moneda) y escribe alias_pendientes.csv.

    python match_mae.py            # baja el catalogo de MAE y reescribe alias_pendientes.csv
"""
import collections
import csv
import json
import os
import re
import urllib.request

import build_alias as b

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://api.marketdata.mae.com.ar/api/mercado/titulosactivos?oTitulo=%7B%7D"
INTERNACIONAL = re.compile(r"\d[.,]?\d*\s?%|\breg\s?s\b|\bregs\b|144a|\b20[2-5]\d\b|\b(19|20)\d\d\b", re.I)


def moneda_mae(d):
    t = d.upper()
    out = []
    if re.search(r"\bDL\b|\bDLK\b|LINKED", t):
        out.append("Dólar Linked")
    elif re.search(r"\bUSD\b|U\$S|US\$|DOLAR|\bD UNIC|CCL|EXT UNI", t):
        out.append("USD")
    if "UVA" in t:
        out.append("UVA")
    if "CER" in t.split():
        out.append("CER")
    return "/".join(out) or "sin aclarar"


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    mae = [x for x in json.load(urllib.request.urlopen(req, timeout=60)) if x["tipoEspecie"] in ("ON", "TPP", "TPN")]
    M = []
    for x in mae:
        e, c, s = b.parse(x["descripcion"])
        M.append((e, c, s, x["codTitulo"], x["descripcion"], moneda_mae(x["descripcion"]), b.fecha_en(x["descripcion"])))
    p = json.load(open(os.path.join(HERE, "alias_pendientes.json"), encoding="utf-8"))
    raw = json.load(open(os.path.join(HERE, "data", "carteras", sorted(os.listdir(os.path.join(HERE, "data", "carteras")))[-1]),
                         encoding="utf-8"))["fondos"]
    cnt = collections.defaultdict(lambda: [0, 0])
    for f in raw:
        for n, r, pc in f["activos"]:
            if n in p:
                cnt[n][0 if "Dolar" in r else 1] += 1

    def rubro(n):
        d, a = cnt[n]
        sh = d / max(d + a, 1)
        return "USD" if sh >= 0.7 else "Pesos/UVA/CER/DL" if sh <= 0.15 else "Dudosa"

    filas = []
    for n, v in sorted(p.items(), key=lambda kv: -kv[1]["fondos"]):
        e, c, s = b.parse(n)
        E = {x for x in e if len(x) >= 3}
        fv = b.fecha_en(n)
        cl = {x for x in (c, s) if x}   # "Santander S 32": la serie es la clase
        cand = [m for m in M if E & m[0] and m[1] in cl] if cl else []
        if not cand and fv:
            cand = [m for m in M if E & m[0] and m[6] == fv]
        if s and len(cand) > 1:
            ex = [m for m in cand if m[2] == s]
            cand = ex or cand
        # una clase puede aparecer con la serie; si hay varias, quedarse con las que calzan la serie
        nota = ""
        if not cand and INTERNACIONAL.search(n):
            nota = "Bono internacional (tasa/año/Reg S/144A en el nombre): no cotiza con ticker local en MAE"
        elif not cand:
            nota = "No está en el catálogo vigente de MAE (puede estar vencida o no listar)"
        filas.append([n, v["fondos"], rubro(n), " | ".join(m[3] for m in cand[:4]), " | ".join(m[4] for m in cand[:4]),
                      " | ".join(m[5] for m in cand[:4]), nota, ", ".join(v.get("candidatos", [])), ""])
    with open(os.path.join(HERE, "alias_pendientes.csv"), "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Nombre en la CNV", "Fondos que la tienen", "Moneda según rubro CNV", "Ticker MAE (candidato)",
                    "Descripción en MAE", "Moneda según descripción MAE", "Nota", "Candidatos del sheet",
                    "Ticker final (completar a mano)"])
        w.writerows(filas)
    con = [r for r in filas if r[3]]
    print("pendientes:", len(filas), "| con candidato MAE:", len(con), "(%d tenencias)" % sum(r[1] for r in con),
          "| internacionales:", sum(1 for r in filas if r[6].startswith("Bono internacional")),
          "| sin MAE:", sum(1 for r in filas if r[6].startswith("No está")))
    return filas


if __name__ == "__main__":
    main()
