/* JefroCrypto Research Dashboard — no secrets, no tokens in frontend. */
const $ = id => document.getElementById(id);
const view = () => $('view');
const qs = params => Object.entries(params).filter(([,v]) => v !== '' && v !== null && v !== undefined).map(([k,v]) => encodeURIComponent(k)+'='+encodeURIComponent(v)).join('&');

async function api(path, opts={}) {
  const r = await fetch(path, {credentials:'same-origin', headers:{'Content-Type':'application/json'}, ...opts});
  const d = await r.json().catch(() => ({detail:r.statusText}));
  if(!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : JSON.stringify(d.detail||d));
  return d;
}
function esc(s){return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function toast(msg){const t=$('toast');t.textContent=msg;t.className='toast';clearTimeout(toast._t);toast._t=setTimeout(()=>t.className='toast hidden',4000)}
function tag(text,cls=''){return `<span class="tag ${cls}">${esc(text)}</span>`}
function empty(msg){return `<div class="empty">${esc(msg)}</div>`}
function filters(){return {niche:$('f-niche').value,language:$('f-language').value,days:+$('f-days').value,mechanic:$('f-mechanic').value.trim(),exclude_own:$('f-external').checked}}

let currentTab='overview';
document.querySelectorAll('.tab').forEach(b=>b.onclick=()=>{document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));b.classList.add('active');currentTab=b.dataset.tab;renderTab()});
async function renderTab(){
  const f=filters();
  try{
    if(currentTab==='overview') return await renderOverview(f);
    if(currentTab==='posts') return await renderPosts(f);
    if(currentTab==='authors') return await renderAuthors();
    if(currentTab==='funnels') return await renderFunnels();
    if(currentTab==='products') return await renderProducts();
    if(currentTab==='insights') return await renderInsights();
    if(currentTab==='performance') return await renderPerformance();
    if(currentTab==='reports') return await renderReports();
    if(currentTab==='data') return await renderData();
  }catch(e){view().innerHTML=`<div class="panel">${empty('Ошибка: '+e.message)}</div>`}
}
async function loadAll(){await renderTab()}

