#!/usr/bin/env python3
"""Scraper de carteras semanales de FCI (CNV) -> tenencias de ON por ticker.

Solo stdlib. Uso:
    python scrape.py                # corrida completa (~1,75 h en serie)
    python scrape.py --limit 20     # prueba: 20 fondos repartidos en la lista
    python scrape.py --from-raw data/carteras/AAAA-MM-DD.json   # re-armar sin scrapear

Salidas (en data/):
    carteras/AAAA-MM-DD.json   crudo de la corrida (fondos Renta Fija / Mixta)
    tenencias_on.json          lo que lee el sitio (ultima corrida)
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = "https://www.cnv.gov.ar/SitioWeb/FondosComunesInversion"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
CLASES_OK = ("Renta Fija", "Renta Mixta")
TICKER_RE = re.compile(r"\b[A-Z0-9]{4}[ODC]\b")
MAX_FALLA = 0.20


def get(url, tries=3, timeout=60):
    err = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
            try:
                return raw.decode("utf-8")
            except UnicodeDecodeError:
                return raw.decode("cp1252", errors="replace")
        except Exception as e:  # noqa: BLE001
            err = e
            time.sleep(2 + 3 * i)
    raise RuntimeError("%s -> %s" % (url, err))


def txt(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip()


def num(s):
    """'1.234,56' -> 1234.56 ; vacio -> None"""
    s = (s or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def lista_fondos():
    h = get(BASE)
    m = re.search(r'<select[^>]*id="Lfc"[^>]*>(.*?)</select>', h, re.S)
    if not m:
        raise RuntimeError("no encontre <select id=Lfc>")
    out = []
    for v, n in re.findall(r'<option[^>]*value="(\d+)"[^>]*>(.*?)</option>', m.group(1), re.S):
        out.append((int(v), txt(n)))
    return out


def parse_fondo(h, fid):
    """Devuelve dict del fondo o None si no hay cartera."""
    i = h.find("Composición Semanal Cartera")
    if i < 0:
        return None
    j = h.find("Se incorporarán aquellos activos", i)
    sec = h[i:j if j > 0 else len(h)]
    head, activos, rubros = {}, [], {}
    rubro = ""
    pn, total, disp, pasivos, otros = None, None, 0.0, 0.0, 0.0
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", sec, re.S):
        c = [txt(x) for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
        if not c:
            continue
        if len(c) == 2:
            k = c[0].lower()
            if k.startswith("fondo"):
                head["nombre"] = c[1]
            elif k.startswith("cartera al"):
                head["fecha"] = c[1]
            elif k.startswith("gerente"):
                head["gerente"] = c[1]
            elif k.startswith("clasific"):
                head["clasificacion"] = c[1]
            elif k.startswith("moneda"):
                head["moneda"] = c[1]
            elif c[0].startswith("(") and num(c[1]) is not None:
                pn = num(c[1])
            continue
        if len(c) < 3:
            continue
        d, a, r = c[0], num(c[1]), num(c[2])
        if c[0].startswith("(") and a is not None and r is None:
            pn = a
        elif d == "" and r is not None:
            total = r
        elif d.lower().startswith("disponibilidades"):
            disp = r or 0.0
        elif d.lower().startswith("otros activos"):
            otros = r or a or 0.0
        elif d.lower().startswith("pasivos"):
            pasivos = r or a or 0.0
        elif a is None and r is not None:
            rubro = d
            rubros[d] = r
        elif a is not None:
            activos.append([d, rubro, a])
    if "nombre" not in head or not activos and not rubros:
        return None
    m = re.match(r"(\d\d)/(\d\d)/(\d\d)$", head.get("fecha", ""))
    fecha = "20%s-%s-%s" % (m.group(3), m.group(2), m.group(1)) if m else None
    # control de suma: disponibilidades + rubros + otros - pasivos ~ 100
    suma = disp + sum(rubros.values()) + otros + pasivos
    suma_act = sum(x[2] for x in activos)
    return {
        "id": fid, "nombre": head["nombre"], "gerente": head.get("gerente", ""),
        "clasificacion": head.get("clasificacion", ""), "moneda": head.get("moneda", ""),
        "fecha_cartera": fecha, "pn": pn, "total": total, "suma_rubros": round(suma, 2),
        "suma_activos": round(suma_act + disp + otros + pasivos, 2),
        "activos": activos,
    }


def scrape(limit, workers, shard=None):
    fondos = lista_fondos()
    print("fondos en la lista:", len(fondos), flush=True)
    if limit:
        paso = max(1, len(fondos) // limit)
        fondos = fondos[::paso][:limit]
    if shard:
        k, n = shard
        fondos = fondos[k::n]
    res, fallas, sin_cartera = [], [], 0
    lock = threading.Lock()
    cont = [0]
    t0 = time.time()

    def uno(f):
        nonlocal sin_cartera
        fid, nombre = f
        try:
            h = get("%s/DetallesFCI/%d" % (BASE, fid))
            p = parse_fondo(h, fid)
        except Exception as e:  # noqa: BLE001
            with lock:
                fallas.append((fid, nombre, str(e)[:120]))
            return
        with lock:
            cont[0] += 1
            if cont[0] % 50 == 0:
                print("  %d/%d  %.0fs" % (cont[0], len(fondos), time.time() - t0), flush=True)
            if p is None:
                sin_cartera += 1
            elif p["clasificacion"] in CLASES_OK:
                res.append(p)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(uno, fondos))
    print("ok=%d  sin_cartera=%d  fallas=%d  renta fija/mixta=%d"
          % (cont[0], sin_cartera, len(fallas), len(res)), flush=True)
    if fallas and len(fallas) / len(fondos) > MAX_FALLA:
        print("DEMASIADAS FALLAS (%d/%d). Ejemplos:" % (len(fallas), len(fondos)))
        for x in fallas[:5]:
            print("  ", x)
        sys.exit(2)
    res.sort(key=lambda x: x["id"])
    return res, fallas, sin_cartera, len(fondos)


# ---------- cruce con tickers ----------
def es_on(nombre):
    return nombre.startswith("ON ") or nombre.startswith("ON-") or nombre.startswith("Obligaci")


def ticker_de(nombre, alias):
    if nombre in alias and alias[nombre]:
        return alias[nombre]
    m = TICKER_RE.search(nombre)
    if m:
        return m.group(0)[:4] + "D"
    return None


_mep = None


def mep_hist():
    global _mep
    if _mep is None:
        try:
            d = json.loads(get("https://api.argentinadatos.com/v1/cotizaciones/dolares/bolsa"))
            _mep = sorted((x["fecha"], float(x["venta"])) for x in d if x.get("venta"))
        except Exception as e:  # noqa: BLE001
            print("sin MEP historico:", e)
            _mep = []
    return _mep


def mep_en(fecha):
    h = mep_hist()
    val = None
    for f, v in h:
        if f <= fecha:
            val = v
        else:
            break
    return val


def armar_tenencias(carteras, alias):
    por_ticker, sin_match = {}, {}
    fmax = max([c["fecha_cartera"] for c in carteras if c["fecha_cartera"]] or [""])
    for c in carteras:
        usd = "dolar" in c["moneda"].lower()
        if not c["pn"] or not c["fecha_cartera"]:
            continue
        tc = 1.0 if usd else mep_en(c["fecha_cartera"])
        if not tc:
            continue
        for nombre, rubro, pct in c["activos"]:
            if not es_on(nombre) or pct <= 0:
                continue
            row = {"fondo": c["nombre"], "id": c["id"], "gerente": c["gerente"],
                   "moneda": "USD" if usd else "ARS", "fecha": c["fecha_cartera"],
                   "pct_pn": pct, "valor_usd": round(pct / 100.0 * c["pn"] / tc)}
            t = ticker_de(nombre, alias)
            if t:
                por_ticker.setdefault(t, []).append(row)
            else:
                sin_match.setdefault(nombre, []).append(row)
    for t in por_ticker:
        por_ticker[t].sort(key=lambda r: -r["valor_usd"])
    return {"generado": datetime.date.today().isoformat(), "fecha_cartera_max": fmax,
            "por_ticker": por_ticker,
            "sin_match": {k: [{"fondo": r["fondo"], "pct_pn": r["pct_pn"]} for r in v]
                          for k, v in sorted(sin_match.items())}}


def resumen_validacion(carteras, fallas, sin_cartera, total, out):
    ok = [c for c in carteras if c["suma_rubros"] and abs(c["suma_rubros"] - 100) <= 1]
    gerentes_ok = {c["gerente"] for c in ok}
    L = ["## Scrape CNV carteras FCI", "",
         "- Fondos en la lista: %d  |  sin cartera: %d  |  fallas: %d" % (total, sin_cartera, len(fallas)),
         "- Renta Fija / Mixta con cartera: %d" % len(carteras),
         "- Validacion de sumas (disp + rubros + otros + pasivos = 100 +-1): %d/%d fondos, %d gerentes distintas"
         % (len(ok), len(carteras), len(gerentes_ok))]
    mal = [c for c in carteras if c not in ok][:10]
    if mal:
        L.append("- Fondos que no cierran (primeros 10): " +
                 "; ".join("%s (%.2f)" % (c["nombre"], c["suma_rubros"]) for c in mal))
    if fallas:
        L.append("- Fallas (primeras 5): " + "; ".join("%d %s" % (f[0], f[2][:60]) for f in fallas[:5]))
    L += ["", "- ON con ticker: %d tickers, %d tenencias" % (
        len(out["por_ticker"]), sum(len(v) for v in out["por_ticker"].values())),
        "- ON sin match (nombres distintos): %d" % len(out["sin_match"])]
    ctrl = [r for r in out["por_ticker"].get("YM41D", []) if r["id"] == 86598]
    c2 = [c for c in carteras if c["id"] == 86598]
    if c2:
        a = [x for x in c2[0]["activos"] if x[0] == "ON YPF Clase 41"]
        L.append("- Control Allaria Dolar Ahorro Plus / ON YPF Clase 41: %s" % (a[0][2] if a else "no aparece"))
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--from-raw")
    ap.add_argument("--shard", help="K/N: procesa solo los fondos con indice = K mod N y guarda data/parts/shard-K.json")
    ap.add_argument("--merge", help="directorio con shard-*.json a unir")
    a = ap.parse_args()
    os.makedirs(os.path.join(DATA, "carteras"), exist_ok=True)
    ap_path = os.path.join(HERE, "alias_on.json")
    alias = json.load(open(ap_path, encoding="utf-8")) if os.path.exists(ap_path) else {}
    if a.shard:
        k, n = [int(x) for x in a.shard.split("/")]
        carteras, fallas, sin_cartera, total = scrape(a.limit, a.workers, (k, n))
        os.makedirs(os.path.join(DATA, "parts"), exist_ok=True)
        json.dump({"fondos": carteras, "fallas": len(fallas), "total": total, "sin_cartera": sin_cartera},
                  open(os.path.join(DATA, "parts", "shard-%d.json" % k), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        return
    if a.merge:
        import glob
        carteras, nf, sin_cartera, total = [], 0, 0, 0
        for p in sorted(glob.glob(os.path.join(a.merge, "**", "shard-*.json"), recursive=True)):
            d = json.load(open(p, encoding="utf-8"))
            carteras += d["fondos"]
            nf += d["fallas"]
            sin_cartera += d["sin_cartera"]
            total += d["total"]
        if not carteras or nf / max(total, 1) > MAX_FALLA:
            print("merge invalido: fondos=%d fallas=%d/%d" % (len(carteras), nf, total))
            sys.exit(2)
        carteras.sort(key=lambda x: x["id"])
        p = os.path.join(DATA, "carteras", datetime.date.today().isoformat() + ".json")
        json.dump({"generado": datetime.date.today().isoformat(), "fondos": carteras},
                  open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        out = armar_tenencias(carteras, alias)
        json.dump(out, open(os.path.join(DATA, "tenencias_on.json"), "w", encoding="utf-8"),
                  ensure_ascii=False, separators=(",", ":"))
        res = resumen_validacion(carteras, [None] * nf, sin_cartera, total, out)
        print(res)
        sm = os.environ.get("GITHUB_STEP_SUMMARY")
        if sm:
            open(sm, "a", encoding="utf-8").write(res)
        return
    if a.from_raw:
        raw = json.load(open(a.from_raw, encoding="utf-8"))
        carteras, fallas, sin_cartera, total = raw["fondos"], [], 0, len(raw["fondos"])
    else:
        carteras, fallas, sin_cartera, total = scrape(a.limit, a.workers)
        if not a.limit:
            p = os.path.join(DATA, "carteras", datetime.date.today().isoformat() + ".json")
            json.dump({"generado": datetime.date.today().isoformat(), "fondos": carteras},
                      open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    out = armar_tenencias(carteras, alias)
    dest = os.path.join(DATA, "tenencias_on.json" if not a.limit else "tenencias_on.prueba.json")
    json.dump(out, open(dest, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    res = resumen_validacion(carteras, fallas, sin_cartera, total, out)
    print(res)
    s = os.environ.get("GITHUB_STEP_SUMMARY")
    if s:
        open(s, "a", encoding="utf-8").write(res)


if __name__ == "__main__":
    main()
