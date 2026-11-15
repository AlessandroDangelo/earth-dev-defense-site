/* Earth Dev Defense — análogos terrestres. Site estático: lê data/dados_site.json (pipeline) e data/equipe.json.
   Sem framework: estado simples + funções de renderização. Globo 3D: globe.gl (three.js).
   As funções de cálculo (mediana, entradas, rankingAtual) não mudam no redesign: só a apresentação. */
'use strict';

const GRUPOS = { terreno: 'Relevo', cobertura: 'Cobertura', temperatura: 'Temperatura', geologia: 'Geologia' };
const ICONE_GRUPO = { terreno: 'mountain', cobertura: 'layers', temperatura: 'thermometer', geologia: 'gem' };
const LITO = {
  vulcanica: 'vulcânica', cristalina: 'cristalina (intrusiva/metamórfica)', sedimentar: 'sedimentar',
  evaporitica: 'evaporítica', gelo: 'gelo', impacto_terras_altas: 'impacto / terras altas',
  misto_indefinido: 'mista / indefinida', nao_classificado: 'não classificada',
};
const MISSOES = [
  { id: 'geral', nome: 'Visão geral', grupo: null, icone: 'globe',
    desc: 'Os quatro grupos (relevo, cobertura, temperatura, geologia) com o mesmo peso. Bom ponto de partida para simular um habitat de longa duração.' },
  { id: 'terreno', nome: 'Pouso e mobilidade', grupo: 'terreno', icone: 'plane-landing',
    desc: 'Só o relevo (declividade, rugosidade e desnível): ensaios de pouso, testes de rovers e travessias de astronautas a pé.' },
  { id: 'temperatura', nome: 'Frio e equipamentos', grupo: 'temperatura', icone: 'thermometer-snowflake',
    desc: 'Só a temperatura da superfície: testes de resistência de equipamentos, baterias, trajes e operação no frio.' },
  { id: 'geologia', nome: 'Geologia de campo', grupo: 'geologia', icone: 'pickaxe',
    desc: 'Só o tipo de rocha: treinamento de astronautas em geologia, coleta de amostras e testes de instrumentos.' },
  { id: 'cobertura', nome: 'Superfície e poeira', grupo: 'cobertura', icone: 'wind',
    desc: 'Só a cobertura do solo (solo exposto, gelo, vegetação, construções): poeira, calibração de instrumentos e gelo como recurso.' },
];
const USOS = {
  terreno: 'ensaios de pouso, mobilidade de rovers e travessias a pé',
  temperatura: 'testes térmicos de equipamentos, baterias e trajes',
  geologia: 'treinamento em geologia de campo e coleta de amostras',
  cobertura: 'testes de poeira, abrasão e calibração de instrumentos',
};
const USO_CURTO = {
  terreno: ['plane-landing', 'Pouso e mobilidade'], temperatura: ['thermometer-snowflake', 'Testes térmicos'],
  geologia: ['pickaxe', 'Geologia de campo'], cobertura: ['wind', 'Poeira e instrumentos'],
};
// Texturas da Terra (NASA Blue Marble e topografia), servidas pelo próprio site (antes via CDN do three-globe).
const TEX = 'assets/img/terra_blue_marble.webp';
const TOPO = 'assets/img/terra_relevo.webp';
const COR = { terra: '#D42804', controle: '#6b7099', sel: '#EAFE07' };

const E = { dados: null, corpo: 'MOON', alvo: 'MOON', missao: 'geral', site: null, k: 5, controles: false, globo: null };
const $ = (s) => document.querySelector(s);
const fmt = (v, d = 1) => (v == null || Number.isNaN(v)) ? '—'
  : Number(v).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d });
const local = (id) => E.dados.locaisPorId[id];
const siteDoRecorte = (tile) => tile.replace(/_r\d+c\d+$/, '');
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ic = (nome, cls = '') => `<svg class="ic ${cls}" aria-hidden="true"><use href="assets/icones.svg#i-${nome}"/></svg>`;
const miniatura = (siteId) => `data/miniaturas/${siteId}.webp`;