/* ---------------- Overview ---------------- */
async function renderOverview(f){
  const o=await api('/api/research/overview');
  const c=o.counts;
  const stat=(label,val)=>`<div class="stat"><span>${label}</span><b>${val}</b></div>`;
  const dist=arr=>(arr||[]).slice(0,8).map(x=>`<div style="display:flex;justify-content:space-between;padding:3px 0;font-size:13px"><span>${esc(x.key)}</span><b>${x.count}</b></div>`).join('')||'<div class="muted">Нет данных</div>';
  const timeline=(o.posts_timeline||[]).map(p=>`<div style="display:flex;justify-content:space-between;font-size:12px;padding:2px 0"><span>${esc(p.date)}</span><span>${p.posts}</span></div>`).join('')||'<div class="muted">Нет данных</div>';
  view().innerHTML=`
  <div class="grid">${stat('Публикаций',c.posts)}${stat('Авторов',c.authors)}${stat('Продуктов',c.products)}${stat('Ссылок',c.links)}${stat('Воронок',c.funnels)}${stat('Инсайтов',c.insights)}${stat('Отчётов',c.reports)}</div>
  <div class="layout" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr))">
    <div class="panel"><h2>Запуск исследования</h2>
      <div class="row"><div><label>Тип</label><select id="r-kind"><option value="apify_search">Поиск чужих постов (Apify)</option><option value="apify_profiles">Посты выбранных авторов (Apify)</option><option value="search">Официальный поиск Meta</option><option value="all">Все источники (включая мои посты)</option><option value="monitor">Мониторинг авторов</option><option value="content_library">Content Library</option><option value="manual">Ручные данные</option></select></div>
      <div><label>Ниша</label><select id="r-niche"><option value="">Все</option><option>AI / SaaS</option><option>Crypto / Web3</option><option>Marketing / Sales</option><option>Business / Startups</option></select></div></div>
      <label>Ключевые слова (через запятую)</label><input id="r-keywords" value="мемкоины, memecoin, крипта, solana, трейдинг" placeholder="мемкоины, solana, трейдинг"/>
      <label>Аккаунты для Apify (через запятую, при выборе поиска по авторам)</label><input id="r-handles" placeholder="author1, author2"/>
      <label>Языки (через запятую)</label><input id="r-langs" value="ru, en" placeholder="ru, en"/>
      <div class="actions"><button onclick="startResearch()">Запустить в фоне</button><button class="secondary" onclick="runAI()">AI-анализ</button></div>
      <p class="notice"><b>Важно:</b> поиск чужих постов требует Meta App Review (Advanced Access) для <code>threads_keyword_search</code>. Без одобрения Meta вернёт только твои публикации, даже при HTTP 200; исправленная версия отмечает такой сбор как <code>skipped</code>. Для скрытия ранее собранных собственных постов заполни <code>THREADS_OWN_USERNAME</code> в .env. Статус — во вкладке Data &amp; Jobs. Можно вручную импортировать чужие посты из CSV/JSON.</p>
    </div>
    <div class="panel"><h2>Распределение по нишам</h2>${dist(o.niches)}<h3>Языки</h3>${dist(o.languages)}<h3>Форматы</h3>${dist(o.formats)}</div>
    <div class="panel"><h2>Динамика публикаций</h2>${timeline}<h3>Трафик и ссылки</h3><div class="muted" style="font-size:13px">Всего ссылок: ${o.traffic.total_links||0} · доменов: ${o.traffic.unique_domains||0} · с UTM: ${o.traffic.with_utm||0}</div></div>
  </div>`;
}
async function startResearch(){
  const kind=$('r-kind').value;
  const keywords=$('r-keywords').value.split(',').map(s=>s.trim()).filter(Boolean);
  const languages=$('r-langs').value.split(',').map(s=>s.trim()).filter(Boolean);
  const handles=$('r-handles').value.split(',').map(s=>s.trim()).filter(Boolean);
  try{const r=await api('/api/research/start',{method:'POST',body:JSON.stringify({kind,niche:$('r-niche').value||null,keywords,languages,handles,limit:20})});toast('Задача создана: '+r.task_id)}catch(e){toast('Ошибка: '+e.message)}
}
async function runAI(){
  try{const r=await api('/api/research/analyze',{method:'POST',body:JSON.stringify({limit:50})});toast('AI-анализ запущен: '+r.task_id)}catch(e){toast('Ошибка: '+e.message)}
}

