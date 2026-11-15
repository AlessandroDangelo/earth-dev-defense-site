#!/usr/bin/env python3
"""Similaridade climatica entre regioes de Marte e locais da Terra.

Marte: marte_global_por_ponto.csv, gerado pelo mgcm_marte_global.py a partir de
       03340.atmos_average.nc e 03340.fixed.nc (se o CSV nao existir, o script
       tenta gera-lo com `mgcm_marte_global.py --no-download`). Se existir
       marte_ciclo_diurno_por_ponto.csv (mgcm_ciclo_diurno.py), a amplitude
       termica diaria tambem entra na comparacao.
Terra: terra_grade_por_local.csv (ou terra_por_local.csv) + terra_*_diario.csv
       do Meteomatics (a versao nova do download ja traz temperatura da
       superficie e aerossois) e, se existirem, terra_power_por_local.csv e
       terra_power_diario.csv do NASA POWER para completar.

Metodo (similaridade de Gower): para cada variavel,
    s = 1 - |terra - marte| / amplitude        (amplitude medida em Terra + Marte)
e a similaridade do par (local da Terra, celula de Marte) e a media ponderada das
variaveis. Pressao entra em log10 e precipitacao em log(1 + x).

Saidas (prefixo "similaridade"):
  _terra.csv           cada local da Terra: melhor celula de Marte, similaridade,
                       similaridade por variavel e com Jezero, Gale e Elysium
  _marte.csv           cada celula de Marte: melhor local da Terra e regiao
  _regioes_marte.csv   Marte dividido em k regioes climaticas e os locais da
                       Terra mais parecidos com cada uma
  _mapa_marte.png, _mapa_terra.png, _regioes_marte.png   (se houver matplotlib)

Exemplos:
  python similaridade_marte_terra.py
  python similaridade_marte_terra.py --sem pressao        # ignora a pressao
  python similaridade_marte_terra.py --pesos pressao=0.5,temp_ar=2
  python similaridade_marte_terra.py -k 8 --so-terra-firme

Requer numpy e pandas; scikit-learn (regioes) e matplotlib (mapas) sao opcionais.
"""
import argparse
import os
import subprocess
import sys

import numpy as np
import pandas as pd

# variavel -> (descricao, transformacao)
VARS = {
    "temp_ar": ("temperatura media do ar (K)", None),
    "amp_sazonal_ar": ("variacao da temperatura do ar ao longo do ano (K)", None),
    "pressao": ("pressao de superficie (Pa, em log10)", np.log10),
    "precip": ("precipitacao (mm/dia, em log(1+x))", np.log1p),
    "temp_sup": ("temperatura media da superficie (K)", None),
    "amp_sazonal_sup": ("variacao da temperatura da superficie ao longo do ano (K)", None),
    "poeira": ("profundidade optica de poeira/aerossois", None),
    "amp_diurna_ar": ("amplitude termica diaria do ar (K)", None),
    "amp_diurna_sup": ("amplitude termica diaria da superficie (K)", None),
}
SITIOS = ["Jezero (Perseverance)", "Gale (Curiosity)", "Elysium (InSight)"]


def first_existing(*names):
    for n in names:
        if n and os.path.exists(n):
            return n
    return None


def seasonal_amplitude(daily_path, col, window=5):
    """Max - min, ao longo do ano, da media movel de `window` dias (por local).
    Equivale as medias de 5 sois do arquivo de Marte."""
    d = pd.read_csv(daily_path, usecols=["local", "data", col])
    d = d.dropna(subset=[col]).sort_values(["local", "data"])
    roll = d.groupby("local")[col].transform(
        lambda s: s.rolling(window, center=True, min_periods=window).mean())
    g = roll.groupby(d["local"])
    return (g.max() - g.min()).rename("amp")


