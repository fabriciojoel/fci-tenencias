#!/usr/bin/env python3
"""Arma alias_on.json y alias_pendientes.json cruzando los nombres de ON de las
carteras CNV contra el universo del sitio (universo_sitio.json = [[nombre, ticker D]]).

    python build_alias.py data/carteras/AAAA-MM-DD.json

Solo se acepta un match con UN unico candidato (mismo emisor + misma clase [+ serie]).
Lo demas va a alias_pendientes.json. alias_on.json se puede completar a mano:
las entradas ya existentes nunca se pisan.
"""
import json
import os
import re
import sys
import unicodedata
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
STOP = {"on", "sa", "s", "a", "de", "la", "del", "cia", "fin", "financiera", "argentina", "arg", "argentinas",
        "sociedad", "anonima", "el", "los", "y", "co", "sau", "sacifia", "saic", "ciasa", "banco", "bco",
        "obligaciones", "negociables", "gen", "generacion", "energy", "energia", "electrica", "servicios",
        "ind", "capital", "solar", "green", "gas", "oil", "petroleo", "energias", "internacional"}
SINON = {"frances": "bbva", "bbva": "bbva", "tarj": "naranja", "tarjeta": "naranja", "hipotecario": "hipotecario",
         "pan": "pae", "amer": "pae", "american": "pae", "amercian": "pae", "pae": "pae",
         "gemsa": "roca", "ctr": "roca", "ct": "roca", "roca": "roca", "medit": "roca", "mediterranea": "roca",
         "oleoducto": "oldelval", "oleoductos": "oldelval", "oldelval": "oldelval", "valle": "oldelval",
         "cgc": "cgc", "comb": "cgc", "combust": "cgc", "combustibles": "cgc", "gral": "cgc", "vmos": "vmos", "vaca": "vmos", "muerta": "vmos", "tgs": "tgs", "sur": "tgs", "pcr": "pcr", "petroq": "pcr", "petroquimica": "pcr", "comodoro": "pcr", "rivadavia": "pcr"}
MARC = {"c", "cl", "clase", "serie", "ser"}


def norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.split()


ROM = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def romano(t):
    """'xviii' -> 18 ; None si no es un romano valido (1..60)."""
    if not t or not re.match(r"^[ivxl]+$", t):
        return None
    tot = 0
    for i, ch in enumerate(t):
        v = ROM[ch]
        tot += -v if i + 1 < len(t) and ROM[t[i + 1]] > v else v
    return tot if 0 < tot <= 60 else None


def normclase(c):
    if c is None:
        return None
    r = romano(c)
    return str(r) if r else c


def parse(nombre):
    t = norm(nombre)
    # "c12", "c.12" -> c 12
    out = []
    for x in t:
        m = re.match(r"^(c|cl)(\d+|[ivxl]+)$", x) if x != "cl" else None
        if m:
            out += [m.group(1), m.group(2)]
        else:
            out.append(x)
    t = out
    clase = serie = None
    emi = []
    i = 0
    while i < len(t):
        x = t[i]
        if x in MARC and i + 1 < len(t) and clase is None:
            clase = t[i + 1]
            i += 2
            continue
        m = re.match(r"^s(\d+)$", x)
        if m and serie is None:
            serie = m.group(1)
        elif x == "s" and i + 1 < len(t) and t[i + 1].isdigit() and serie is None:
            serie = t[i + 1]
            i += 2
            continue
        elif clase is None and x not in STOP and not x.isdigit():
            emi.append(SINON.get(x, x))
        i += 1
    return set(emi), normclase(clase), serie


def fecha_en(nombre):
    """ddmmyy en el nombre -> ISO (None si no hay una fecha valida)."""
    import datetime
    for m in re.finditer(r"(?<!\d)(\d\d)(\d\d)(\d\d)(?!\d)", nombre):
        try:
            return datetime.date(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            continue
    return None


def main():
    raw = json.load(open(sys.argv[1], encoding="utf-8"))
    uni = json.load(open(os.path.join(HERE, "universo_sitio.json"), encoding="utf-8"))
    U = []
    for nom, tk, venc in uni:
        e, c, s = parse(nom)
        U.append((e, c, s, tk, nom, venc))
    cuentas = Counter()
    for f in raw["fondos"]:
        for n, _r, _p in f["activos"]:
            if n.startswith("ON "):
                cuentas[n] += 1
    ap = os.path.join(HERE, "alias_on.json")
    alias = json.load(open(ap, encoding="utf-8")) if os.path.exists(ap) else {}
    bloq = set(json.load(open(os.path.join(HERE, "alias_bloqueados.json"), encoding="utf-8"))["bloqueados"])
    for k in bloq:
        alias.pop(k, None)
    nuevos, pend = {}, {}
    for n, k in cuentas.most_common():
        if n in bloq:
            pend[n] = {"fondos": k, "motivo": "bloqueado (cruce automatico dudoso)"}
            continue
        if n in alias or re.search(r"\b[A-Z0-9]{4}[ODC]\b", n):
            continue
        e, c, s = parse(n)
        fv = fecha_en(n)
        if fv:   # "ON YPF 210727": emisor + fecha de vencimiento (ddmmyy)
            cd = [u for u in U if u[5] == fv and {x for x in e if len(x) >= 3} & u[0] and not (c and u[1] and c != u[1])]
            if len({u[3] for u in cd}) == 1:
                nuevos[n] = cd[0][3]
                continue
        ym = re.search(r"(?<!\d)(20[2-5]\d)(?!\d)", n)
        if ym and not c and e:   # "Aeropuertos 2000 Regs 2031": emisor + año de vencimiento
            cy = [u for u in U if u[5] and u[5][:4] == ym.group(1) and {x for x in e if len(x) >= 3} & u[0]]
            if len({u[3] for u in cy}) == 1:
                nuevos[n] = cy[0][3]
                continue
        if not c or not e:
            pend[n] = {"fondos": k, "motivo": "sin clase o emisor"}
            continue
        cl = {x for x in (c, s) if x}
        cand = [u for u in U if (cl & {x for x in (u[1], u[2]) if x}) and ({x for x in e if len(x) >= 3} & u[0]) and (s is None or u[2] is None or s == u[2] or c == u[1])]
        if s is not None:
            exact = [u for u in cand if u[2] == s]
            cand = exact or cand
        tks = {u[3] for u in cand}
        if len(tks) == 1:
            nuevos[n] = cand[0][3]
        elif len(tks) > 1:
            pend[n] = {"fondos": k, "motivo": "ambiguo", "candidatos": sorted(tks)}
        else:
            pend[n] = {"fondos": k, "motivo": "fuera del universo / sin match"}
    alias.update(nuevos)
    for n, v in pend.items():
        fv = fecha_en(n)
        if fv:
            v["vencimiento"] = fv
            v["mismo_vencimiento_en_sitio"] = [u[3] + " " + u[4] for u in U if u[5] == fv]
    json.dump(dict(sorted(alias.items())), open(ap, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump(pend, open(os.path.join(HERE, "alias_pendientes.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("nombres ON distintos: %d | alias nuevos: %d | pendientes: %d (%d fondos-tenencia)"
          % (len(cuentas), len(nuevos), len(pend), sum(v["fondos"] for v in pend.values())))


if __name__ == "__main__":
    main()