/* ---------------- Trending Posts ---------------- */
async function renderPosts(f){
  const q=qs({limit:30,sort:'created_at',order:'desc',niche:f.niche,language:f.language,mechanic:f.mechanic,days:f.days,exclude_own:f.exclude_own});
  const data=await api('/api/research/posts?'+q);
  const cards=(data.items||[]).map(p=>{
    const m=p.metrics||{};const c=p.classification||{};
    return `<article class="card"><div class="cardhead"><div><div class="muted" style="font-size:12px">@${esc(p.author?.username||'unknown')} · ${esc(p.language||'und')} · ${esc((p.published_at||'').slice(0,10))}</div>
      <div>${(c.subcategories||[]).slice(0,4).map(x=>tag(x,'blue')).join('')}${(c.marketing_mechanics||[]).slice(0,3).map(x=>tag(x,'green')).join('')}</div></div>
      <div class="metrics"><span>👁 <b>${m.views??'—'}</b></span><span>ER <b>${m.engagement_rate??'—'}%</b></span><span>💬 <b>${m.replies??'—'}</b></span><span>🔁 <b>${m.reposts??'—'}</b></span></div></div>
      <div class="text">${esc(p.original_text)}</div>
      <div class="actions">${p.post_url?`<a href="${esc(p.post_url)}" target="_blank" rel="noopener">Permalink ↗</a>`:''}<button class="ghost" onclick="showPost(${p.id})">Детали / AI</button></div></article>`}).join('');
  view().innerHTML=`<div class="panel"><h2>Trending Posts <span class="muted" style="font-size:13px">(${data.total||0})</span></h2>
    <div class="row"><div><label>Сортировка</label><select id="p-sort" onchange="renderPosts(filters())"><option value="created_at">Дата</option><option value="published_at">Публикация</option></select></div>
    <div><label>Мин. просмотры</label><input id="p-min" type="number" placeholder="0"/></div></div>
    ${cards||empty('Пока нет чужих публикаций. Запусти поиск Apify или импортируй посты через Data & Jobs.')}</div>`;
}
async function showPost(id){
  const p=await api('/api/research/posts/'+id);
  const analyses=(p.analyses||[]).map(a=>`<h3>${esc(a.agent)} · уверенность ${a.confidence}</h3><pre style="white-space:pre-wrap;font-size:12px;color:var(--muted)">${esc(JSON.stringify(a.result,null,2))}</pre>`).join('')||'<div class="muted">AI ещё не анализировал пост.</div>';
  const links=(p.links||[]).map(l=>`<li><a href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.domain||l.url)}</a> ${l.has_referral?tag('referral','amber'):''}</li>`).join('');
  view().innerHTML=`<div class="panel"><h2>Публикация #${id}</h2><div class="text">${esc(p.original_text)}</div>
    <h3>История метрик</h3><pre style="white-space:pre-wrap;font-size:12px">${esc(JSON.stringify(p.metrics_history,null,2))}</pre>
    <h3>Ссылки</h3><ul>${links||'<li class="muted">нет</li>'}</ul><h3>AI-анализ</h3>${analyses}
    <div class="actions"><button class="secondary" onclick="analyzeOne(${id})">Переанализировать</button><button class="ghost" onclick="renderTab()">← Назад</button></div></div>`;
}
async function analyzeOne(id){try{await api('/api/research/analyze',{method:'POST',body:JSON.stringify({post_id:id,force:true})});toast('Анализ выполнен');await showPost(id)}catch(e){toast('Ошибка: '+e.message)}}

/* ---------------- Authors ---------------- */
async function renderAuthors(){
  const rows=await api('/api/research/authors/leaderboard?metric=median_views&limit=30');
  const body=(rows||[]).map(r=>`<tr><td>@${esc(r.username)}</td><td>${r.followers??'—'}</td><td>${esc(r.segment||'—')}</td><td>${r.median_views??'—'}</td><td>${r.median_er??'—'}</td><td>${r.posts_count}</td><td>${r.regularity_posts_per_week??'—'}</td><td>${r.cta_share??'—'}%</td></tr>`).join('');
  view().innerHTML=`<div class="panel"><h2>Исследуемые авторы</h2><div class="muted" style="font-size:13px;margin-bottom:12px">Медиана — основная метрика сравнения (устойчива к вирусным выбросам).</div>
  <table><thead><tr><th>Автор</th><th>Подписчики</th><th>Сегмент</th><th>Медиана просмотров</th><th>Медиана ER</th><th>Постов</th><th>Регулярность/нед</th><th>Доля CTA</th></tr></thead><tbody>${body||'<tr><td colspan="8" class="empty">Нет авторов</td></tr>'}</tbody></table></div>`;
}

