#!/usr/bin/env python3
"""Tabela global de Marte a partir da simulacao de referencia do modelo climatico
da NASA Ames (MGCM, FV3BETAOUT1), a mesma que alimenta a interface web do MCMC.

Baixa do NAS Data Portal (mesmas URLs que o MarsPull do AmesCAP usa):
  03340.fixed.nc          (~350 KB)  relevo, albedo, inercia termica
  03340.atmos_average.nc  (~4,5 GB)  medias de 5 sois ao longo de um ano marciano

e gera marte_global_por_ponto.csv: uma linha por ponto da grade (48 x 96 = 4.608
pontos, 3,75 graus), com media/min/max anuais e medias por estacao.

Exemplos:
  python mgcm_marte_global.py --fixed-only      # baixa so o arquivo pequeno e mostra o conteudo
  python mgcm_marte_global.py                   # baixa (retomavel) e extrai
  python mgcm_marte_global.py --no-download     # so extrai de arquivos ja baixados
  python mgcm_marte_global.py --inspect         # lista variaveis e dimensoes dos arquivos

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
FIXED = "03340.fixed.nc"
AVERAGE = "03340.atmos_average.nc"
UA = {"User-Agent": "mgcm-marte-global/1.0 (uso academico; script pessoal)"}

# locais com medicoes, para ligar o modelo aos dados dos rovers (lat, lon leste)
SITIOS = {"Jezero (Perseverance)": (18.4, 77.5), "Gale (Curiosity)": (-4.6, 137.4),
          "Elysium (InSight)": (4.5, 135.6)}
ESTACOES = [("ls000_090", 0, 90), ("ls090_180", 90, 180),
            ("ls180_270", 180, 270), ("ls270_360", 270, 360)]


def download(url, dest):
    """Baixa com retomada (Range) quando o servidor aceita."""
    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = dict(UA)
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:        # ja estava completo
            os.replace(part, dest)
            return
        raise
    with resp:
        if have and resp.status != 206:   # servidor ignorou o Range: recomeca
            have = 0
        total = have + int(resp.headers.get("Content-Length") or 0)
        mode = "ab" if have else "wb"
        done, t0, last = have, time.time(), 0
        with open(part, mode) as f:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if time.time() - last > 5:
                    last = time.time()
                    speed = (done - have) / max(time.time() - t0, 1e-6) / 1e6
                    pct = f"{100 * done / total:.1f}%" if total else "?"
                    print(f"  {os.path.basename(dest)}: {done / 1e6:.0f} MB ({pct}), {speed:.1f} MB/s",
                          flush=True)
    if total and os.path.getsize(part) < total:
        sys.exit(f"Download incompleto de {url}; rode de novo para retomar.")
    os.replace(part, dest)


def ensure(name, args):
    path = os.path.join(args.dir, name)
    if os.path.exists(path):
        return path
    if args.no_download:
        sys.exit(f"Arquivo ausente: {path}")
    print(f"Baixando {args.base_url}{name}")
    download(args.base_url + name, path)
    return path


def inspect(path):
    from netCDF4 import Dataset
    with Dataset(path) as nc:
        print(f"\n{os.path.basename(path)}  ({os.path.getsize(path) / 1e6:.1f} MB)")
        print("  dimensoes: " + ", ".join(f"{k}={len(v)}" for k, v in nc.dimensions.items()))
        for name, v in nc.variables.items():
            print(f"  {name:18s} {str(v.dimensions):40s} "
                  f"{getattr(v, 'units', ''):10s} {getattr(v, 'long_name', '')}")


def arr(v):
    import numpy as np
    a = np.ma.filled(np.ma.asarray(v, dtype="f8"), np.nan)
    return a


def main():
    ap = argparse.ArgumentParser(description="Tabela global de Marte a partir do MGCM da NASA Ames.")
    ap.add_argument("--dir", default="mgcm", help="pasta dos arquivos .nc")
    ap.add_argument("-o", "--output", default="marte_global_por_ponto.csv")
    ap.add_argument("--fixed-only", action="store_true", help="so baixa e mostra o arquivo fixed")
    ap.add_argument("--no-download", action="store_true")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--average-file", default=AVERAGE)
    ap.add_argument("--fixed-file", default=FIXED)
    ap.add_argument("--base-url", default=BASE_URL)
    args = ap.parse_args()
    os.makedirs(args.dir, exist_ok=True)

    try:
        import numpy as np
        from netCDF4 import Dataset
    except ImportError:
        sys.exit("Instale as dependencias: pip install numpy netCDF4")

    fixed_path = ensure(args.fixed_file, args)
    if args.fixed_only:
        inspect(fixed_path)
        return
    avg_path = ensure(args.average_file, args)
    if args.inspect:
        inspect(fixed_path)
        inspect(avg_path)
        return

    cols = {}
    with Dataset(fixed_path) as nc:
        lat, lon = arr(nc.variables["lat"][:]), arr(nc.variables["lon"][:])
        for src, name in [("zsurf", "elevacao_m"), ("alb", "albedo"),
                          ("thin", "inercia_termica"), ("emis", "emissividade")]:
            if src in nc.variables:
                cols[name] = arr(nc.variables[src][:])

    with Dataset(avg_path) as nc:
        V = nc.variables
        if not (np.allclose(arr(V["lat"][:]), lat) and np.allclose(arr(V["lon"][:]), lon)):
            sys.exit("As grades do fixed e do atmos_average nao coincidem.")
        nt = len(nc.dimensions["time"])
        ls = arr(V["areo"][:]).reshape(nt, -1)[:, 0] % 360.0 if "areo" in V else None
        k_sfc = int(np.argmax(arr(V["pfull"][:]))) if "pfull" in V else -1
        print(f"{os.path.basename(avg_path)}: {nt} tempos, grade {lat.size} x {lon.size}; "
              f"camada mais proxima do solo = indice {k_sfc}"
              + (f" ({arr(V['pfull'][:])[k_sfc]:.2f} mb)" if "pfull" in V else ""))

        def field(name):
            """-> array (tempo, lat, lon); em variaveis 3D pega a camada junto ao solo."""
            v = V[name]
            if "pfull" in v.dimensions:
                idx = [slice(None)] * v.ndim
                idx[v.dimensions.index("pfull")] = k_sfc
                return arr(v[tuple(idx)])
            return arr(v[:])

        def stats(prefix, data, seasons=False, only_mean=False):
            cols[prefix + "_media"] = np.nanmean(data, axis=0)
            if not only_mean:
                cols[prefix + "_min"] = np.nanmin(data, axis=0)
                cols[prefix + "_max"] = np.nanmax(data, axis=0)
            if seasons and ls is not None:
                for tag, a, b in ESTACOES:
                    sel = (ls >= a) & (ls < b)
                    if sel.any():
                        cols[f"{prefix}_{tag}"] = np.nanmean(data[sel], axis=0)

        used = []
        for src, prefix, seas, only_mean in [
                ("ts", "temp_superficie_K", True, False),
                ("temp", "temp_ar_K", True, False),
                ("ps", "pressao_Pa", True, False),
                ("taudust_VIS", "poeira_opacidade_vis", False, True),
                ("taudust_IR", "poeira_opacidade_ir", False, True),
                ("r", "umidade_especifica_kgkg", False, True),
                ("stress", "tensao_vento_Nm2", False, True),
                ("cldcol", "coluna_gelo_nuvem", False, True)]:
            if src in V:
                stats(prefix, field(src), seas, only_mean)
                used.append(src)
        if "ucomp" in V and "vcomp" in V:
            # velocidade do vento MEDIO de 5 sois (subestima a velocidade media instantanea)
            stats("vento_medio_vetorial_ms", np.hypot(field("ucomp"), field("vcomp")), False, False)
            used += ["ucomp", "vcomp"]
        if "co2ice_sfc" in V:
            cols["fracao_ano_com_gelo_co2"] = np.nanmean(field("co2ice_sfc") > 0, axis=0)
            used.append("co2ice_sfc")
        if "temp_superficie_K_max" in cols:
            cols["amplitude_sazonal_superficie_K"] = (cols["temp_superficie_K_max"]
                                                     - cols["temp_superficie_K_min"])
        print("Variaveis usadas: " + ", ".join(used))

    LON, LAT = np.meshgrid(lon, lat)
    sitio = np.full(LAT.shape, "", dtype=object)
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
        extra = ", ".join(f"{n}={cols[n][i, j]:.4g}" for n in
                          ("temp_superficie_K_media", "pressao_Pa_media", "elevacao_m") if n in cols)
        print(f"  {nome}: celula lat {lat[i]:.2f}, lon {lon[j]:.2f}  {extra}")


if __name__ == "__main__":
    main()