def load_earth(args):
    notes = []
    base = pd.read_csv(args.terra)
    if args.terra_extra and os.path.exists(args.terra_extra) and args.terra_extra != args.terra:
        extra = pd.read_csv(args.terra_extra)
        novos = extra[~extra["local"].isin(base["local"])]
        if len(novos):
            base = pd.concat([base, novos], ignore_index=True)
    E = base[["local", "tipo", "lat", "lon"]].copy()
    E["temp_ar"] = base["t_mean_2m_24h_K_mean"]
    E["pressao"] = base["sfc_pressure_mean_24h_Pa_mean"]
    E["precip"] = base["precip_24h_mm_mean"]
    # amplitudes diarias (so entram se houver o arquivo de ciclo diurno de Marte)
    if "amplitude_termica_diaria_media" in base:
        E["amp_diurna_ar"] = base["amplitude_termica_diaria_media"]
    if "amplitude_superficie_diaria_media" in base:
        E["amp_diurna_sup"] = base["amplitude_superficie_diaria_media"]

    amp = None
    for path in [args.terra_diario, args.terra_diario_extra]:
        if path and os.path.exists(path):
            a = seasonal_amplitude(path, "t_mean_2m_24h_K")
            amp = a if amp is None else amp.combine_first(a)
    if amp is not None:
        E["amp_sazonal_ar"] = E["local"].map(amp)
    faltam = E["amp_sazonal_ar"].isna() if "amp_sazonal_ar" in E else pd.Series(True, index=E.index)
    if faltam.any():
        aprox = base["t_mean_2m_24h_K_max"] - base["t_mean_2m_24h_K_min"]
        E.loc[faltam, "amp_sazonal_ar"] = aprox[faltam]
        notes.append(f"{int(faltam.sum())} locais sem dados diarios: variacao anual aproximada "
                     "por max - min das medias diarias (um pouco maior que a de 5 dias)")

    # superficie e aerossois do proprio Meteomatics (versao nova do download), se houver
    if "t_mean_0m_24h_K_mean" in base:
        E["temp_sup"] = base["t_mean_0m_24h_K_mean"]
        amp0 = None
        for path in [args.terra_diario, args.terra_diario_extra]:
            if path and os.path.exists(path) and "t_mean_0m_24h_K" in pd.read_csv(path, nrows=0).columns:
                a = seasonal_amplitude(path, "t_mean_0m_24h_K")
                amp0 = a if amp0 is None else amp0.combine_first(a)
        if amp0 is not None:
            E["amp_sazonal_sup"] = E["local"].map(amp0)
        notes.append("temperatura da superficie na Terra = t_mean_0m_24h do Meteomatics")
    if "total_aod_550nm_idx_mean" in base:
        E["poeira"] = base["total_aod_550nm_idx_mean"]
        notes.append("poeira na Terra = profundidade optica total de aerossois (550 nm) do Meteomatics")

    # NASA POWER preenche o que o Meteomatics nao trouxe
    def fill(var, serie):
        mapped = E["local"].map(serie)
        E[var] = E[var].fillna(mapped) if var in E else mapped

    if args.power and os.path.exists(args.power):
        P = pd.read_csv(args.power).set_index("local")
        if "TS_K_mean" in P:
            fill("temp_sup", P["TS_K_mean"])
        aod = [c for c in P.columns if c.upper().startswith("AOD") and c.endswith("_mean")]
        if aod:
            fill("poeira", P[aod[0]])
            notes.append(f"NASA POWER ({aod[0]}) completa a poeira onde faltar")
        if args.power_diario and os.path.exists(args.power_diario):
            head = pd.read_csv(args.power_diario, nrows=0).columns
            if "TS_K" in head:
                fill("amp_sazonal_sup", seasonal_amplitude(args.power_diario, "TS_K"))
    elif "temp_sup" not in E:
        notes.append("sem dados de superficie (Meteomatics novo ou NASA POWER): "
                     "temperatura da superficie e poeira ficam fora")
    return E, notes