/* ---------------- Funnels ---------------- */
async function renderFunnels(){
  const rows=await api('/api/research/funnels?limit=100');
  const cards=(rows||[]).map(f=>`<div class="card"><div class="cardhead"><div><b>${esc(f.funnel_type)}</b> ${tag(f.proof_level, f.proof_level>=6?'red':'green')} ${tag(f.verified_status)}</div>
    <span class="muted" style="font-size:12px">уверенность ${f.confidence}</span></div>
    <div>${(f.steps||[]).map(s=>`<div style="padding:4px 0;font-size:13px">${s.order+1}. ${esc(s.type)} — ${esc(s.description||'')} ${tag(s.proof_level)}</div>`).join('')}</div>
    ${f.destination_url?`<div class="muted" style="font-size:12px">→ ${esc(f.destination_url)}</div>`:''}</div>`).join('');
  view().innerHTML=`<div class="panel"><h2>Маркетинговые воронки</h2><div class="muted" style="font-size:12px;margin-bottom:12px">L1–L5 наблюдаемые · L6–L7 требуют аналитики автора. Система не выдаёт ссылку за доказанную продажу.</div>${cards||empty('Воронки не обнаружены')}</div>`;
}

/* ---------------- Products ---------------- */
async function renderProducts(){
  const rows=await api('/api/research/products?limit=100');
  const cards=(rows||[]).map(p=>`<div class="card"><div class="cardhead"><div><b>${esc(p.name)}</b><div class="muted" style="font-size:12px">${esc(p.domain||'')}</div></div>${p.pricing_model?tag(p.pricing_model,'amber'):''}</div>
    <div class="text" style="font-size:13px">${esc(p.description||'Нет описания')}</div>
    ${p.website?`<div style="margin-top:8px;font-size:13px"><a href="${esc(p.website)}" target="_blank" rel="noopener">Сайт ↗</a></div>`:''}</div>`).join('');
  view().innerHTML=`<div class="panel"><h2>Библиотека продуктов</h2>${cards||empty('Продукты не найдены')}</div>`;
}

/* ---------------- Insights / Briefs ---------------- */
async function renderInsights(){
  const [rows,briefs]=await Promise.all([api('/api/research/insights?limit=100'),api('/api/research/briefs')]);
  const briefRows=(briefs||[]).map(b=>`<tr><td>${b.id}</td><td>${esc(b.topic)}</td><td>${esc((b.language||'en').toUpperCase())}</td><td>${tag(b.status)}</td>
    <td><button class="secondary" onclick="generateFromBrief(${b.id})">Создать черновик</button></td></tr>`).join('');
  const cards=(rows||[]).map(i=>`<div class="card"><div class="cardhead"><div><b>${esc(i.title)}</b><div class="muted" style="font-size:12px">${esc(i.niche||'')} · выборка ${i.sample_size}</div></div>${tag('уверенность '+i.confidence,'green')}</div>
    <div class="text" style="font-size:13px">${esc(i.description)}</div>
    ${i.limitations?`<div class="muted" style="font-size:12px;margin-top:8px">Ограничения: ${esc(i.limitations)}</div>`:''}
    <div class="actions"><button class="secondary" onclick="makeBrief(${i.id},'${encodeURIComponent(i.title)}')">В Writer</button></div></div>`).join('');
  view().innerHTML=`<div class="panel"><h2>AI Insights</h2>${cards||empty('Инсайтов пока нет. Сохраняйте гипотезы через API или после анализа.')}
    <h3>Передать инсайт в Writer</h3><label>Тема</label><input id="b-topic" placeholder="Тема публикации"/>
    <div class="row"><div><label>Язык</label><select id="b-lang"><option value="en">English</option><option value="ru">Русский</option><option value="es">Español</option><option value="de">Deutsch</option></select></div>
    <div><label>CTA</label><input id="b-cta" placeholder="Try it for free"/></div></div>
    <div class="actions"><button onclick="createBrief()">Создать бриф</button></div>
    <h3>Брифы Writer</h3><table><thead><tr><th>#</th><th>Тема</th><th>Язык</th><th>Статус</th><th></th></tr></thead><tbody>${briefRows||'<tr><td colspan="5" class="empty">Брифов нет</td></tr>'}</tbody></table></div>`;
}
async function makeBrief(id,title){$('b-topic').value=decodeURIComponent(title);$('b-topic').dataset.insight=id;if($('f-language').value)$('b-lang').value=$('f-language').value;toast('Инсайт выбран')}
async function createBrief(){try{await api('/api/research/briefs',{method:'POST',body:JSON.stringify({insight_id:+$('b-topic').dataset.insight||null,topic:$('b-topic').value,language:$('b-lang').value,cta:$('b-cta').value||null})});toast('Бриф создан и передан в Writer');await renderInsights()}catch(e){toast('Ошибка: '+e.message)}}
async function generateFromBrief(id){try{const r=await api(`/api/research/briefs/${id}/generate`,{method:'POST'});toast(`Черновик #${r.id} (${r.language.toUpperCase()}) создан. Одобри его в Content Studio.`)}catch(e){toast('Ошибка: '+e.message)}}

