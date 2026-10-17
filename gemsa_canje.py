#!/usr/bin/env python3
"""Mapa de las ON de GEMSA / CTR: ticker -> clase (BYMA ficha tecnica) + estado en el canje (lista de Eco Valores,
26/02/2026) y cruce con los nombres que usan los fondos en la CNV. Escribe gemsa_canje.csv y devuelve alias."""
import csv, json, re, string, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, "E:/fci-tenencias")
import build_alias as b

URL = "https://open.bymadata.com.ar/vanoms-be-core/rest/api/bymadata/free/bnown/fichatecnica/especies/general"
C43 = set("MRCG MRCH MRCK MRCP MRCR MRCT MRCW MRCZ MR34 MR36 MR37 MR38 MR42 LEC3 LEC7 LEC9 LECA LECD LECH LECI LECJ".split())
C44 = set("MRCL MRCO MRCQ MRCU MRCY MR35 LECB LECE LECG".split())
FUERA = set("MR39 MR40 MR41 LECL LECK MRCA".split())


def ficha(s):
    req = urllib.request.Request(URL, data=json.dumps({"symbol": s, "Content-Type": "application/json"}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=20))["data"]
        return d[0] if d else None
    except Exception:
        return None


def probe(t):
    for suf in ("D", "O", "C"):
        r = ficha(t + suf)
        if r:
            return t, suf, r
    return t, None, None


def main():
    chars = string.digits + string.ascii_uppercase
    cand = [p + c for p in ("MRC", "LEC") for c in chars] + ["MR%02d" % i for i in range(100)]
    with ThreadPoolExecutor(6) as ex:
        res = [x for x in ex.map(probe, cand) if x[2]]
    rows = []
    for t, suf, r in res:
        em = r.get("emisor") or ""
        den = (r.get("denominacion") or "")
        den = re.sub(r"(?i)^clase\s+", "", den).split()[0] if den else ""
        k = b.romano(den.lower()) if b.romano(den.lower()) else (int(den) if den.isdigit() else None)
        rows.append({"ticker": t, "suf": suf, "clase": k, "den": r.get("denominacion"), "moneda": r.get("moneda"),
                     "emision": str(r.get("fechaEmision"))[:10], "vto": str(r.get("fechaVencimiento"))[:10],
                     "nominal": r.get("montoNominal"), "residual": r.get("montoResidual"), "isin": r.get("codigoIsin"),
                     "emisor": "GEMSA+CTR" if "Roca" in str(r.get("denominacion", "")) + str(r.get("emisorNombre", "")) else ""})
    return rows


if __name__ == "__main__":
    rows = main()
    json.dump(rows, open("E:/fci-tenencias/_gemsa_byma.json", "w", encoding="utf-8"), ensure_ascii=False)
    for r in sorted(rows, key=lambda r: (r["ticker"][:3] == "LEC", r["clase"] or 0)):
        print(r["ticker"], r["clase"], r["den"], r["moneda"], r["emision"], r["vto"], r["residual"])
