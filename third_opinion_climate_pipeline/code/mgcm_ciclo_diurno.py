#!/usr/bin/env python3
"""Ciclo diurno de Marte a partir do arquivo 03340.atmos_diurn.nc do modelo climatico
da NASA Ames (mesma simulacao do mgcm_marte_global.py). O arquivo tem, para cada
periodo de 5 sois do ano, a media de cada uma das 24 horas do dia.

O arquivo inteiro tem ~48 GB. Por padrao o script NAO baixa tudo: abre o arquivo
no servidor e le so os trechos necessarios (leitura por faixa de bytes). Se o
servidor nao aceitar esse modo, use --baixar (download completo, retomavel).

Saida: marte_ciclo_diurno_por_ponto.csv, uma linha por ponto da grade, com
  amp_diurna_<variavel>_media/min/max   amplitude diaria (max - min das 24 horas):
                                        media, menor e maior valor ao longo do ano
  amp_diurna_<variavel>_ls...           media da amplitude por estacao
  <variavel>_min_diario_media, <variavel>_max_diario_media
para temperatura do ar junto ao solo, temperatura da superficie (se o arquivo
tiver), pressao e vento.

Exemplos:
  python mgcm_ciclo_diurno.py --inspect       # mostra o conteudo sem baixar (rapido)
  python mgcm_ciclo_diurno.py                 # extrai lendo do servidor
  python mgcm_ciclo_diurno.py --sem-vento     # mais rapido: pula as duas variaveis de vento
  python mgcm_ciclo_diurno.py --baixar        # baixa os 48 GB para a pasta mgcm/ e extrai

Requer numpy e netCDF4 (pip install netCDF4).
"""
import argparse
import csv
import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "https://data.nas.nasa.gov/legacygcm/fv3betaout1/fv3betaout1/"
DIURN = "03340.atmos_diurn.nc"
UA = {"User-Agent": "mgcm-ciclo-diurno/1.0 (uso academico; script pessoal)"}
SITIOS = {"Jezero (Perseverance)": (18.4, 77.5), "Gale (Curiosity)": (-4.6, 137.4),
          "Elysium (InSight)": (4.5, 135.6)}
ESTACOES = [("ls000_090", 0, 90), ("ls090_180", 90, 180),
            ("ls180_270", 180, 270), ("ls270_360", 270, 360)]


def http_open(url, start=0, timeout=120):
    headers = dict(UA)
    if start:
        headers["Range"] = f"bytes={start}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)


def diagnose(url):
    """Diz se o problema e do servidor inteiro ou so deste arquivo."""
    import re
    base = url.rsplit("/", 1)[0] + "/"
    print("\nDiagnostico do servidor:")
    for name in ("03340.fixed.nc", url.rsplit("/", 1)[1]):
        try:
            req = urllib.request.Request(base + name, headers={**UA, "Range": "bytes=0-7"})
            with urllib.request.urlopen(req, timeout=60) as r:
                print(f"  {name}: HTTP {r.status}, Content-Range={r.headers.get('Content-Range')}")
        except Exception as e:  # noqa: BLE001
            print(f"  {name}: {e}")
    try:
        html = urllib.request.urlopen(urllib.request.Request(base, headers=UA), timeout=60).read().decode("utf-8", "replace")
        names = sorted(set(re.findall(r"[\w.\-]+\.nc", html)))
        print("  arquivos listados em " + base + ": " + (", ".join(names) if names else "(nenhum .nc na pagina)"))
    except Exception as e:  # noqa: BLE001
        print(f"  listagem de {base}: {e}")


def download(url, dest, max_wait_errors=12, wait=30):
    """Download completo. Retoma sozinho (Range) se a conexao cair ou o servidor
    responder 502/503/504; desiste apos varias falhas seguidas sem progresso."""
    part = dest + ".part"
    errors, t0, last = 0, time.time(), 0
    start_size = os.path.getsize(part) if os.path.exists(part) else 0
    while True:
        have = os.path.getsize(part) if os.path.exists(part) else 0
        try:
            resp = http_open(url, have)
            with resp:
                if have and resp.status != 206:       # servidor ignorou o Range: recomeca
                    have = 0
                total = have + int(resp.headers.get("Content-Length") or 0)
                with open(part, "ab" if have else "wb") as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        errors = 0
                        if time.time() - last > 10:
                            last = time.time()
                            done = f.tell()
                            speed = (done - start_size) / max(time.time() - t0, 1e-6) / 1e6
                            print(f"  {done / 1e9:.2f} GB de {total / 1e9:.1f} GB "
                                  f"({100 * done / max(total, 1):.1f}%), {speed:.1f} MB/s", flush=True)
            if not total or os.path.getsize(part) >= total:
                os.replace(part, dest)
                return
            print("  conexao encerrada antes do fim; retomando...", flush=True)
        except urllib.error.HTTPError as e:
            if e.code == 416 and have:                # ja estava completo
                os.replace(part, dest)
                return
            if e.code not in (429, 500, 502, 503, 504):
                raise
            errors += 1
            print(f"  servidor respondeu HTTP {e.code} (tentativa {errors}/{max_wait_errors})", flush=True)
        except (urllib.error.URLError, OSError) as e:
            errors += 1
            print(f"  falha de conexao: {e} (tentativa {errors}/{max_wait_errors})", flush=True)
        if errors >= max_wait_errors:
            diagnose(url)
            sys.exit("\nO servidor nao entregou o arquivo. O que ja foi baixado ficou em "
                     f"{part}; rode o mesmo comando mais tarde para retomar.")
        time.sleep(min(wait * max(errors, 1), 180))