/* ---------------- Performance ---------------- */
async function renderPerformance(){
  const [funnels,links]=await Promise.all([api('/api/research/funnels?limit=100'),api('/api/research/links?limit=100')]);
  const byType=Object.entries(funnels.reduce((a,f)=>(a[f.funnel_type]=(a[f.funnel_type]||0)+1,a),{}));
  const rows=byType.map(([k,v])=>`<tr><td>${esc(k)}</td><td>${v}</td></tr>`).join('');
  view().innerHTML=`<div class="panel"><h2>Метрики и сравнения</h2>
    <h3>Формулы</h3><div class="notice">ER = (Likes + Replies + Reposts + Quotes) / Views × 100 · RR = Replies / Views × 100 · ShareRate = (Reposts + Quotes) / Views × 100 · CTR = Clicks / Views × 100 · CR = Conversions / Clicks × 100. Метрики чужих аккаунтов, недоступные источнику, остаются пустыми — они не приравниваются к нулю.</div>
    <h3>Воронки по типам</h3><table><thead><tr><th>Тип</th><th>Количество</th></tr></thead><tbody>${rows||'<tr><td colspan="2" class="empty">Нет данных</td></tr>'}</tbody></table>
    <h3>Внешние ссылки (${links.length})</h3><table><thead><tr><th>Домен</th><th>Платформа</th><th>UTM</th><th>Реферал</th></tr></thead><tbody>${links.slice(0,30).map(l=>`<tr><td>${esc(l.domain||'')}</td><td>${esc(l.platform||'')}</td><td>${Object.keys(l.utm||{}).length?'да':'нет'}</td><td>${l.has_referral?'да':'нет'}</td></tr>`).join('')||'<tr><td colspan="4" class="empty">Нет ссылок</td></tr>'}</tbody></table></div>`;
}

/* ---------------- Reports ---------------- */
async function renderReports(){
  const rows=await api('/api/research/reports?limit=50');
  const body=(rows||[]).map(r=>`<tr><td>${r.id}</td><td>${esc(r.title)}</td><td>${esc(r.type)}</td><td>${esc((r.created_at||'').slice(0,16))}</td>
    <td><a href="#" onclick="openReport(${r.id});return false">Открыть</a> · <a href="/api/research/reports/${r.id}/export?format=markdown">MD</a> · <a href="/api/research/reports/${r.id}/export?format=pdf">PDF</a> · <a href="/api/research/reports/${r.id}/export?format=csv">CSV</a> · <a href="/api/research/reports/${r.id}/export?format=json">JSON</a></td></tr>`).join('');
  view().innerHTML=`<div class="panel"><h2>Отчёты исследований</h2>
    <div class="row"><div><label>Название</label><input id="rep-title" value="Threads Research Report"/></div><div><label>Период, дней</label><input id="rep-days" type="number" value="30"/></div></div>
    <div class="actions"><button onclick="createReport()">Сформировать отчёт</button></div>
    <h3>Список</h3><table><thead><tr><th>#</th><th>Название</th><th>Тип</th><th>Дата</th><th>Экспорт</th></tr></thead><tbody>${body||'<tr><td colspan="5" class="empty">Отчётов нет</td></tr>'}</tbody></table></div>`;
}
async function createReport(){try{await api('/api/research/reports',{method:'POST',body:JSON.stringify({title:$('rep-title').value,days:+$('rep-days').value})});toast('Отчёт сформирован');await renderReports()}catch(e){toast('Ошибка: '+e.message)}}
async function openReport(id){const r=await api('/api/research/reports/'+id);view().innerHTML=`<div class="panel"><h2>${esc(r.title)}</h2><pre style="white-space:pre-wrap;font-size:13px">${esc(r.content_md)}</pre><div class="actions"><button class="secondary" onclick="renderTab()">← Назад</button></div></div>`}