/* ---------------------------------------------------------------- ranking */
function mediana(xs) {
  const s = xs.filter((x) => x != null).sort((a, b) => a - b);
  if (!s.length) return 0;
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function entradas() {
  const sim = E.dados.similaridade;
  return E.alvo === E.corpo ? sim.por_corpo[E.corpo] : sim.por_alvo[E.alvo];
}
/* Similaridade por grupo, na mesma escala do score: 100/(1 + d/mediana_do_grupo). */
function rankingAtual() {
  const lista = entradas();
  const med = {};
  for (const g of Object.keys(GRUPOS)) {
    let m = mediana(lista.map((e) => e.dist_grupos[g]));
    if (!(m > 0)) m = (lista.reduce((a, e) => a + (e.dist_grupos[g] || 0), 0) / lista.length) || 1;
    med[g] = m;
  }
  const missao = MISSOES.find((m) => m.id === E.missao);
  const linhas = lista.map((e) => {
    const sg = {};
    for (const g of Object.keys(GRUPOS)) sg[g] = 100 / (1 + (e.dist_grupos[g] || 0) / med[g]);
    const loc = local(e.site_id);
    return { ...e, sg, valor: missao.grupo ? sg[missao.grupo] : e.score, loc,
             controle: loc.tipo === 'controle', publicado: E.dados.publicados.has(`${e.site_id}|${E.corpo}`) };
  });
  // empates (comuns na geologia, que é discreta) desempatados pelo score geral
  linhas.sort((a, b) => (b.valor - a.valor) || (b.score - a.score));
  const visiveis = linhas.filter((l) => E.controles || !l.controle);
  visiveis.forEach((l, i) => { l.pos = i + 1; });
  return visiveis;
}
const linhasVisiveis = () => rankingAtual();

/* Empates só para exibição: linhas consecutivas com a mesma nota exibida (inteira). As notas e a ordem não mudam;
   dentro do grupo a ordem é a de sempre (nota com decimais e, em empate exato, a visão geral). */
function gruposEmpate(linhas) {
  const grupos = [];
  for (const l of linhas) {
    const g = grupos[grupos.length - 1];
    if (g && Math.round(g.valor) === Math.round(l.valor)) g.linhas.push(l);
    else grupos.push({ valor: l.valor, inicio: l.pos, linhas: [l] });
  }
  return grupos;
}

/* ---------------------------------------------------------------- abertura e desafio */
function renderNumeros() {
  const d = E.dados;
  const terra = d.locais.filter((l) => l.corpo === 'EARTH').length;
  const alvos = d.locais.length - terra;
  const itens = [[terra, 'lugares da Terra', 'map-pin'], [alvos, 'alvos na Lua e em Marte', 'crosshair'],
    [d.dados.recortes.length, 'quadrados de 9 km analisados', 'grid-3x3'],
    [d.dados.meta.features.length, 'características por quadrado', 'sliders-horizontal']];
  $('#numeros').innerHTML = itens.map(([n, r, i]) => `<div class="numero">${ic(i)}<b>${n}</b><span>${r}</span></div>`).join('');
}
function renderTrio() {
  const trio = [['earth_atacama_yungay', 'Terra', 'terra-cor'], ['moon_haworth', 'Lua', 'alvo-cor'], ['mars_jezero', 'Marte', 'alvo-cor']]
    .map(([id, corpo, cor]) => ({ l: local(id), corpo, cor })).filter((x) => x.l);
  $('#trio').innerHTML = trio.map(({ l, corpo, cor }) => `<figure class="trio-item">
      <img src="${miniatura(l.site_id)}" alt="Relevo sombreado de ${esc(l.nome)} (${corpo})" loading="lazy" width="240" height="240">
      <span class="corpo"><span class="ponto ${cor}"></span>${corpo}</span><span class="lugar">${esc(l.nome)}</span></figure>`).join('')
    + '<figcaption class="trio-legenda">Relevo real dos quadrados analisados, na mesma escala (dados NASADEM, LOLA e CTX).</figcaption>';
}

/* ---------------------------------------------------------------- escolhas */
function renderAlvos() {
  $('#alvos').innerHTML = '';
  const alvos = E.dados.locais.filter((l) => l.corpo === E.corpo);
  const nomeCorpo = E.corpo === 'MOON' ? 'Lua' : 'Marte';
  const itens = [{ id: E.corpo, nome: `Todos os alvos de ${nomeCorpo}`, info: `${alvos.length} alvos juntos`, todos: true },
    ...alvos.map((a) => ({ id: a.site_id, nome: a.nome,
      info: `${a.n_recortes} ${a.n_recortes === 1 ? 'recorte' : 'recortes'} · ${fmt(a.lat, 2)}°, ${fmt(a.lon, 2)}°` }))];
  for (const it of itens) {
    const b = document.createElement('button');
    b.className = 'alvo'; b.type = 'button'; b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(it.id === E.alvo));
    b.innerHTML = (it.todos
      ? `<span class="mosaico" aria-hidden="true">${alvos.slice(0, 4).map((a) => `<img src="${miniatura(a.site_id)}" alt="" loading="lazy" width="120" height="120">`).join('')}</span>`
      : `<img class="miniatura" src="${miniatura(it.id)}" alt="Relevo sombreado de ${esc(it.nome)}" loading="lazy" width="240" height="240">`)
      + `<span class="alvo-nome">${esc(it.nome)}</span><span class="alvo-info">${esc(it.info)}</span>`;
    b.addEventListener('click', () => { E.alvo = it.id; E.site = null; atualizar(); });
    $('#alvos').append(b);
  }
}
function renderMissoes() {
  $('#missoes').innerHTML = '';
  for (const m of MISSOES) {
    const b = document.createElement('button');
    b.className = 'missao'; b.type = 'button'; b.setAttribute('role', 'radio');
    b.setAttribute('aria-checked', String(m.id === E.missao));
    b.innerHTML = `${ic(m.icone)}<span>${esc(m.nome)}</span>`;
    b.addEventListener('click', () => { E.missao = m.id; atualizar(); });
    $('#missoes').append(b);
  }
  $('#missao-desc').innerHTML = `${ic('info')}<span>${esc(MISSOES.find((m) => m.id === E.missao).desc)}</span>`;
}
function nomeAlvoAtual() {
  return E.alvo === E.corpo ? (E.corpo === 'MOON' ? 'a Lua (todos os alvos)' : 'Marte (todos os alvos)') : local(E.alvo).nome;
}
function selos(l) {
  return (l.publicado ? ' <span class="selo selo-esa" title="No Catálogo de Análogos Planetários da ESA para este corpo">ESA</span>' : '')
    + (l.controle ? ' <span class="selo selo-controle" title="Local de controle (cidade ou floresta)">controle</span>' : '');
}
function selecionar(id) { E.site = id; renderRanking(); renderGlobo(true); renderDetalhe(true); renderClima(); }