def load_mars(args):
    if not os.path.exists(args.marte):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mgcm_marte_global.py")
        print(f"{args.marte} nao existe; gerando a partir dos .nc...")
        if not os.path.exists(script) or subprocess.call(
                [sys.executable, script, "--no-download", "-o", args.marte]) != 0:
            sys.exit("Nao consegui gerar a tabela de Marte. Rode: python mgcm_marte_global.py --no-download")
    m = pd.read_csv(args.marte)
    M = m[["lat", "lon_leste", "lon_180", "sitio"]].copy()
    M["sitio"] = M["sitio"].fillna("")
    for c in ["elevacao_m", "albedo"]:
        if c in m:
            M[c] = m[c]
    M["temp_ar"] = m["temp_ar_K_media"]
    M["amp_sazonal_ar"] = m["temp_ar_K_max"] - m["temp_ar_K_min"]
    M["pressao"] = m["pressao_Pa_media"]
    M["precip"] = 0.0                       # nao chove em Marte
    M["temp_sup"] = m["temp_superficie_K_media"]
    M["amp_sazonal_sup"] = m["temp_superficie_K_max"] - m["temp_superficie_K_min"]
    if "poeira_opacidade_vis_media" in m:
        M["poeira"] = m["poeira_opacidade_vis_media"]
    if args.marte_diurno and os.path.exists(args.marte_diurno):
        d = pd.read_csv(args.marte_diurno)
        key = lambda t: (t["lat"].round(2).astype(str) + "_" + t["lon_leste"].round(2).astype(str))
        same = (len(d) == len(M) and np.allclose(d["lat"], M["lat"], atol=0.01)
                and np.allclose(d["lon_leste"], M["lon_leste"], atol=0.01))
        dk = d.set_index(key(d))
        k = key(M)
        resumo = []
        for var, col in [("amp_diurna_ar", "amp_diurna_temp_ar_K_media"),
                         ("amp_diurna_sup", "amp_diurna_temp_superficie_K_media")]:
            if col in d:
                M[var] = d[col].to_numpy() if same else k.map(dk[col]).to_numpy()
                resumo.append(f"{var}: {int(np.isfinite(M[var].astype(float)).sum())}/{len(M)} celulas com valor")
        print(f"Ciclo diurno de Marte lido de {args.marte_diurno} "
              f"({'mesma grade' if same else 'grade diferente, casado por coordenada'}; "
              + "; ".join(resumo) + ")")
    return M


def transformed(df, var):
    f = VARS[var][1]
    x = df[var].astype(float).to_numpy()
    return f(x) if f else x


def pair_matrix(E, M, used, weights):
    """Similaridade (Ne x Nm) usando, para cada local, as variaveis que ele tem."""
    num = np.zeros((len(E), len(M)), dtype=np.float32)
    den = np.zeros((len(E), 1), dtype=np.float32)
    ranges = {}
    for v in used:
        e, m = transformed(E, v), transformed(M, v)
        allv = np.concatenate([e[np.isfinite(e)], m])
        rng = float(allv.max() - allv.min()) or 1.0
        ranges[v] = rng
        ok = np.isfinite(e)
        s = 1.0 - np.abs(np.where(ok, e, 0.0)[:, None] - m[None, :]) / rng
        w = weights.get(v, 1.0)
        num += (w * s * ok[:, None]).astype(np.float32)
        den += (w * ok[:, None]).astype(np.float32)
    return num / np.maximum(den, 1e-9), ranges


