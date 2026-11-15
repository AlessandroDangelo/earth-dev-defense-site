#!/usr/bin/env python3
"""Baixa do Meteomatics um ano de dados diarios para locais candidatos a analogos
de Marte na Terra: os locais nomeados e, com --grid, uma grade global so em
terra firme.

Saidas (prefixo "terra", ou "terra_grade" quando ha --grid):
  <prefixo>_diario.csv     uma linha por local e por dia
  <prefixo>_por_local.csv  uma linha por local: media/min/max de cada variavel,
                           amplitudes termicas, dias com neve e dados estaticos

Variaveis: tres grupos de ate 10 parametros diarios (clima a 2 m; superficie,
nuvens e aerossois; solo e radiacao) mais dados estaticos (elevacao, uso do solo).
Parametros que a conta recusar sao descartados automaticamente.

Credenciais: variaveis de ambiente METEOMATICS_USER e METEOMATICS_PASS
(ou --user/--password). Nao grave a senha em arquivo versionado.

Exemplos:
  python meteomatics_download.py --grid 5 --dry-run   # quantos pontos e consultas
  python meteomatics_download.py --grid 5 --check     # testa os parametros na conta
  python meteomatics_download.py --grid 5             # baixa (retoma pelo cache se cair)
  python meteomatics_download.py --grid 5 --parte 1/3 --prefixo terra_p1   # dividir entre colegas
  python meteomatics_download.py --juntar terra_p1 terra_p2 terra_p3 --prefixo terra_grade

A grade usa a mascara de terra do pacote global-land-mask (pip install global-land-mask)
e afina as longitudes perto dos polos para nao super-representar essas regioes.

So usa a biblioteca padrao (Python 3.8+), alem do global-land-mask para --grid.
"""
import argparse
import base64
import csv
import datetime as dt
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request

API_URL = "https://api.meteomatics.com"

# Nomes conferidos na documentacao do Meteomatics (ate 10 por consulta).
GROUPS = {
    "clima": [
        "t_mean_2m_24h:K", "t_min_2m_24h:K", "t_max_2m_24h:K",
        "sfc_pressure_mean_24h:Pa", "relative_humidity_mean_2m_24h:p",
        "wind_speed_mean_10m_24h:ms", "wind_gusts_10m_24h:ms",
        "global_rad_24h:J", "precip_24h:mm", "uv_max_24h:idx",
    ],
    "superficie": [
        "t_mean_0m_24h:K", "t_min_0m_24h:K", "t_max_0m_24h:K",
        "dew_point_mean_2m_24h:K", "total_cloud_cover_mean_24h:p",
        "clear_sky_rad_24h:J", "evaporation_24h:mm", "snow_depth:cm",
        "total_aod_550nm:idx", "dust_aod_550nm:idx",
    ],
    "solo_radiacao": [
        "volumetric_soil_water_mean_-5cm_24h:m3m3", "soil_moisture_index_-5cm:idx",
        "longwave_rad_24h:J", "relative_humidity_min_2m_24h:p",
        "relative_humidity_max_2m_24h:p", "frost_depth:cm", "pm10:ugm3",
    ],
}
STATIC = ["elevation:m", "land_usage:idx", "soil_type:idx", "is_open_water_body:idx"]