/* ---------------------------------------------------------------- ranking */
function renderRanking() {
  const missao = MISSOES.find((m) => m.id === E.missao);
  $('#titulo-ranking').textContent = `Lugares da Terra mais parecidos com ${nomeAlvoAtual()}`
    + (missao.grupo ? ` — ${GRUPOS[missao.grupo].toLowerCase()}` : '');
  const ol = $('#ranking'); ol.innerHTML = '';
  for (const g of gruposEmpate(linhasVisiveis())) {
    const empate = g.linhas.length > 1;
    const lugar = g.inicio;                                   // posição exibida do grupo
    if (empate) {
      const li = document.createElement('li');
      li.className = 'grupo-empate'; li.setAttribute('aria-hidden', 'true');
      li.innerHTML = `<span><b>${g.linhas.length} empatados em ${lugar}º</b> · nota ${fmt(g.valor, 0)}</span><span>ordem interna: decimais da nota</span>`;
      ol.append(li);
    }
    for (const l of g.linhas) {
      const li = document.createElement('li');
      const b = document.createElement('button');
      const podio = lugar <= 3;
      b.type = 'button';
      b.className = 'linha' + (l.controle ? ' controle' : '') + (podio ? ` podio p${lugar}` : '') + (empate ? ' empatado' : '');
      if (l.site_id === E.site) b.setAttribute('aria-current', 'true');
      b.setAttribute('aria-label', `${empate ? `empatado em ${lugar}º` : `${l.pos}º`} ${l.loc.nome}, similaridade ${fmt(l.valor, 0)} de 100`);
      b.innerHTML = `<span class="pos">${empate ? '=' : l.pos}</span><span class="nome">${esc(l.loc.nome)}${selos(l)}</span>`
        + `<span class="valor">${fmt(l.valor, 0)}</span><span></span>`
        + `<span class="barra" aria-hidden="true"><span style="width:${Math.max(2, l.valor).toFixed(1)}%"></span></span>`;
      b.addEventListener('click', () => selecionar(l.site_id));
      li.append(b); ol.append(li);
    }
  }
}

/* ---------------------------------------------------------------- globo 3D */
const altitudeInicial = () => (window.innerWidth < 600 ? 3.1 : 2.75);
function criarGlobo() {
  const el = $('#globo');
  if (!window.Globe) {
    el.innerHTML = '<div class="globo-aviso">O globo 3D precisa de conexão com a internet e de WebGL. O ranking ao lado traz os mesmos dados.</div>';
    return null;
  }
  try {
    const g = Globe({ animateIn: true })(el)
      .globeImageUrl(TEX).bumpImageUrl(TOPO)
      .backgroundColor('rgba(0,0,0,0)').atmosphereColor('#9cc4f5').atmosphereAltitude(0.15)
      .width(el.clientWidth).height(el.clientHeight)
      .pointLat('lat').pointLng('lng').pointAltitude('alt').pointRadius('raio').pointColor('cor')
      .pointLabel('rotulo').pointsMerge(false).pointsTransitionDuration(500)
      .onPointClick((p) => selecionar(p.site_id))
      .ringLat('lat').ringLng('lng').ringColor(() => (t) => `rgba(234,254,7,${1 - t})`)
      .ringMaxRadius(6).ringPropagationSpeed(2.5).ringRepeatPeriod(1100);
    const reduzido = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    g.controls().autoRotate = !reduzido;
    g.controls().autoRotateSpeed = 0.35;
    g.controls().addEventListener('start', () => { g.controls().autoRotate = false; });
    g.pointOfView({ lat: 15, lng: -30, altitude: altitudeInicial() });
    new ResizeObserver(() => g.width(el.clientWidth).height(el.clientHeight)).observe(el);
    return g;
  } catch (e) {
    el.innerHTML = '<div class="globo-aviso">Não foi possível iniciar o globo 3D neste navegador (WebGL). O ranking ao lado traz os mesmos dados.</div>';
    return null;
  }
}
function renderGlobo(voar) {
  if (!E.globo) E.globo = criarGlobo();
  const linhas = linhasVisiveis();
  const vals = linhas.filter((l) => !l.controle).map((l) => l.valor);
  const min = Math.min(...vals), max = Math.max(...vals);
  const pontos = linhas.map((l) => {
    const sel = l.site_id === E.site;
    const rel = max > min ? (l.valor - min) / (max - min) : 1;
    return {
      site_id: l.site_id, lat: l.loc.lat, lng: l.loc.lon,
      alt: 0.015 + 0.26 * Math.max(0, rel), raio: sel ? 0.85 : 0.5,
      cor: sel ? COR.sel : (l.controle ? COR.controle : COR.terra),
      rotulo: `<div class="rotulo-globo"><strong>${esc(l.loc.nome)}</strong><br>${l.pos}º · similaridade ${fmt(l.valor, 0)}`
        + `${l.publicado ? ' · ESA' : ''}${l.controle ? ' · controle' : ''}</div>`,
    };
  });
  $('#legenda-globo').innerHTML = `<span>Altura da barra = similaridade (de ${fmt(min, 0)} a ${fmt(max, 0)} nesta visão)</span>`
    + `<span><span class="amostra" style="background:${COR.terra}"></span>lugar candidato</span>`
    + (E.controles ? `<span><span class="amostra" style="background:${COR.controle}"></span>controle</span>` : '')
    + `<span><span class="amostra" style="background:${COR.sel}"></span>selecionado</span>`
    + '<span>Arraste para girar · role para aproximar</span>';
  if (!E.globo) return;
  E.globo.pointsData(pontos);
  const sel = pontos.find((p) => p.site_id === E.site);
  E.globo.ringsData(sel ? [sel] : []);
  if (voar && sel) {
    E.globo.controls().autoRotate = false;
    E.globo.pointOfView({ lat: sel.lat, lng: sel.lng, altitude: 2.0 }, 1200);
  }
}