/* ---------------- Data & Jobs ---------------- */
async function renderData(){
  const [jobs,status,sources]=await Promise.all([api('/api/research/jobs?limit=30'),api('/api/research/status'),api('/api/research/sources')]);
  const sourceRows=(sources||[]).map(s=>`<tr><td>${s.id}</td><td>${esc(s.name)}</td><td>${esc(s.type)}</td>
    <td>${tag(s.enabled?'вкл':'выкл',s.enabled?'green':'')}</td>
    <td><input id="cfg-${s.id}" value="${esc(JSON.stringify(s.config||{}))}" style="font-size:12px"/></td>
    <td><button class="secondary" onclick="toggleSource(${s.id},${!s.enabled})">${s.enabled?'Выключить':'Включить'}</button>
        <button class="ghost" onclick="saveSourceCfg(${s.id})">Сохранить</button></td></tr>`).join('');
  const body=(jobs||[]).map(j=>`<tr><td>${j.id}</td><td>${esc(j.type)}</td><td>${tag(j.status,j.status==='success'?'green':(j.status==='skipped'?'amber':''))}</td><td>${j.found}</td><td>${j.new}</td><td>${j.duplicates}</td><td>${j.errors}</td><td>${esc(j.error_message||'')}</td></tr>`).join('');
  view().innerHTML=`<div class="panel"><h2>Ручное добавление публикации</h2>
    <label>Ссылка на пост / текст</label><textarea id="m-text" placeholder="Вставь текст или ссылку на Threads-публикацию"></textarea>
    <div class="row"><div><label>Автор</label><input id="m-author" placeholder="username"/></div><div><label>Ниша</label><input id="m-niche" placeholder="Crypto / Web3"/></div><div><label>Язык</label><input id="m-lang" placeholder="en"/></div><div><label>Продукт</label><input id="m-product" placeholder="Название продукта"/></div></div>
    <div class="row"><div><label>Просмотры</label><input id="m-views" type="number"/></div><div><label>Лайки</label><input id="m-likes" type="number"/></div><div><label>Ответы</label><input id="m-replies" type="number"/></div><div><label>Репосты</label><input id="m-reposts" type="number"/></div></div>
    <div class="actions"><button onclick="addManual()">Добавить</button></div>
    <h3>Импорт JSON / CSV</h3><input type="file" id="m-file" accept=".json,.csv"/>
    <div class="actions"><button class="secondary" onclick="uploadFile()">Импортировать</button></div>
    <h3>Добавить автора</h3><div class="row"><div><label>Username</label><input id="pr-user"/></div><div><label>Threads user ID (необязательно)</label><input id="pr-ext" placeholder="нужен только без profile_discovery"/></div><div><label>Подписчики</label><input id="pr-follow" type="number"/></div></div>
    <div class="actions"><button class="secondary" onclick="addProfile()">Добавить</button></div>
    <h3>Массовый импорт авторов</h3><input type="file" id="pr-file" accept=".json,.csv"/>
    <div class="actions"><button class="secondary" onclick="uploadProfiles()">Импортировать авторов</button></div>
  </div>
  <div class="panel"><h2>Источники данных</h2><div class="muted" style="font-size:12px;margin-bottom:10px">Отключённый источник не ломает остальные. Статус skipped — источник недоступен по уважительной причине (нет токена, endpoint или авторов), это не ошибка кода.</div>
    <table><thead><tr><th>#</th><th>Источник</th><th>Тип</th><th>Состояние</th><th>Конфиг JSON</th><th></th></tr></thead><tbody>${sourceRows||'<tr><td colspan="6" class="empty">Нет источников</td></tr>'}</tbody></table>
    <p class="notice">Официальный endpoint поиска Threads: <code>/keyword_search</code>. Нельзя включить публичный поиск одной настройкой URL: необходимо одобрение Meta App Review для <code>threads_keyword_search</code>, после которого следует получить новый OAuth-токен. Для наблюдения за чужими аккаунтами требуется отдельное разрешение <code>threads_profile_discovery</code>.</p>
  </div>
  <div class="panel"><h2>Журнал задач сбора</h2><table><thead><tr><th>#</th><th>Тип</th><th>Статус</th><th>Найдено</th><th>Новых</th><th>Дублей</th><th>Ошибок</th><th>Причина</th></tr></thead><tbody>${body||'<tr><td colspan="8" class="empty">Задач нет</td></tr>'}</tbody></table>
  <h3>Статус фоновых задач</h3><pre style="white-space:pre-wrap;font-size:12px">${esc(JSON.stringify(status,null,2))}</pre></div>`;
}
async function toggleSource(id,enabled){try{await api(`/api/research/sources/${id}`,{method:'PATCH',body:JSON.stringify({enabled})});toast('Источник обновлён');await renderData()}catch(e){toast('Ошибка: '+e.message)}}
async function saveSourceCfg(id){try{const cfg=JSON.parse($('cfg-'+id).value);await api(`/api/research/sources/${id}`,{method:'PATCH',body:JSON.stringify({config_json:cfg})});toast('Конфиг сохранён');await renderData()}catch(e){toast('Ошибка JSON: '+e.message)}}
async function addManual(){
  const payload={text:$('m-text').value,author:$('m-author').value||null,niche:$('m-niche').value||null,language:$('m-lang').value||null,product:$('m-product').value||null,
    views:+$('m-views').value||null,likes:+$('m-likes').value||null,replies:+$('m-replies').value||null,reposts:+$('m-reposts').value||null};
  try{await api('/api/research/posts/manual',{method:'POST',body:JSON.stringify(payload)});toast('Публикация добавлена');await renderData()}catch(e){toast('Ошибка: '+e.message)}
}
async function uploadFile(){
  const f=$('m-file').files[0];if(!f){toast('Выбери файл');return}
  const fd=new FormData();fd.append('file',f);
  try{const r=await fetch('/api/research/import',{method:'POST',credentials:'same-origin',body:fd});const d=await r.json();if(!r.ok)throw new Error(d.detail||'error');toast(`Импортировано: ${d.imported}, дублей: ${d.duplicates}`);await renderData()}catch(e){toast('Ошибка: '+e.message)}
}
async function uploadProfiles(){const f=$('pr-file').files[0];if(!f){toast('Выбери файл авторов');return}const fd=new FormData();fd.append('file',f);
  try{const r=await fetch('/api/research/profiles/import',{method:'POST',credentials:'same-origin',body:fd});const d=await r.json();if(!r.ok)throw new Error(d.detail||'error');toast(`Добавлено авторов: ${d.added}`);await renderData()}catch(e){toast('Ошибка: '+e.message)}}
async function addProfile(){
  try{await api('/api/research/profiles',{method:'POST',body:JSON.stringify({username:$('pr-user').value,external_profile_id:$('pr-ext').value||null,followers_count:+$('pr-follow').value||null})});toast('Автор добавлен');await renderData()}catch(e){toast('Ошибка: '+e.message)}
}

(async function init(){
  try{const h=await api('/api/health');$('health').textContent=`AI ${h.ai_configured?'on':'off'} · Threads ${h.threads_configured?'on':'off'}`}catch(e){$('health').textContent='нет связи'}
  await renderTab();
})();
