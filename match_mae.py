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


def byma_simbolos():
    """{simbolo base sin sufijo: (vencimiento, moneda)} de la pizarra de BYMA (ON corporativas)."""
    req = urllib.request.Request("https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/negociable-obligations",
                                 data=json.dumps({"excludeZeroPxAndQty": False, "T2": True, "T1": True, "T0": True}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception:
        return {}
    rows = d if isinstance(d, list) else d.get("data", [])
    out = {}
    for x in rows:
        s = x["symbol"].split(".")[0]
        if s.endswith("D"):
            out[s[:-1]] = (x.get("maturityDate"), x.get("denominationCcy"))
    return out


def main():
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"})
    mae = [x for x in json.load(urllib.request.urlopen(req, timeout=60)) if x["tipoEspecie"] in ("ON", "TPP", "TPN")]
    M = []
    for x in mae:
        e, c, s = b.parse(x["descripcion"])
        M.append((e, c, s, x["codTitulo"], x["descripcion"], moneda_mae(x["descripcion"]), b.fecha_en(x["descripcion"])))
    p = json.load(open(os.path.join(HERE, "alias_pendientes.json"), encoding="utf-8"))
    BY = byma_simbolos()
    sheet = {t for _n, t, _v in json.load(open(os.path.join(HERE, "universo_sitio.json"), encoding="utf-8"))}
    ap = os.path.join(HERE, "alias_on.json")
    alias = json.load(open(ap, encoding="utf-8"))
    hall = json.load(open(os.path.join(HERE, "hallazgos_web.json"), encoding="utf-8"))
    bloq = set(json.load(open(os.path.join(HERE, "alias_bloqueados.json"), encoding="utf-8"))["bloqueados"])
    for k in bloq:
        alias.pop(k, None)
    nuevos = 0
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
        if not cl:   # "Vista Energy 33": numero suelto al final = clase
            t = re.search(r"\s(\d{1,3})\s*$", n)
            if t:
                cl = {t.group(1)}
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
        bases = {m[3][:-1] for m in cand}
        if len(bases) == 1:
            tk = list(bases)[0] + "D"
            if tk in sheet and n not in alias and n not in bloq:   # el ticker de MAE existe en el sheet: es esa ON
                alias[n] = tk
                nuevos += 1
        en_by = " | ".join("%s: %s %s" % (b_ + "D", BY[b_][0], BY[b_][1]) for b_ in sorted(bases) if b_ in BY) or ("no figura" if cand else "")
        filas.append([n, v["fondos"], rubro(n), " | ".join(m[3] for m in cand[:4]), " | ".join(m[4] for m in cand[:4]),
                      " | ".join(m[5] for m in cand[:4]), en_by, nota, hall.get(n, ""), ", ".join(v.get("candidatos", [])), ""])
    json.dump(dict(sorted(alias.items())), open(ap, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("alias nuevos por MAE->sheet:", nuevos)
    destino = os.path.join(HERE, "alias_pendientes.csv")
    try:
        open(destino, "a").close()
    except PermissionError:   # abierto en Excel
        destino = os.path.join(HERE, "alias_pendientes_nuevo.csv")
        print("alias_pendientes.csv esta abierto: escribo", destino)
    with open(destino, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Nombre en la CNV", "Fondos que la tienen", "Moneda según rubro CNV", "Ticker MAE (candidato)",
                    "Descripción en MAE", "Moneda según descripción MAE", "En BYMA hoy (vencimiento, moneda)", "Nota", "Hallazgo web", "Candidatos del sheet",
                    "Ticker final (completar a mano)"])
        w.writerows(filas)
    con = [r for r in filas if r[3]]
    print("pendientes:", len(filas), "| con candidato MAE:", len(con), "(%d tenencias)" % sum(r[1] for r in con),
          "| internacionales:", sum(1 for r in filas if r[7].startswith("Bono internacional")),
          "| sin MAE:", sum(1 for r in filas if r[7].startswith("No está")))
    return filas


if __name__ == "__main__":
    main()