# Coordenadas aproximadas (suficientes para dados de modelo). tipo: analogo | controle
SITES = [
    ("Atacama - Yungay", -24.10, -70.00, "analogo"),
    ("Atacama - Chajnantor", -23.02, -67.75, "analogo"),
    ("Licancabur", -22.83, -67.88, "analogo"),
    ("Ojos del Salado", -27.11, -68.54, "analogo"),
    ("Salar de Uyuni", -20.13, -67.49, "analogo"),
    ("Aconcagua", -32.65, -70.01, "analogo"),
    ("Vales Secos de McMurdo", -77.63, 162.90, "analogo"),
    ("Vostok", -78.46, 106.84, "analogo"),
    ("Dome C", -75.10, 123.33, "analogo"),
    ("Dome Argus", -80.37, 77.37, "analogo"),
    ("Ilha Devon - Haughton", 75.38, -89.67, "analogo"),
    ("Svalbard - Bockfjorden", 79.40, 13.30, "analogo"),
    ("Groenlandia - Summit", 72.58, -38.46, "analogo"),
    ("Islandia - Askja", 65.05, -16.75, "analogo"),
    ("Mauna Loa - HI-SEAS", 19.60, -155.49, "analogo"),
    ("Utah - MDRS", 38.41, -110.79, "analogo"),
    ("Deserto de Mojave", 35.00, -115.50, "analogo"),
    ("Vale da Morte", 36.50, -117.00, "analogo"),
    ("Rio Tinto", 37.72, -6.55, "analogo"),
    ("Teide", 28.27, -16.64, "analogo"),
    ("Lanzarote", 29.00, -13.70, "analogo"),
    ("Danakil - Dallol", 14.24, 40.30, "analogo"),
    ("Namibe", -24.75, 15.30, "analogo"),
    ("Saara - Tanezrouft", 24.00, 0.00, "analogo"),
    ("Kilimanjaro", -3.07, 37.35, "analogo"),
    ("Wadi Rum", 29.57, 35.42, "analogo"),
    ("Rub al Khali", 20.00, 50.00, "analogo"),
    ("Deserto de Lut", 30.60, 59.07, "analogo"),
    ("Ladakh", 34.15, 77.58, "analogo"),
    ("Planalto do Tibete - Changtang", 33.00, 86.00, "analogo"),
    ("Bacia de Qaidam", 38.40, 93.30, "analogo"),
    ("Everest", 27.99, 86.93, "analogo"),
    ("Gobi", 42.50, 105.00, "analogo"),
    ("Oymyakon", 63.46, 142.79, "analogo"),
    ("Denali", 63.07, -151.00, "analogo"),
    ("Pilbara", -21.20, 119.30, "analogo"),
    ("Arkaroola", -30.30, 139.30, "analogo"),
    ("Deserto de Simpson", -25.00, 137.00, "analogo"),
    ("Manaus", -3.10, -60.00, "controle"),
    ("Londres", 51.50, -0.13, "controle"),
    ("Singapura", 1.35, 103.80, "controle"),
    ("Sao Paulo", -23.55, -46.63, "controle"),
    ("Nova York", 40.71, -74.01, "controle"),
]

INVALID = {-999.0, -888.0, -777.0, -666.0}


def col(param):
    return param.replace(":", "_")


class Client:
    def __init__(self, api_url, user, password, cache_dir):
        self.api = api_url.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": "Basic " + token,
                        "User-Agent": "meteomatics-download/2.0"}
        self.cache_dir = cache_dir
        self.n_queries = self.n_cached = 0
        if cache_dir:
            os.makedirs(cache_dir, exist_ok=True)

    def get(self, path, timeout=300, cache=True):
        """-> (status_http, texto). Respostas 200 ficam em cache no disco."""
        cpath = None
        if cache and self.cache_dir:
            cpath = os.path.join(self.cache_dir, hashlib.sha1(path.encode()).hexdigest() + ".json")
            if os.path.exists(cpath):
                self.n_cached += 1
                with open(cpath, encoding="utf-8") as f:
                    return 200, f.read()
        req = urllib.request.Request(self.api + "/" + path.lstrip("/"), headers=self.headers)
        self.n_queries += 1
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    text = r.read().decode("utf-8", errors="replace")
                if cpath:
                    with open(cpath + ".tmp", "w", encoding="utf-8") as f:
                        f.write(text)
                    os.replace(cpath + ".tmp", cpath)
                return 200, text
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
                return e.code, body
            except Exception as e:  # noqa: BLE001
                if attempt < 2:
                    time.sleep(10)
                    continue
                return 0, str(e)


def query(client, when, params, batch, cache=True):
    """when: 'inicio--fim:P1D' ou um instante. -> (dados, erro)"""
    locs = "+".join(f"{lat:.4f},{lon:.4f}" for _, lat, lon, _ in batch)
    status, text = client.get(f"{when}/{','.join(params)}/{locs}/json", cache=cache)
    if status != 200:
        return None, f"HTTP {status}: {text[:300]}"
    try:
        data = json.loads(text)
    except ValueError:
        return None, "resposta nao e JSON: " + text[:200]
    if data.get("status", "OK") != "OK" or "data" not in data:
        return None, "resposta sem dados: " + text[:300]
    return data, None


def collect(data, batch, table):
    """table[(nome, AAAA-MM-DD)][parametro] = valor"""
    for block in data["data"]:
        param = block["parameter"]
        for coord in block.get("coordinates", []):
            lat, lon = float(coord["lat"]), float(coord["lon"])
            site = min(batch, key=lambda s: abs(s[1] - lat) + abs(s[2] - lon))
            for d in coord.get("dates", []):
                v = d.get("value")
                if v is None:
                    continue
                v = float(v)
                if v in INVALID:
                    if v == -666.0 and "cloud_cover" in param:
                        v = 0.0                      # -666 = ceu sem nuvens
                    else:
                        continue
                table.setdefault((site[0], d["date"][:10]), {})[param] = v