/* ---------------------------------------------------------------- comparação */
function valorAlvo(col) {
  if (E.alvo !== E.corpo) return local(E.alvo).media[col];
  const alvos = E.dados.locais.filter((l) => l.corpo === E.corpo);
  return alvos.reduce((a, l) => a + l.media[col], 0) / alvos.length;
}
function fmtUnid(v, u) {
  if (u === 'K') return `${fmt(v, 0)} K (${fmt(v - 273.15, 0)} °C)`;
  if (u === 'fração') return `${fmt(100 * v, 0)}%`;
  return `${fmt(v, v >= 100 ? 0 : 1)} ${u}`;
}
/* Halteres: alvo (círculo azul) × lugar da Terra (losango vermelho), agrupados por categoria, cada linha na própria escala. */
function halteres(site) {
  const feats = E.dados.dados.meta.features.filter((f) => f.grupo !== 'geologia');
  const W = 300, pad = 10;
  let html = '<div class="legenda" aria-hidden="true"><span><span class="ponto alvo-cor"></span>Alvo (Lua/Marte)</span>'
    + '<span><span class="ponto terra-cor"></span>Lugar da Terra</span>'
    + '<span>Cada linha tem a própria escala: do menor ao maior valor entre todos os locais.</span></div><div class="halteres">';
  let tabela = '<table><thead><tr><th>Característica</th><th class="num">Alvo</th><th class="num">Terra</th></tr></thead><tbody>';
  let grupoAtual = null;
  for (const f of feats) {
    if (f.grupo !== grupoAtual) {
      grupoAtual = f.grupo;
      html += `<p class="halteres-grupo">${ic(ICONE_GRUPO[f.grupo] || 'info')}${esc(GRUPOS[f.grupo] || f.grupo)}</p>`;
    }
    const vals = E.dados.locais.map((l) => l.media[f.coluna]);
    const min = Math.min(...vals), max = Math.max(...vals);
    // posição em % da trilha (mesma escala de antes: do menor ao maior valor entre todos os locais)
    const x = (v) => 100 * (pad + (W - 2 * pad) * (max > min ? (v - min) / (max - min) : 0.5)) / W;
    const va = valorAlvo(f.coluna), vt = site.media[f.coluna];
    const xa = x(va), xt = x(vt);
    const dica = `${f.nome}: alvo ${fmtUnid(va, f.unidade)}; ${site.nome} ${fmtUnid(vt, f.unidade)}`;
    html += `<div class="haltere"><span class="rot">${esc(f.nome)}</span>`
      + `<div class="trilha" role="img" aria-label="${esc(dica)}" data-dica="${esc(dica)}" tabindex="0">`
      + `<span class="trilha-ligacao" style="left:${Math.min(xa, xt).toFixed(2)}%;width:${Math.abs(xa - xt).toFixed(2)}%"></span>`
      + `<span class="marca-terra" style="left:${xt.toFixed(2)}%"></span><span class="marca-alvo" style="left:${xa.toFixed(2)}%"></span>`
      + '</div></div>';
    tabela += `<tr><td>${esc(f.nome)}</td><td class="num">${fmtUnid(va, f.unidade)}</td><td class="num">${fmtUnid(vt, f.unidade)}</td></tr>`;
  }
  tabela += '</tbody></table>';
  return html + `</div><details class="saiba"><summary>Ver tabela com os valores</summary><div class="tabela-wrap">${tabela}</div></details>`;
}
/* Leitura absoluta da distância de um grupo (a barra é relativa aos outros lugares da Terra). */
function absoluto(g, d) {
  if (g === 'geologia') {
    return d < 0.25 ? 'mesmo tipo de rocha' : d < 0.75 ? 'tipo de rocha do alvo indefinido' : 'tipo de rocha diferente';
  }
  const rot = d < 0.5 ? 'muito parecido' : d < 1 ? 'parecido' : d < 1.5 ? 'diferente' : 'muito diferente';
  return `${rot} (${fmt(d, 1)} desvio${d >= 1.95 ? 's' : ''}-padrão)`;
}
/* Rótulo curto (uma ou duas palavras) da mesma leitura absoluta, para os mini-cards. */
function rotuloCurto(g, d) {
  if (g === 'geologia') return d < 0.25 ? ['mesma rocha', 'bom'] : d < 0.75 ? ['indefinida', 'medio'] : ['rocha diferente', 'ruim'];
  return d < 0.5 ? ['muito parecido', 'bom'] : d < 1 ? ['parecido', 'bom'] : d < 1.5 ? ['diferente', 'medio'] : ['muito diferente', 'ruim'];
}
function renderDetalhe(rolar) {
  const linhas = linhasVisiveis();
  if (!linhas.length) { $('#detalhe').innerHTML = ''; return; }
  if (!E.site || !linhas.some((l) => l.site_id === E.site)) E.site = linhas[0].site_id;
  const l = linhas.find((x) => x.site_id === E.site);
  const site = l.loc;
  const alvoImg = local(siteDoRecorte(l.recorte_alvo));
  $('#titulo-detalhe').textContent = `${site.nome} × ${nomeAlvoAtual()}`;
  // um uso só é sugerido se o grupo é parecido em termos absolutos (< 1 desvio-padrão; geologia: mesma classe)
  const parecidos = Object.keys(GRUPOS).filter((g) => (g === 'geologia' ? l.dist_grupos[g] < 0.25 : l.dist_grupos[g] < 1));
  const geoAlvo = alvoImg.geologia ? LITO[alvoImg.geologia.classe_predominante] : '—';
  const geoTerra = site.geologia ? LITO[site.geologia.classe_predominante] : '—';
  $('#detalhe').innerHTML = `
    <div class="comparacao">
      <figure class="figura"><img src="data/${esc(alvoImg.imagem_relevo)}" alt="Relevo sombreado de ${esc(alvoImg.nome)}" width="480" height="480">
        <figcaption><span class="ponto alvo-cor"></span><strong>${esc(alvoImg.nome)}</strong> — janela de 27 km; quadrados amarelos = recortes analisados</figcaption></figure>
      <figure class="figura"><img src="data/${esc(site.imagem_relevo)}" alt="Relevo sombreado de ${esc(site.nome)}" width="480" height="480">
        <figcaption><span class="ponto terra-cor"></span><strong>${esc(site.nome)}</strong> (${fmt(site.lat, 2)}°, ${fmt(site.lon, 2)}°)${l.publicado ? ' · <span class="selo selo-esa">ESA</span>' : ''}</figcaption></figure>
      <div class="cartao placar">
        <div class="resumo-score"><span class="grande">${fmt(l.score, 0)}</span><span class="de">de 100</span>
          <span class="contexto">na visão geral · ${l.pos}º com o filtro atual</span></div>
        <div class="mini-grupos">${Object.keys(GRUPOS).map((g) => {
          const [rot, cls] = rotuloCurto(g, l.dist_grupos[g]);
          return `<div class="mini-grupo" title="${esc(GRUPOS[g])}: ${esc(absoluto(g, l.dist_grupos[g]))}">${ic(ICONE_GRUPO[g])}
            <span class="g-nome">${GRUPOS[g]}</span><span class="g-nota" aria-label="${GRUPOS[g]}: ${fmt(l.sg[g], 0)} de 100">${fmt(l.sg[g], 0)}</span>
            <span class="g-rot ${cls}">${rot}</span></div>`;
        }).join('')}</div>
        <p class="rotulo">Serve para</p>
        ${parecidos.length ? `<ul class="usos">${parecidos.map((g) => `<li class="uso" title="${esc(USOS[g])}">${ic(USO_CURTO[g][0])}${USO_CURTO[g][1]}</li>`).join('')}</ul>`
          : '<p class="nota" style="margin:0">Nenhum grupo realmente parecido: análogo fraco para este alvo.</p>'}
        ${site.tipo === 'controle' ? '<p class="nota" style="margin:0">Este é um <strong>local de controle</strong> (cidade ou floresta), incluído para checar o método.</p>' : ''}
        <details class="saiba"><summary>Ver detalhes</summary>
          <p>Similaridade por grupo (mesma escala; 50 = par típico). A nota compara com os outros lugares da Terra; o texto diz o quanto o lugar é parecido em termos absolutos:</p>
          <ul class="lista">${Object.keys(GRUPOS).map((g) => `<li><strong>${GRUPOS[g]} ${fmt(l.sg[g], 0)}:</strong> ${absoluto(g, l.dist_grupos[g])}</li>`).join('')}</ul>
          <p><strong>Geologia:</strong> alvo ${esc(geoAlvo)} · Terra ${esc(geoTerra)}${site.geologia ? `<br><span title="${esc(site.geologia.fonte)}">Unidade: ${esc(Object.keys(site.geologia.unidades)[0])}</span>` : ''}</p>
          ${parecidos.length ? `<p><strong>Serve para</strong> (grupos parecidos: menos de 1 desvio-padrão ou mesmo tipo de rocha):</p>
            <ul class="lista">${parecidos.map((g) => `<li><strong>${GRUPOS[g]}:</strong> ${USOS[g]}</li>`).join('')}</ul>` : ''}
          <p>Elevação: ${esc(site.fonte_dem)}. Quadrados mais parecidos: ${esc(l.recorte_alvo)} × ${esc(l.recorte_terra)}.</p>
        </details>
      </div>
    </div>
    <div class="cartao">${halteres(site)}</div>`;
  ligarDicas($('#detalhe'));
  if (rolar && window.innerWidth < 960) $('#detalhe-sec').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
function ligarDicas(raiz) {
  const tip = $('#tooltip');
  raiz.querySelectorAll('[data-dica]').forEach((el) => {
    const mostrar = (x, y) => { tip.textContent = el.dataset.dica; tip.hidden = false;
      tip.style.left = `${Math.min(x + 12, innerWidth - 270)}px`; tip.style.top = `${y + 12}px`; };
    el.addEventListener('mousemove', (ev) => mostrar(ev.clientX, ev.clientY));
    el.addEventListener('mouseleave', () => { tip.hidden = true; });
    el.addEventListener('focus', () => { const r = el.getBoundingClientRect(); mostrar(r.left, r.bottom); });
    el.addEventListener('blur', () => { tip.hidden = true; });
  });
}

/* ---------------------------------------------------------------- ZEUS */
function renderZeus() {
  $('#k').value = E.k; $('#k-valor').textContent = E.k;
  const chave = `k${E.k}`;
  const lista = linhasVisiveis().filter((l) => l.cocluster[chave] > 0).sort((a, b) => b.cocluster[chave] - a.cocluster[chave]);
  const q = E.dados.dados.meta.qualidade_k.find((x) => x.k === E.k);
  // agrupa pela fração dos quadrados do alvo (o texto repetido aparece uma vez, como legenda)
  const faixas = [];
  for (const l of lista) {
    const f = faixas[faixas.length - 1];
    if (f && Math.abs(f.v - l.cocluster[chave]) < 1e-9) f.linhas.push(l); else faixas.push({ v: l.cocluster[chave], linhas: [l] });
  }
  $('#zeus').innerHTML = lista.length
    ? '<p class="zeus-legenda">Percentual = parte dos quadrados do alvo que caem no mesmo grupo do lugar.</p>'
      + faixas.map((f) => `<div class="zeus-grupo"><div class="zeus-faixa"><b>${fmt(100 * f.v, 0)}%</b>
          <span class="barra" aria-hidden="true"><span style="width:${(100 * f.v).toFixed(1)}%"></span></span></div>
          <div class="zeus-chips">${f.linhas.map((l) => `<button type="button" class="chip${l.controle ? ' controle' : ''}" data-site="${l.site_id}"
            aria-label="${esc(l.loc.nome)}, ${fmt(100 * f.v, 0)}% dos quadrados do alvo${l.controle ? ', local de controle' : ''}">${l.controle ? ic('building-2') : ''}${esc(l.loc.nome)}${l.controle ? ' <small>controle</small>' : ''}</button>`).join('')}</div></div>`).join('')
    : '<p class="nota">Com este k, nenhum lugar da Terra cai no mesmo grupo do alvo: o ZEUS o considera único.</p>';
  $('#zeus-qualidade').textContent = q ? `Qualidade do agrupamento com k = ${E.k}: silhueta ${fmt(q.silhueta_embedding, 2)} (0 a 1, maior = grupos mais separados); k sugerido = ${E.dados.dados.meta.k_sugerido}.` : '';
  $('#zeus').querySelectorAll('.chip').forEach((c) => c.addEventListener('click', () => selecionar(c.dataset.site)));
}

/* ---------------------------------------------------------------- clima (Marte) */
function fmtClima(v, u) {
  if (u === 'K') return `${fmt(v, 0)} K`;
  if (u === 'Pa') return `${fmt(v, 0)} Pa`;
  if (u === 'mm/dia') return `${fmt(v, 2)} mm/dia`;
  return fmt(v, v < 0.1 ? 3 : 2);
}
function renderClima() {
  const el = $('#clima');
  const C = E.dados.dados.clima_marte;
  if (!C) { el.innerHTML = '<p class="nota">Camada de clima não calculada nesta versão dos dados.</p>'; return; }
  if (E.corpo !== 'MARS') {
    el.innerHTML = '<p class="nota">A comparação de clima existe só para Marte (a Lua não tem atmosfera). '
      + 'Escolha a aba <strong>Marte</strong> no passo 1 para vê-la.</p>';
    return;
  }
  const bloco = C.por_alvo[E.alvo];
  const linhas = linhasVisiveis().filter((l) => bloco.locais[l.site_id]);
  const porClima = [...linhas].sort((a, b) => bloco.locais[b.site_id].sim - bloco.locais[a.site_id].sim);
  const posClima = Object.fromEntries(porClima.map((l, i) => [l.site_id, i + 1]));
  const n = linhas.length;
  const sel = linhas.find((l) => l.site_id === E.site) || linhas[0];
  const c = bloco.locais[sel.site_id];
  const pc = posClima[sel.site_id];
  const terco = (p) => (p <= n / 3 ? 'alto' : p <= (2 * n) / 3 ? 'meio' : 'baixo');
  const frase = {
    'alto|alto': 'é parecido com o alvo <strong>no terreno e também no clima</strong>: bom candidato para testes completos.',
    'alto|meio': 'é parecido no terreno; no clima fica no meio da lista.',
    'alto|baixo': 'é parecido no <strong>terreno</strong>, mas está entre os <strong>menos parecidos no clima</strong>: serve para testes de relevo, rocha e mobilidade, não para testes climáticos.',
    'meio|alto': 'está entre os mais parecidos no <strong>clima</strong>, mas não no terreno: útil para testes de equipamentos no frio e na secura.',
    'baixo|alto': 'é um análogo <strong>climático</strong>, mas não de terreno: útil para testes de equipamentos no ambiente, não de relevo ou rocha.',
  }[`${terco(sel.pos)}|${terco(pc)}`] || 'fica no meio ou abaixo da lista nos dois critérios.';
  const val = bloco.validacao;
  const tabela = bloco.marte ? `<details class="saiba"><summary>Ver as ${C.grandezas.length} grandezas comparadas</summary><div class="tabela-wrap"><table>
      <thead><tr><th>Grandeza</th><th class="num">Marte (célula do modelo)</th><th class="num">${esc(sel.loc.nome)}</th><th class="num">Similaridade</th></tr></thead><tbody>
      ${C.grandezas.map((g) => `<tr><td>${esc(g.nome)}${g.peso < 1 ? ' <small>(peso ½)</small>' : ''}</td>`
        + `<td class="num">${fmtClima(bloco.marte[g.id], g.unidade)}</td><td class="num">${fmtClima(c.terra[g.id], g.unidade)}</td>`
        + `<td class="num">${fmt(c.grandezas[g.id], 0)}</td></tr>`).join('')}
      </tbody></table></div>
      <p class="nota">Célula do modelo de Marte usada: ${fmt(bloco.celula[0], 0)}°, ${fmt(bloco.celula[1], 0)}° L (2° × 2°, ~120 km).
        Pressão e chuva entram em escala logarítmica.</p></details>` : '';
  el.innerHTML = `
    <p class="intro-bloco">Quanto o clima de cada lugar da Terra se parece com o de Marte — independente do ranking acima.</p>
    <div class="clima-grade">
      <div class="cartao">
        <div class="resumo-score"><span class="grande">${fmt(c.sim, 0)}</span><span class="de">de 100 em clima</span>
          <span class="contexto">${esc(sel.loc.nome)}: ${pc}º de ${n} em clima · ${sel.pos}º de ${n} no ranking acima</span></div>
        <p style="margin:var(--e-3) 0 0;color:var(--tinta)"><strong>${esc(sel.loc.nome)}</strong> ${frase}</p>
        ${tabela}
      </div>
      <div class="cartao">
        <h4 class="rotulo" style="margin:0 0 var(--e-2);font-size:var(--t-s);color:var(--branco)">Mais parecidos em clima com ${esc(nomeAlvoAtual())}</h4>
        <ol class="mini-ranking">${porClima.slice(0, 6).map((l, i) => `<li><button type="button" data-site="${l.site_id}"
            aria-label="${i + 1}º em clima: ${esc(l.loc.nome)}, ${fmt(bloco.locais[l.site_id].sim, 0)} de 100">
            <span class="pos">${i + 1}</span><span class="nome">${esc(l.loc.nome)}</span><span class="valor">${fmt(bloco.locais[l.site_id].sim, 0)}</span>
            <span></span><span class="barra" aria-hidden="true"><span style="width:${bloco.locais[l.site_id].sim.toFixed(1)}%"></span></span></button></li>`).join('')}</ol>
        <details class="saiba"><summary>Saiba mais e limitações</summary>
          <p>Trabalho de <strong>Luís Gustavo de Oliveira Miranda</strong>, da equipe: compara nove grandezas de clima
            (temperatura do ar e da superfície, variação ao longo do ano e entre dia e noite, pressão, chuva e poeira) de cada lugar
            da Terra com o modelo climático de Marte da NASA Ames. É independente do ranking acima, que mede terreno, cobertura,
            temperatura da superfície e geologia${val ? ` (correlação entre os dois: ${fmt(val.spearman_com_score_v1_7, 2)}, ou seja, quase nenhuma)` : ''}.</p>
          <p>Escala: 100 = igual em todas as grandezas; 0 = tão diferente quanto os extremos de Terra e Marte juntos.
            ${val ? `Separa análogos de cidades e floresta com AUC ${fmt(val.auc_analogo_x_controle, 2)}.` : ''}</p>
          <ul class="lista">${C.avisos.map((a) => `<li>${esc(a)}</li>`).join('')}</ul>
        </details>
      </div>
    </div>`;
  el.querySelectorAll('.mini-ranking button').forEach((b) => b.addEventListener('click', () => selecionar(b.dataset.site)));
}

/* ---------------------------------------------------------------- resultados em destaque */
function topGeral(corpo, n) {
  return E.dados.similaridade.por_corpo[corpo].filter((e) => local(e.site_id).tipo !== 'controle')
    .sort((a, b) => b.score - a.score).slice(0, n).map((e) => `${local(e.site_id).nome} (${fmt(e.score, 0)})`);
}
function renderResultados() {
  const m = topGeral('MARS', 3), l = topGeral('MOON', 3);
  $('#resultado-analise').innerHTML = `${ic('arrow-right')}<span><strong>Resultado principal:</strong> para <strong>Marte</strong>,
    lideram ${esc(m.slice(0, 2).join(', '))} e ${esc(m[2])}. Para a <strong>Lua</strong>, ninguém chega perto: os menos diferentes
    são ${esc(l.slice(0, 2).join(', '))} e ${esc(l[2])} — a Lua pede combinar análogos por tipo de missão.</span>`;
  const v = (t, c) => E.dados.dados.meta.validacao.find((x) => x.teste === t && x.corpo === c);
  const a = v('candidatos_vs_controles', 'MOON'), b = v('candidatos_vs_controles', 'MARS'), c = v('publicados_vs_demais', 'MOON');
  if (a && b && c) {
    $('#resultado-metodologia').innerHTML = `${ic('shield-check')}<span><strong>Resultado da validação:</strong> o método separa
      análogos de cidades e floresta (AUC ${fmt(a.auc, 2)} na Lua e ${fmt(b.auc, 2)} em Marte) e coloca os lugares do catálogo da ESA
      no topo para a Lua (AUC ${fmt(c.auc, 2)}).</span>`;
  }
}

/* ---------------------------------------------------------------- metodologia */
const NOMES_GRUPO_FONTE = { terra: 'Terra', lua: 'Lua', marte: 'Marte', ia_clima: 'IA e clima', imagens: 'Imagens e interface' };
const AVISOS_PRINCIPAIS = [6, 7, 1];   // viés de seleção, análogos de terreno (não mineralógicos), fontes de temperatura
function renderSobre() {
  const meta = E.dados.dados.meta;
  const v = (teste, corpo) => meta.validacao.find((x) => x.teste === teste && x.corpo === corpo);
  const tiles = [
    ['Lua', v('publicados_vs_demais', 'MOON'), 'lugares do catálogo da ESA acima dos demais'],
    ['Marte', v('publicados_vs_demais', 'MARS'), 'lugares do catálogo da ESA acima dos demais'],
    ['Lua', v('candidatos_vs_controles', 'MOON'), 'análogos acima de cidades e floresta'],
    ['Marte', v('candidatos_vs_controles', 'MARS'), 'análogos acima de cidades e floresta'],
  ].filter((t) => t[1]);
  $('#validacao').innerHTML = tiles.map(([c, x, r]) => `<div class="tile"><div class="corpo-t">${c}</div><div class="num">${fmt(x.auc, 2)}</div>`
    + `<div class="rot">${r} (AUC; p = ${fmt(x.p, 3)})</div></div>`).join('')
    + '<p class="nota" style="grid-column:1/-1;margin:0">Os lugares da Terra foram escolhidos pela equipe (viés de seleção).</p>';
  const principais = AVISOS_PRINCIPAIS.filter((i) => meta.avisos[i]);
  const resto = meta.avisos.filter((_, i) => !principais.includes(i));
  $('#avisos').innerHTML = principais.map((i) => `<li>${esc(meta.avisos[i])}</li>`).join('');
  $('#avisos-resto').innerHTML = resto.map((a) => `<li>${esc(a)}</li>`).join('');
  $('#avisos-mais').hidden = !resto.length;
  const grupos = {};
  for (const f of meta.fontes) (grupos[f.grupo || 'terra'] ||= []).push(f);
  $('#fontes').innerHTML = Object.keys(NOMES_GRUPO_FONTE).filter((g) => grupos[g]).map((g) => `<details class="saiba fonte-grupo" open>
      <summary>${NOMES_GRUPO_FONTE[g]} (${grupos[g].length})</summary><ul>${grupos[g].map((f) => `<li><a href="${esc(f.url)}" target="_blank" rel="noopener">${esc(f.nome)}</a> — ${esc(f.uso)}`
      + (f.credito ? `. ${esc(f.credito)}` : '') + (f.licenca ? ` (${esc(f.licenca)})` : '') + '</li>').join('')}</ul></details>`).join('');
  $('#protocolo').textContent = meta.protocolo;
}

/* ---------------------------------------------------------------- equipe */
function iniciais(nome) {
  const p = nome.replace(/[’']/g, '').split(/\s+/).filter((x) => x.length > 2 || /^[A-ZÀ-Ú]/.test(x));
  return (p[0][0] + p[p.length - 1][0]).toUpperCase();
}
/* Contato com ícone. Vazio ("", ainda não informado) ou null (a pessoa não tem) não aparece para o público. */
function contato(valor, tipo, nome) {
  if (!valor) return '';
  const href = tipo === 'email' ? `mailto:${valor}` : valor;
  const [icone, rot] = { email: ['mail', `E-mail de ${nome}: ${valor}`], lattes: ['graduation-cap', `Currículo Lattes de ${nome}`],
    linkedin: ['linkedin', `LinkedIn de ${nome}`] }[tipo];
  return `<li><a href="${esc(href)}" target="_blank" rel="noopener" aria-label="${esc(rot)}" title="${esc(rot)}">${ic(icone)}</a></li>`;
}
async function renderEquipe() {
  let eq;
  try { eq = await (await fetch('data/equipe.json')).json(); } catch (_) { return; }
  const fotos = eq.fotos || [];
  $('#equipe-conteudo').innerHTML = `
    <div class="equipe-topo">
      <div>
        <div class="equipe-marca">
          ${eq.logo ? `<img class="logo-equipe" src="${esc(eq.logo)}" alt="Logo da equipe Earth Dev Defense" loading="lazy" width="96" height="96">` : ''}
          <h3 class="nome-equipe">Earth <span>Dev</span> Defense</h3>
        </div>
        <p>${esc(eq.descricao)}</p>
        <p class="nota">Evento local: <strong>${esc(eq.evento_local)}</strong> ·
          <a href="${esc(eq.pagina_oficial)}" target="_blank" rel="noopener">página oficial da equipe</a></p>
      </div>
      <div class="fotos">${fotos.slice(0, 2).map((f) => `<img src="${esc(f.arquivo)}" alt="${esc(f.legenda)}" loading="lazy" width="800" height="600">`).join('')}</div>
    </div>
    <div class="integrantes">${eq.integrantes.map((p) => {
      const cs = contato(p.email, 'email', p.nome) + contato(p.lattes, 'lattes', p.nome) + contato(p.linkedin, 'linkedin', p.nome);
      return `<article class="pessoa">
        ${p.foto ? `<img class="avatar" src="${esc(p.foto)}" alt="Foto de ${esc(p.nome)}" loading="lazy" width="72" height="72">`
          : `<span class="iniciais" aria-hidden="true">${esc(iniciais(p.nome))}</span>`}
        <div><h3>${esc(p.nome)}</h3>
          ${p.funcao ? `<p class="funcao">${esc(p.funcao)}</p>` : ''}
          ${cs ? `<ul class="contatos">${cs}</ul>` : ''}</div>
      </article>`;
    }).join('')}
    </div>`;
}

/* ---------------------------------------------------------------- navegação */
function ligarNavegacao() {
  const btn = $('.menu-btn'), menu = $('#menu');
  const fechar = () => { menu.classList.remove('aberto'); btn.setAttribute('aria-expanded', 'false'); btn.setAttribute('aria-label', 'Abrir menu');
    btn.querySelector('use').setAttribute('href', 'assets/icones.svg#i-menu'); };
  btn.addEventListener('click', () => {
    const abrir = !menu.classList.contains('aberto');
    if (!abrir) return fechar();
    menu.classList.add('aberto'); btn.setAttribute('aria-expanded', 'true'); btn.setAttribute('aria-label', 'Fechar menu');
    btn.querySelector('use').setAttribute('href', 'assets/icones.svg#i-x');
  });
  menu.querySelectorAll('a').forEach((a) => a.addEventListener('click', fechar));
  document.addEventListener('keydown', (ev) => { if (ev.key === 'Escape') fechar(); });

  // seção atual no menu e passo atual da análise (a última seção cujo topo passou da linha de leitura)
  const secoes = ['inicio', 'desafio', 'analise', 'metodologia', 'equipe'].map((id) => document.getElementById(id));
  const passos = [...document.querySelectorAll('.passos-nav a')].map((a) => [a, document.querySelector(a.getAttribute('href'))]);
  let pedido = false;
  const marcar = () => {
    pedido = false;
    const linha = 140;
    let atual = secoes[0];
    for (const s of secoes) if (s.getBoundingClientRect().top <= linha) atual = s;
    menu.querySelectorAll('a').forEach((a) => a.setAttribute('aria-current', String(a.getAttribute('href') === `#${atual.id}`)));
    let passoAtual = null;
    for (const [a, alvo] of passos) if (alvo && alvo.getBoundingClientRect().top <= linha + 40) passoAtual = a;
    passos.forEach(([a]) => {
      a.classList.toggle('feito', passoAtual && passos.findIndex(([x]) => x === a) < passos.findIndex(([x]) => x === passoAtual));
      if (a === passoAtual) a.setAttribute('aria-current', 'step'); else a.removeAttribute('aria-current');
    });
  };
  addEventListener('scroll', () => { if (!pedido) { pedido = true; requestAnimationFrame(marcar); } }, { passive: true });
  marcar();
}

/* ---------------------------------------------------------------- início */
function atualizar() {
  document.querySelectorAll('.aba').forEach((a) => a.setAttribute('aria-selected', String(a.dataset.corpo === E.corpo)));
  renderAlvos(); renderMissoes(); renderRanking(); renderDetalhe(false); renderGlobo(false); renderZeus(); renderClima();
}
async function iniciar() {
  ligarNavegacao();
  renderEquipe();
  let dados;
  try {
    dados = await (await fetch('data/dados_site.json')).json();
  } catch (e) {
    $('#analise').insertAdjacentHTML('beforeend', '<p class="nota">Não foi possível carregar os dados. Abra o site por um servidor '
      + '(ex.: <code>python -m http.server</code> dentro da pasta <code>site/</code>).</p>');
    return;
  }
  E.dados = { dados, locais: dados.locais, locaisPorId: Object.fromEntries(dados.locais.map((l) => [l.site_id, l])),
              similaridade: dados.similaridade,
              publicados: new Set((dados.meta.analogos_publicados || []).map((p) => `${p.site_id}|${p.corpo}`)) };
  E.k = dados.meta.k_sugerido;
  document.querySelectorAll('.aba').forEach((a) => a.addEventListener('click', () => {
    E.corpo = a.dataset.corpo; E.alvo = E.corpo; E.site = null; atualizar();
  }));
  $('#mostrar-controles').addEventListener('change', (ev) => { E.controles = ev.target.checked; atualizar(); });
  $('#k').addEventListener('input', (ev) => { E.k = Number(ev.target.value); renderZeus(); });
  renderNumeros(); renderTrio(); renderSobre(); renderResultados(); atualizar();
}
iniciar();