def open_dataset(args):
    """-> (Dataset, descricao). Local se existir (ou --baixar); senao remoto por faixa de bytes."""
    from netCDF4 import Dataset
    local = args.local or os.path.join(args.dir, args.file)
    if args.baixar and not os.path.exists(local):
        os.makedirs(os.path.dirname(local) or ".", exist_ok=True)
        print(f"Baixando {args.base_url}{args.file} (cerca de 48 GB)")
        download(args.base_url + args.file, local, args.tentativas, args.espera)
    if os.path.exists(local):
        return Dataset(local), f"arquivo local {local}"
    url = args.base_url + args.file
    try:
        return Dataset(url + "#mode=bytes"), f"leitura remota de {url}"
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Nao consegui abrir o arquivo no servidor por faixa de bytes ({e}).\n"
                 "Use --baixar para o download completo (48 GB, retomavel).")


def describe(nc):
    print(f"  formato: {nc.data_model}; dimensoes: "
          + ", ".join(f"{k}={len(v)}" for k, v in nc.dimensions.items()))
    for name, v in nc.variables.items():
        try:
            chunk = v.chunking()
        except Exception:  # noqa: BLE001
            chunk = "?"
        print(f"  {name:16s} {str(v.dimensions):52s} {getattr(v, 'units', ''):8s} "
              f"{getattr(v, 'long_name', '')[:34]:34s} blocos={chunk}")