def grid_sites(step, keep_ocean):
    """Grade com longitudes afinadas por cos(lat); so terra firme, salvo keep_ocean."""
    is_land = None
    if not keep_ocean:
        try:
            from global_land_mask import globe
            is_land = globe.is_land
        except ImportError:
            sys.exit("A grade so em terra firme requer: pip install global-land-mask\n"
                     "(ou use --incluir-oceano)")
    pts = []
    lat = -90.0 + step / 2.0
    while lat < 90.0:
        n = max(1, round(360.0 / step * math.cos(math.radians(lat))))
        for i in range(n):
            lon = -180.0 + (i + 0.5) * 360.0 / n
            if is_land is None or bool(is_land(lat, lon)):
                pts.append((f"grade_{lat:+06.2f}_{lon:+07.2f}", round(lat, 4), round(lon, 4), "grade"))
        lat += step
    return pts


def load_sites(args):
    sites = []
    if args.sites:
        with open(args.sites, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                sites.append((r["nome"], float(r["lat"]), float(r["lon"]), r.get("tipo") or "analogo"))
    elif not args.sem_locais:
        sites = list(SITES)
    if args.grid:
        sites += grid_sites(args.grid, args.incluir_oceano)
    if args.parte:
        i, n = (int(x) for x in args.parte.split("/"))
        sites = sites[i - 1::n]
    return sites


class Stats:
    """Acumula media/min/max por local sem guardar os dados diarios na memoria."""

    def __init__(self):
        self.acc = {}          # nome -> coluna -> [n, soma, min, max]
        self.days = {}

    def add(self, name, vals):
        self.days[name] = self.days.get(name, 0) + 1
        a = self.acc.setdefault(name, {})
        extra = {}
        for tag, lo, hi in [("amplitude_termica_diaria", "t_min_2m_24h_K", "t_max_2m_24h_K"),
                            ("amplitude_superficie_diaria", "t_min_0m_24h_K", "t_max_0m_24h_K")]:
            if lo in vals and hi in vals:
                extra[tag] = vals[hi] - vals[lo]
        if "snow_depth_cm" in vals:
            extra["dia_com_neve"] = 1.0 if vals["snow_depth_cm"] > 0 else 0.0
        for k, v in list(vals.items()) + list(extra.items()):
            s = a.get(k)
            if s is None:
                a[k] = [1, v, v, v]
            else:
                s[0] += 1; s[1] += v; s[2] = min(s[2], v); s[3] = max(s[3], v)


def write_summary(path, stats, info, static, cols):
    static_cols = sorted({k for v in static.values() for k in v})
    header = ["local", "tipo", "lat", "lon", "n_dias"] + static_cols
    for c in cols:
        header += [c + "_mean", c + "_min", c + "_max"]
    header += ["amplitude_termica_diaria_media", "amplitude_superficie_diaria_media",
               "fracao_dias_com_neve"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for name in sorted(stats.acc):
            _, lat, lon, tipo = info[name]
            a = stats.acc[name]
            row = [name, tipo, lat, lon, stats.days[name]] + [static.get(name, {}).get(k, "") for k in static_cols]
            for c in cols:
                s = a.get(c)
                row += [s[1] / s[0], s[2], s[3]] if s else ["", "", ""]
            for k in ("amplitude_termica_diaria", "amplitude_superficie_diaria", "dia_com_neve"):
                s = a.get(k)
                row.append(s[1] / s[0] if s else "")
            w.writerow(row)
    return len(stats.acc)


def join(prefixes, out_prefix):
    """Junta as saidas de varias execucoes (--parte) e recalcula o resumo."""
    cols, info, static, stats = [], {}, {}, Stats()
    for p in prefixes:
        with open(f"{p}_diario.csv", encoding="utf-8", newline="") as f:
            for c in next(csv.reader(f))[5:]:
                if c not in cols:
                    cols.append(c)
        with open(f"{p}_por_local.csv", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            first = r.fieldnames.index("n_dias") + 1
            last = next(i for i, c in enumerate(r.fieldnames) if c.endswith("_mean"))
            for row in r:
                static[row["local"]] = {k: row[k] for k in r.fieldnames[first:last]}
    seen = set()
    with open(f"{out_prefix}_diario.csv", "w", newline="", encoding="utf-8") as out:
        w = csv.writer(out)
        w.writerow(["local", "tipo", "lat", "lon", "data"] + cols)
        for p in prefixes:
            with open(f"{p}_diario.csv", encoding="utf-8", newline="") as f:
                for row in csv.DictReader(f):
                    key = (row["local"], row["data"])
                    if key in seen:
                        continue
                    seen.add(key)
                    info[row["local"]] = (row["local"], row["lat"], row["lon"], row["tipo"])
                    vals = {c: float(row[c]) for c in cols if row.get(c) not in (None, "")}
                    stats.add(row["local"], vals)
                    w.writerow([row["local"], row["tipo"], row["lat"], row["lon"], row["data"]]
                               + [row.get(c, "") for c in cols])
    n = write_summary(f"{out_prefix}_por_local.csv", stats, info, static, cols)
    print(f"{len(seen)} linhas diarias e {n} locais gravados em {out_prefix}_diario.csv / _por_local.csv")


def main():
    ap = argparse.ArgumentParser(description="Dados diarios do Meteomatics para locais candidatos.")
    ap.add_argument("--user", default=os.environ.get("METEOMATICS_USER"))
    ap.add_argument("--password", default=os.environ.get("METEOMATICS_PASS"))
    ap.add_argument("--start", help="AAAA-MM-DD (padrao: um ano antes de --end)")
    ap.add_argument("--end", help="AAAA-MM-DD (padrao: ontem, UTC)")
    ap.add_argument("--sites", help="CSV com colunas nome,lat,lon[,tipo] no lugar da lista embutida")
    ap.add_argument("--sem-locais", action="store_true", help="nao inclui a lista embutida de locais")
    ap.add_argument("--grid", type=float, help="acrescenta grade global com este passo em graus")
    ap.add_argument("--incluir-oceano", action="store_true", help="nao filtra a grade por terra firme")
    ap.add_argument("--grupos", default=",".join(GROUPS), help="grupos de variaveis: " + ", ".join(GROUPS))
    ap.add_argument("--parte", help="i/n: processa so a i-esima de n fatias dos locais")
    ap.add_argument("--juntar", nargs="+", metavar="PREFIXO", help="junta saidas de varias execucoes")
    ap.add_argument("--batch", type=int, default=10, help="locais por consulta (padrao 10)")
    ap.add_argument("--dry-run", action="store_true", help="so mostra pontos e consultas previstas")
    ap.add_argument("--check", action="store_true", help="so testa os parametros na conta")
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--prefixo", help="prefixo das saidas (padrao: terra ou terra_grade)")
    ap.add_argument("--cache-dir", default="mm_cache")
    ap.add_argument("--api-url", default=API_URL)
    args = ap.parse_args()
    prefix = args.prefixo or ("terra_grade" if args.grid else "terra")

    if args.juntar:
        join(args.juntar, prefix)
        return

    end = dt.date.fromisoformat(args.end) if args.end else (
        dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1))
    start = dt.date.fromisoformat(args.start) if args.start else end - dt.timedelta(days=365)
    series = f"{start}T00:00:00Z--{end}T00:00:00Z:P1D"
    groups = {g: list(GROUPS[g]) for g in args.grupos.split(",") if g.strip() in GROUPS}
    sites = load_sites(args)
    if not sites:
        sys.exit("Nenhum local selecionado.")
    n_batches = math.ceil(len(sites) / max(1, args.batch))
    n_grid = sum(1 for s in sites if s[3] == "grade")
    print(f"{len(sites)} locais ({n_grid} de grade), {start} a {end}")
    print(f"Consultas previstas: cerca de {n_batches * (len(groups) + 1) + len(groups) + 2} "
          f"({n_batches} lotes x {len(groups)} grupos + dados estaticos + testes); "
          "as ja feitas ficam em cache e nao contam de novo")
    if args.dry_run:
        return
    if not args.user or not args.password:
        sys.exit("Defina METEOMATICS_USER e METEOMATICS_PASS (ou use --user/--password).")
    client = Client(args.api_url, args.user, args.password, args.cache_dir)

    status, text = client.get("user_stats_json", cache=False)
    client.n_queries -= 1
    print("Conta:", (text[:700] if status == 200 else f"nao consegui ler os limites (HTTP {status})"))

    # ---- teste: cada grupo inteiro em 1 local; so testa um a um se o grupo falhar ----
    probe_when = f"{end - dt.timedelta(days=2)}T00:00:00Z--{end}T00:00:00Z:P1D"
    for g, params in list(groups.items()) + [("estatico", STATIC)]:
        target = groups[g] if g in groups else STATIC
        data, err = query(client, probe_when, params, sites[:1], cache=False)
        if err and err.startswith("HTTP 401"):
            sys.exit("Usuario ou senha recusados pela API (HTTP 401).")
        if data:
            print(f"  grupo {g}: {len(params)} parametros ok")
            continue
        ok, n_before = [], len(params)
        for p in list(params):
            d1, e1 = query(client, probe_when, [p], sites[:1], cache=False)
            print(f"    {'ok      ' if d1 else 'RECUSADO'} {p}" + ("" if d1 else f"  ({e1[:100]})"))
            if d1:
                ok.append(p)
            time.sleep(args.delay)
        target[:] = ok
        print(f"  grupo {g}: {len(ok)} de {n_before} parametros aceitos")
    groups = {g: p for g, p in groups.items() if p}
    if not groups:
        sys.exit("Nenhum parametro aceito.")
    data, err = query(client, f"{start}T00:00:00Z--{start + dt.timedelta(days=1)}T00:00:00Z:P1D",
                      next(iter(groups.values()))[:1], sites[:1], cache=False)
    print(f"  historico em {start}: {'ok' if data else 'RECUSADO (' + err[:160] + ')'}")
    if not data:
        sys.exit("A conta nao entrega dados dessa data; ajuste --start.")
    if args.check:
        print(f"Consultas usadas no teste: {client.n_queries}")
        return

    batch_size = max(1, args.batch)

    def run(when, params, batch):
        """Consulta um lote; se o lote for recusado, tenta local por local."""
        table = {}
        data, err = query(client, when, params, batch)
        if data is None and len(batch) > 1:
            print(f"[aviso] lote recusado ({err[:100]}); tentando local por local")
            for s in batch:
                d1, e1 = query(client, when, params, [s])
                if d1:
                    collect(d1, [s], table)
                else:
                    print(f"[falha] {s[0]}: {e1[:120]}")
                time.sleep(args.delay)
        elif data is None:
            print(f"[falha] {batch[0][0]}: {err[:120]}")
        else:
            collect(data, batch, table)
        return table

    # ---- dados estaticos (um instante) e descarte de pontos de grade sobre agua ----
    static = {}
    if STATIC:
        print("Dados estaticos...")
        for i in range(0, len(sites), batch_size):
            batch = sites[i:i + batch_size]
            for (name, _), vals in run(f"{end}T00:00:00Z", STATIC, batch).items():
                static[name] = {col(p): v for p, v in vals.items()}
            time.sleep(args.delay)
        water = {n for n, v in static.items() if v.get("is_open_water_body_idx") == 1.0}
        before = len(sites)
        sites = [s for s in sites if not (s[3] == "grade" and s[0] in water)]
        if before != len(sites):
            print(f"  {before - len(sites)} pontos de grade sobre agua descartados; restam {len(sites)}")

    # ---- series diarias: por lote, todos os grupos; grava e acumula o resumo ----
    params_all = [p for g in groups.values() for p in g]
    cols = [col(p) for p in params_all]
    info = {s[0]: s for s in sites}
    stats = Stats()
    n_rows = 0
    with open(f"{prefix}_diario.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["local", "tipo", "lat", "lon", "data"] + cols)
        for bi, i in enumerate(range(0, len(sites), batch_size), 1):
            batch = sites[i:i + batch_size]
            table = {}
            for params in groups.values():
                for key, vals in run(series, params, batch).items():
                    table.setdefault(key, {}).update(vals)
                time.sleep(args.delay)
            for (name, date), vals in sorted(table.items()):
                _, lat, lon, tipo = info[name]
                cv = {col(p): v for p, v in vals.items()}
                stats.add(name, cv)
                w.writerow([name, tipo, lat, lon, date] + [cv.get(c, "") for c in cols])
                n_rows += 1
            f.flush()
            print(f"  lote {bi}/{math.ceil(len(sites) / batch_size)}: "
                  f"{min(i + batch_size, len(sites))}/{len(sites)} locais "
                  f"({client.n_queries} consultas novas, {client.n_cached} do cache)", flush=True)

    n = write_summary(f"{prefix}_por_local.csv", stats, info, static, cols)
    print(f"\n{n_rows} linhas em {prefix}_diario.csv; {n} locais em {prefix}_por_local.csv")
    print(f"Consultas novas: {client.n_queries}; reaproveitadas do cache: {client.n_cached}")
    faltou = [s[0] for s in sites if s[0] not in stats.acc]
    if faltou:
        print(f"{len(faltou)} locais sem dados (rode de novo para tentar): " + ", ".join(faltou[:10])
              + (" ..." if len(faltou) > 10 else ""))


if __name__ == "__main__":
    main()