def main():
    ap = argparse.ArgumentParser(description="Similaridade Marte-Terra por regiao.")
    ap.add_argument("--marte", default="marte_global_por_ponto.csv")
    ap.add_argument("--marte-diurno", default="marte_ciclo_diurno_por_ponto.csv",
                    help="saida do mgcm_ciclo_diurno.py (opcional)")
    ap.add_argument("--terra", default=first_existing("terra_grade_por_local.csv", "terra_por_local.csv"))
    ap.add_argument("--terra-extra", default="terra_por_local.csv",
                    help="locais adicionais (os que nao estiverem em --terra)")
    ap.add_argument("--terra-diario", default=first_existing("terra_grade_diario.csv", "terra_diario.csv"))
    ap.add_argument("--terra-diario-extra", default="terra_diario.csv")
    ap.add_argument("--power", default="terra_power_por_local.csv")
    ap.add_argument("--power-diario", default="terra_power_diario.csv")
    ap.add_argument("--sem", default="", help="variaveis a ignorar, ex.: pressao,poeira")
    ap.add_argument("--pesos", default="", help="ex.: pressao=0.5,temp_ar=2 (padrao: 1)")
    ap.add_argument("-k", type=int, default=6, help="numero de regioes climaticas de Marte")
    ap.add_argument("--so-terra-firme", action="store_true",
                    help="descarta pontos de grade no oceano (requer pip install global-land-mask)")
    ap.add_argument("--prefixo", default="similaridade")
    args = ap.parse_args()
    if not args.terra:
        sys.exit("Nao achei terra_grade_por_local.csv nem terra_por_local.csv; use --terra.")

    E, notes = load_earth(args)
    M = load_mars(args)
    print(f"Terra: {len(E)} locais ({args.terra})   Marte: {len(M)} celulas ({args.marte})")

    try:
        from global_land_mask import globe
        E["em_terra_firme"] = globe.is_land(E["lat"].to_numpy(), ((E["lon"].to_numpy() + 180) % 360) - 180)
        if args.so_terra_firme:
            E = E[E["em_terra_firme"] | (E["tipo"] != "grade")].reset_index(drop=True)
            print(f"  apos descartar oceano: {len(E)} locais")
    except Exception:  # noqa: BLE001
        if args.so_terra_firme:
            sys.exit("--so-terra-firme requer: pip install global-land-mask")
        if (E["tipo"] == "grade").any():
            notes.append("pontos de grade incluem oceano (instale global-land-mask e use "
                         "--so-terra-firme para descartar)")

    ignorar = {s.strip() for s in args.sem.split(",") if s.strip()}
    weights = {}
    for item in filter(None, (s.strip() for s in args.pesos.split(","))):
        k, v = item.split("=")
        weights[k.strip()] = float(v)
    used = [v for v in VARS if v in E and v in M and v not in ignorar and E[v].notna().any()]
    # uma variavel de Marte vazia (ou quase) sai da conta, em vez de derrubar todas as celulas
    for v in list(used):
        frac = float(np.isfinite(M[v].astype(float)).mean()) if len(M) else 0.0
        if frac < 0.9:
            used.remove(v)
            notes.append(f"variavel {v} ignorada: so {100 * frac:.0f}% das celulas de Marte tem valor"
                         + (" (rode de novo o mgcm_ciclo_diurno.py atualizado)" if v.startswith("amp_diurna") else ""))
    base_vars = [v for v in used if E[v].notna().all()]
    if not base_vars:
        sys.exit("Nenhuma variavel disponivel para todos os locais da Terra.")
    n_before = len(M)
    M = M.dropna(subset=used).reset_index(drop=True)
    if len(M) < n_before:
        notes.append(f"{n_before - len(M)} celulas de Marte sem algum valor foram descartadas")
    if M.empty:
        sys.exit("Nenhuma celula de Marte tem todas as variaveis; confira marte_global_por_ponto.csv.")

    print("\nVariaveis comparadas:")
    for v in used:
        n = int(E[v].notna().sum())
        print(f"  {v:16s} {VARS[v][0]:58s} Terra {E[v].min():.4g} a {E[v].max():.4g} ({n} locais) | "
              f"Marte {M[v].min():.4g} a {M[v].max():.4g}" + ("" if v in base_vars else "   [so parte dos locais]"))
    for n in notes:
        print("  [nota] " + n)

    S_base, _ = pair_matrix(E, M, base_vars, weights)
    S_full, ranges = pair_matrix(E, M, used, weights)
    area = np.cos(np.deg2rad(M["lat"].to_numpy()))          # peso de area das celulas
    has_full = E[used].notna().all(axis=1).to_numpy()

    # ---------- Terra: melhor celula de Marte para cada local ----------
    j = S_base.argmax(axis=1)
    T = E[["local", "tipo", "lat", "lon"] + (["em_terra_firme"] if "em_terra_firme" in E else [])].copy()
    T["similaridade_base"] = S_base.max(axis=1)
    T["similaridade_completa"] = np.where(has_full, S_full.max(axis=1), np.nan)
    T["similaridade_media_planeta"] = (S_base * area).sum(axis=1) / area.sum()
    T["marte_lat"] = M["lat"].to_numpy()[j]
    T["marte_lon_leste"] = M["lon_leste"].to_numpy()[j]
    if "elevacao_m" in M:
        T["marte_elevacao_m"] = M["elevacao_m"].to_numpy()[j]
    for v in used:
        e, m = transformed(E, v), transformed(M, v)[j]
        T["sim_" + v] = 1.0 - np.abs(e - m) / ranges[v]
    for nome in SITIOS:
        idx = np.flatnonzero(M["sitio"].to_numpy() == nome)
        if idx.size:
            T["sim_" + nome.split(" ")[0]] = S_base[:, idx[0]]
    for v in used:
        T[v + "_terra"] = E[v]
        T[v + "_marte"] = M[v].to_numpy()[j]
    T = T.sort_values("similaridade_base", ascending=False)
    T.to_csv(f"{args.prefixo}_terra.csv", index=False)

    # ---------- Marte: melhor local da Terra para cada celula ----------
    i = S_base.argmax(axis=0)
    R = M[["lat", "lon_leste", "lon_180", "sitio"] + [c for c in ("elevacao_m",) if c in M]].copy()
    R["melhor_local_terra"] = E["local"].to_numpy()[i]
    R["similaridade_base"] = S_base.max(axis=0)
    for v in used:
        R[v] = M[v]

    # ---------- regioes climaticas de Marte ----------
    regioes = None
    try:
        from sklearn.cluster import KMeans
        from sklearn.preprocessing import StandardScaler
        X = np.column_stack([transformed(M, v) for v in used if v != "precip"])
        lab = KMeans(n_clusters=args.k, n_init=10, random_state=0).fit_predict(
            StandardScaler().fit_transform(X))
        R["regiao"] = lab
        rows = []
        for r in range(args.k):
            sel = lab == r
            w = area[sel]
            sim_r = (S_base[:, sel] * w).sum(axis=1) / w.sum()
            top = np.argsort(-sim_r)[:5]
            row = {"regiao": r, "n_celulas": int(sel.sum()),
                   "area_pct": 100 * w.sum() / area.sum(),
                   "lat_media": float(np.average(M["lat"].to_numpy()[sel], weights=w)),
                   "lat_abs_media": float(np.average(np.abs(M["lat"].to_numpy()[sel]), weights=w))}
            if "elevacao_m" in M:
                row["elevacao_media_m"] = float(np.average(M["elevacao_m"].to_numpy()[sel], weights=w))
            for v in used:
                row[v + "_media"] = float(np.average(M[v].to_numpy()[sel], weights=w))
            row["sitios"] = "; ".join(s for s in M["sitio"].to_numpy()[sel] if s)
            row["melhor_similaridade"] = float(sim_r[top[0]])
            row["locais_terra_mais_parecidos"] = "; ".join(
                f"{E['local'].iloc[t]} ({sim_r[t]:.3f})" for t in top)
            rows.append(row)
        regioes = pd.DataFrame(rows).sort_values("melhor_similaridade", ascending=False)
        regioes.to_csv(f"{args.prefixo}_regioes_marte.csv", index=False)
    except ImportError:
        print("\n[nota] scikit-learn nao instalado: pulei a divisao de Marte em regioes")
    R.to_csv(f"{args.prefixo}_marte.csv", index=False)

    # ---------- resumo na tela ----------
    pd.set_option("display.width", 220)
    cols = ["local", "tipo", "similaridade_base", "similaridade_completa", "marte_lat", "marte_lon_leste"]
    print(f"\nVariaveis na similaridade base: {base_vars}")
    print("\nTop 15 locais da Terra (melhor correspondencia com alguma celula de Marte):")
    print(T[cols].head(15).round(3).to_string(index=False))
    for nome in SITIOS:
        c = "sim_" + nome.split(" ")[0]
        if c in T:
            top = T.sort_values(c, ascending=False).head(5)
            print(f"\nMais parecidos com {nome}: " +
                  "; ".join(f"{a} ({b:.3f})" for a, b in zip(top["local"], top[c])))
    if regioes is not None:
        print("\nRegioes climaticas de Marte:")
        show = ["regiao", "area_pct", "lat_abs_media", "temp_ar_media", "pressao_media",
                "melhor_similaridade", "locais_terra_mais_parecidos"]
        print(regioes[[c for c in show if c in regioes]].round(2).to_string(index=False))

    # ---------- mapas ----------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(11, 5))
        sc = ax.scatter(R["lon_180"], R["lat"], c=R["similaridade_base"], s=9, marker="s", cmap="viridis")
        for nome in SITIOS:
            p = R[R["sitio"] == nome]
            if len(p):
                ax.plot(p["lon_180"], p["lat"], "r*", ms=12)
                ax.annotate(nome.split(" ")[0], (p["lon_180"].iloc[0], p["lat"].iloc[0]),
                            color="red", xytext=(5, 5), textcoords="offset points")
        fig.colorbar(sc, label="similaridade com o melhor local da Terra")
        ax.set(xlabel="longitude (graus leste)", ylabel="latitude", xlim=(-180, 180), ylim=(-90, 90),
               title="Marte: quao parecida cada celula e com o melhor local terrestre")
        fig.tight_layout(); fig.savefig(f"{args.prefixo}_mapa_marte.png", dpi=150); plt.close(fig)

        fig, ax = plt.subplots(figsize=(11, 5))
        lon_e = ((T["lon"] + 180) % 360) - 180
        sc = ax.scatter(lon_e, T["lat"], c=T["similaridade_base"], s=28, cmap="viridis")
        for _, r in T.head(10).iterrows():
            ax.annotate(r["local"], (((r["lon"] + 180) % 360) - 180, r["lat"]), fontsize=7,
                        xytext=(3, 3), textcoords="offset points")
        fig.colorbar(sc, label="similaridade com a melhor celula de Marte")
        ax.set(xlabel="longitude", ylabel="latitude", xlim=(-180, 180), ylim=(-90, 90),
               title="Terra: quao parecido cada local e com Marte")
        fig.tight_layout(); fig.savefig(f"{args.prefixo}_mapa_terra.png", dpi=150); plt.close(fig)

        if "regiao" in R:
            fig, ax = plt.subplots(figsize=(11, 5))
            sc = ax.scatter(R["lon_180"], R["lat"], c=R["regiao"], s=9, marker="s", cmap="tab10")
            ax.legend(*sc.legend_elements(), title="regiao", loc="lower left", ncol=args.k, fontsize=7)
            ax.set(xlabel="longitude (graus leste)", ylabel="latitude", xlim=(-180, 180), ylim=(-90, 90),
                   title="Marte: regioes climaticas (k-means)")
            fig.tight_layout(); fig.savefig(f"{args.prefixo}_regioes_marte.png", dpi=150); plt.close(fig)
        print(f"\nMapas: {args.prefixo}_mapa_marte.png, {args.prefixo}_mapa_terra.png"
              + (f", {args.prefixo}_regioes_marte.png" if "regiao" in R else ""))
    except ImportError:
        print("\n[nota] matplotlib nao instalado: mapas nao gerados")
    print(f"Tabelas: {args.prefixo}_terra.csv, {args.prefixo}_marte.csv"
          + (f", {args.prefixo}_regioes_marte.csv" if regioes is not None else ""))


if __name__ == "__main__":
    main()