def main():
    ap = argparse.ArgumentParser(description="Ciclo diurno de Marte (MGCM, atmos_diurn).")
    ap.add_argument("-o", "--output", default="marte_ciclo_diurno_por_ponto.csv")
    ap.add_argument("--inspect", action="store_true", help="so lista o conteudo do arquivo")
    ap.add_argument("--baixar", action="store_true", help="baixa o arquivo inteiro (~48 GB) antes")
    ap.add_argument("--local", help="caminho de um atmos_diurn.nc ja baixado")
    ap.add_argument("--sem-vento", action="store_true", help="nao processa ucomp/vcomp")
    ap.add_argument("--tentativas", type=int, default=12,
                    help="falhas seguidas toleradas no download antes de desistir")
    ap.add_argument("--espera", type=float, default=30, help="segundos entre tentativas (cresce a cada falha)")
    ap.add_argument("--dir", default="mgcm")
    ap.add_argument("--file", default=DIURN)
    ap.add_argument("--base-url", default=BASE_URL)
    args = ap.parse_args()
    try:
        import numpy as np
        import netCDF4  # noqa: F401
    except ImportError:
        sys.exit("Instale as dependencias: pip install numpy netCDF4")

    nc, origem = open_dataset(args)
    print("Fonte: " + origem)
    if args.inspect:
        describe(nc)
        return

    V = nc.variables
    tod_dim = next((d for d in nc.dimensions if d.startswith("time_of_day")), None)
    if tod_dim is None:
        sys.exit("O arquivo nao tem dimensao time_of_day_XX; nao e um arquivo diurno.")
    lat = np.asarray(V["lat"][:], dtype="f8")
    lon = np.asarray(V["lon"][:], dtype="f8")
    nt = len(nc.dimensions["time"])
    areo = np.asarray(V["areo"][:], dtype="f8").reshape(nt, -1)[:, 0] % 360.0 if "areo" in V else None
    k_sfc = int(np.argmax(np.asarray(V["pfull"][:]))) if "pfull" in V else -1
    print(f"{nt} periodos x {len(nc.dimensions[tod_dim])} horas, grade {lat.size} x {lon.size}; "
          f"camada junto ao solo = indice {k_sfc}")

    def read(name, t):
        """-> (horas, lat, lon) do periodo t; em variaveis com pfull, so a camada junto ao solo."""
        v = V[name]
        idx = []
        for d in v.dimensions:
            idx.append(t if d == "time" else k_sfc if d == "pfull" else slice(None))
        a = np.ma.filled(np.ma.asarray(v[tuple(idx)], dtype="f8"), np.nan)
        order = [d for d in v.dimensions if d not in ("time", "pfull")]
        return np.transpose(a, [order.index(tod_dim), order.index("lat"), order.index("lon")])

    cols = {}
    shape = (lat.size, lon.size)

    def process(label, get, unit, seasons=True):
        """Acumula, ao longo do ano, min/max/amplitude diarios de get(t) -> (horas, lat, lon).
        Periodos sem dado numa celula sao ignorados nessa celula (nao contaminam a media)."""
        import warnings
        acc = {k: np.zeros(shape) for k in ("amp", "min", "max", "mean")}
        n = np.zeros(shape)
        amp_lo = np.full(shape, np.nan); amp_hi = np.full(shape, np.nan)
        seas = {tag: [np.zeros(shape), np.zeros(shape)] for tag, _, _ in ESTACOES}
        t0, vazios = time.time(), 0
        for t in range(nt):
            a = get(t)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)      # fatias so com NaN
                lo, hi, me = np.nanmin(a, axis=0), np.nanmax(a, axis=0), np.nanmean(a, axis=0)
            amp = hi - lo
            ok = np.isfinite(amp)
            vazios += int(not ok.any())
            for k, x in (("amp", amp), ("min", lo), ("max", hi), ("mean", me)):
                acc[k] += np.where(ok, x, 0.0)
            n += ok
            amp_lo = np.fmin(amp_lo, amp); amp_hi = np.fmax(amp_hi, amp)
            if areo is not None:
                for tag, a0, a1 in ESTACOES:
                    if a0 <= areo[t] < a1:
                        seas[tag][0] += np.where(ok, amp, 0.0); seas[tag][1] += ok
            if (t + 1) % 20 == 0 or t + 1 == nt:
                el = time.time() - t0
                print(f"  {label}: {t + 1}/{nt} periodos ({el:.0f} s, "
                      f"faltam ~{el / (t + 1) * (nt - t - 1):.0f} s)", flush=True)

        def div(total, count):
            return np.where(count > 0, total / np.maximum(count, 1), np.nan)

        cols[f"amp_diurna_{label}_{unit}_media"] = div(acc["amp"], n)
        cols[f"amp_diurna_{label}_{unit}_min"] = amp_lo
        cols[f"amp_diurna_{label}_{unit}_max"] = amp_hi
        cols[f"{label}_{unit}_min_diario_media"] = div(acc["min"], n)
        cols[f"{label}_{unit}_max_diario_media"] = div(acc["max"], n)
        cols[f"{label}_{unit}_media"] = div(acc["mean"], n)
        if seasons:
            for tag, (total, count) in seas.items():
                if count.any():
                    cols[f"amp_diurna_{label}_{unit}_{tag}"] = div(total, count)
        sem = int((n == 0).sum())
        if vazios or sem:
            print(f"  {label}: {vazios} periodos sem nenhum dado; {sem} celulas sem valor; "
                  f"periodos validos por celula: {int(n.min())} a {int(n.max())}")

    used = []
    for name, label, unit in [("ts", "temp_superficie", "K"), ("temp", "temp_ar", "K"),
                              ("ps", "pressao", "Pa")]:
        if name in V and tod_dim in V[name].dimensions:
            process(label, lambda t, n=name: read(n, t), unit, seasons=(name != "ps"))
            used.append(name)
    if not args.sem_vento and all(n in V and tod_dim in V[n].dimensions for n in ("ucomp", "vcomp")):
        process("vento", lambda t: np.hypot(read("ucomp", t), read("vcomp", t)), "ms", seasons=False)
        used += ["ucomp", "vcomp"]
    if not used:
        sys.exit("Nenhuma das variaveis esperadas (ts, temp, ps, ucomp, vcomp) tem ciclo diurno no arquivo.")
    print("Variaveis usadas: " + ", ".join(used)
          + ("" if "ts" in used else "  (o arquivo nao tem temperatura da superficie por hora)"))

    sitio = np.full(shape, "", dtype=object)
    for nome, (slat, slon) in SITIOS.items():
        i = int(np.argmin(np.abs(lat - slat)))
        j = int(np.argmin(np.abs(((lon - slon + 180) % 360) - 180)))
        sitio[i, j] = nome
    names = list(cols)
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lat", "lon_leste", "lon_180", "sitio"] + names)
        for i in range(lat.size):
            for j in range(lon.size):
                row = [f"{lat[i]:.3f}", f"{lon[j]:.3f}", f"{((lon[j] + 180) % 360) - 180:.3f}", sitio[i, j]]
                row += ["" if not np.isfinite(cols[n][i, j]) else f"{cols[n][i, j]:.6g}" for n in names]
                w.writerow(row)
    print(f"{lat.size * lon.size} pontos x {len(names) + 4} colunas gravados em {args.output}")
    for nome in SITIOS:
        i, j = np.argwhere(sitio == nome)[0]
        extra = ", ".join(f"{n}={cols[n][i, j]:.4g}" for n in names
                          if n.startswith("amp_diurna") and n.endswith("_media"))
        print(f"  {nome}: {extra}")


if __name__ == "__main__":
    main()