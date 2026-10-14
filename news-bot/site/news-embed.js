/* Виджет «Новости одной строкой» для ekb-guide.ru (Tilda, блок T123 «HTML-код»)
   Использование на странице:
     <div id="ekb-news-widget"></div>
     <script src="https://news.ekb-guide.ru/news-embed.js?v=1" defer></script>
   Параметры (атрибуты <script>):
     data-target="мой_id"  — свой контейнер (по умолчанию ekb-news-widget)
     data-limit="8"        — сколько новостей показать (по умолчанию 5)
   Виджет и всплывающее окно рендерятся в Shadow DOM — стили Tilda их не ломают и наоборот.
   При ошибке или пустой ленте виджет молча не показывается.
*/
(function(){
  var SB='https://sb.ekb-guide.ru';
  var KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhibWRwcW5zZXl3cGh3Z3hzbmxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MjE1NzYsImV4cCI6MjA5NTI5NzU3Nn0.wLuTKZ-uhCQ69iEm6gyJrsgaP0NgVL-PBad3kJD7uHU';
  var MEDIA='https://video.ekb-guide.ru/m/';
  var SITE='https://news.ekb-guide.ru';
  var cs=document.currentScript;
  var mountId=(cs&&cs.getAttribute('data-target'))||'ekb-news-widget';
  var LIMIT=Math.min(Math.max(parseInt((cs&&cs.getAttribute('data-limit'))||'5',10)||5,1),30);
  var MONTHS=['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  var ITEMS=[];

  function esc(s){s=(s==null?'':''+s);return s.replace(/[&<>"']/g,function(m){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];});}
  function linkify(e){return e.replace(/(https?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]])/g,function(u){return '<a href="'+u+'" target="_blank" rel="noopener">'+u+'</a>';});}
  function paragraphs(t){return String(t||'').trim().split(/\n\s*\n/).map(function(p){return '<p>'+linkify(esc(p.trim()))+'</p>';}).join('');}
  function ekbDay(d){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Yekaterinburg',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);}
  function dayLabel(iso){
    var key=ekbDay(new Date(iso)), now=new Date();
    if(key===ekbDay(now)) return 'сегодня';
    if(key===ekbDay(new Date(now.getTime()-864e5))) return 'вчера';
    var p=key.split('-'), s=parseInt(p[2],10)+' '+MONTHS[parseInt(p[1],10)-1];
    return p[0]!==ekbDay(now).slice(0,4)?s+' '+p[0]:s;
  }
  function newsUrl(n){return SITE+'/n/'+encodeURIComponent(n.slug);}
  function media(n){return (n.news_media||[]).slice().sort(function(a,b){return a.position-b.position;});}

  // Шрифты — один раз в <head> страницы (@font-face из Shadow DOM не подключается).
  function injectFonts(){
    if(document.getElementById('ekbn-fonts'))return;
    var l=document.createElement('link');l.id='ekbn-fonts';l.rel='stylesheet';
    l.href='https://fonts.googleapis.com/css2?family=Montserrat:wght@700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@600&display=swap';
    document.head.appendChild(l);
  }

  // Дизайн-код ЕКБ ГИД (как ekb-guide.ru/price): кремовая бумага, жёлтый маркер,
  // заголовки — Montserrat 700, текст — Inter, подписи — JetBrains Mono.
  var VARS=':host{all:initial;display:block;--paper:#F4F1E9;--card:#FFFDF7;--ink:#191512;--muted:#6F6A60;--line:#E4DFCF;--hl:#F5E24B;--hl-soft:#FCF4B4;'+
    '--disp:Montserrat,-apple-system,"Segoe UI",sans-serif;--sans:Inter,-apple-system,"Segoe UI",Roboto,sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace;}';
  var BASE=VARS+
    '*{box-sizing:border-box;}'+
    '.w,.mod{font-family:var(--sans);font-size:16px;color:var(--ink);-webkit-font-smoothing:antialiased;line-height:1.55;text-align:left;}'+
    'a{color:inherit;}'+
    '.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;font-family:var(--disp);font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;padding:13px 24px;border-radius:999px;cursor:pointer;border:1.5px solid var(--ink);color:var(--ink);background:transparent;text-decoration:none;margin:0;transition:transform .16s ease,box-shadow .16s ease,background .16s ease,color .16s ease;}'+
    '.btn:hover{transform:translateY(-2px);}'+
    '.btn-primary{background:var(--hl);border-color:var(--hl);}'+
    '.btn-primary:hover{box-shadow:0 8px 18px rgba(245,226,75,.55);}'+
    '.btn:focus-visible,a:focus-visible{outline:2px solid var(--ink);outline-offset:3px;}'+
    '.mono{font-family:var(--mono);font-size:10.5px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);}'+
    '@media(prefers-reduced-motion:reduce){*{transition:none !important;animation:none !important;}}';

  var LIST_CSS=BASE+
    // поля как в дизайн-коде: контент 1080px по центру, по бокам 22px (на телефоне 16px) —
    // блок T123 в Tilda растянут на всю ширину окна и своих отступов не даёт
    '.w{max-width:1080px;margin:0 auto;padding:0 22px;}'+
    '@media(max-width:640px){.w{padding:0 16px;}}'+
    '.head{margin:0 0 6px;}'+
    'h2{font-family:var(--disp);font-weight:700;text-transform:uppercase;font-size:clamp(24px,3.5vw,38px);line-height:1.03;letter-spacing:-.005em;margin:0;}'+
    '.hl{background-image:linear-gradient(var(--hl),var(--hl));background-repeat:no-repeat;background-position:0 82%;background-size:100% 64%;padding:.02em .16em;-webkit-box-decoration-break:clone;box-decoration-break:clone;}'+
    '.all{font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--ink);text-decoration:none;white-space:nowrap;border-bottom:2px solid var(--hl);padding-bottom:2px;}'+
    'ul{list-style:none;margin:18px 0 0;padding:0;}'+
    'li{border-top:1px solid var(--line);}'+
    'li:last-child{border-bottom:1px solid var(--line);}'+
    'li a{display:block;padding:16px 12px;margin:0 -12px;text-decoration:none;border-radius:16px;transition:background .16s ease;}'+
    'li a:hover{background:var(--card);}'+
    '.t{font-family:var(--disp);font-weight:700;font-size:17px;line-height:1.2;margin:0;letter-spacing:-.005em;}'+
    '.s{margin:5px 0 0;font-size:15px;line-height:1.5;opacity:.86;}'+
    '.d{margin-top:8px;}'+
    '.foot{margin-top:18px;}'+
    '.all:hover{background:var(--hl);}';

  var MODAL_CSS=BASE+
    '.ov{position:fixed;inset:0;background:rgba(25,21,18,.55);display:flex;align-items:center;justify-content:center;padding:18px;}'+
    '.mod{width:min(760px,100%);max-height:92vh;overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;background:var(--card);border-radius:24px;box-shadow:0 18px 50px rgba(25,21,18,.22);}'+
    '.mb{padding:24px 26px 28px;}'+
    '.mt{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;}'+
    'h2{font-family:var(--disp);font-weight:700;font-size:clamp(22px,3.6vw,30px);line-height:1.12;margin:0;letter-spacing:-.005em;}'+
    '.x{flex:0 0 auto;width:44px;height:44px;border-radius:50%;border:1.5px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer;font-size:17px;line-height:1;padding:0;margin:0;font-family:var(--sans);transition:border-color .16s ease;}'+
    '.x:hover{border-color:var(--ink);}'+
    '.md{margin-top:10px;}'+
    '.msum{font-size:17px;line-height:1.5;margin:14px 0 0;font-weight:500;}'+
    '.gal{margin:18px -26px 0;display:flex;gap:8px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;padding:0 26px;}'+
    '.gal::-webkit-scrollbar{display:none;}'+
    '.gal>*{flex:0 0 auto;scroll-snap-align:center;max-width:100%;max-height:62vh;border-radius:16px;background:var(--line);display:block;}'+
    '.gal.one>*{margin:0 auto;}'+
    '.gal img{width:auto;height:auto;object-fit:contain;}'+
    '.gal video{width:100%;background:var(--ink);}'+
    '.gal.many>*{max-width:88%;}'+
    '.gal.many img{height:min(56vh,420px);width:auto;object-fit:cover;}'+
    '.gal.many video{height:min(56vh,420px);width:auto;}'+
    '.cnt{text-align:center;margin-top:10px;}'+
    '.body{margin-top:18px;font-size:16px;line-height:1.65;}'+
    '.body p{margin:0 0 12px;white-space:pre-line;overflow-wrap:anywhere;}'+
    '.body a{color:var(--ink);text-decoration-color:var(--hl);text-decoration-thickness:3px;text-underline-offset:2px;}'+
    '.acts{display:flex;flex-wrap:wrap;gap:12px;align-items:center;margin-top:20px;padding-top:18px;border-top:1px solid var(--line);}'+
    '.acts .btn:not(.btn-primary):hover{background:var(--ink);color:var(--paper);}'+
    '@media(max-width:600px){.ov{align-items:flex-end;padding:0;}.mod{width:100%;max-height:94vh;border-radius:20px 20px 0 0;}.mb{padding:18px 16px calc(24px + env(safe-area-inset-bottom));}.gal{margin:16px -16px 0;padding:0 16px;}.acts .btn{width:100%;}}';

  // ---------- всплывающее окно ----------
  // Хост окна живёт прямо в <body>: у блоков Tilda бывают transform/overflow, которые ломают position:fixed.
  var host=null, root=null, current=null, pushed=false, savedOverflow='';
  function galleryHtml(n){
    var m=media(n); if(!m.length) return '';
    var items=m.map(function(x){
      var src=MEDIA+encodeURIComponent(x.token);
      var dims=(x.width&&x.height)?' width="'+(+x.width)+'" height="'+(+x.height)+'"':'';
      return x.kind==='video'
        ?'<video src="'+esc(src)+'" controls playsinline preload="metadata"'+dims+'></video>'
        :'<img src="'+esc(src)+'" loading="lazy" alt=""'+dims+'>';
    }).join('');
    return '<div class="gal '+(m.length>1?'many':'one')+'">'+items+'</div>'+(m.length>1?'<div class="cnt mono">'+m.length+' · листайте →</div>':'');
  }
  function modalHtml(n){
    return '<div class="ov"><div class="mod" role="dialog" aria-modal="true" aria-label="'+esc(n.title)+'"><div class="mb">'+
      '<div class="mt"><h2>'+esc(n.title)+'</h2><button type="button" class="x" data-close aria-label="Закрыть">✕</button></div>'+
      '<div class="md mono">'+esc(dayLabel(n.published_at))+'</div>'+
      (n.summary?'<p class="msum">'+esc(n.summary)+'</p>':'')+
      galleryHtml(n)+
      (n.body?'<div class="body">'+paragraphs(n.body)+'</div>':'')+
      '<div class="acts"><a class="btn btn-primary" href="'+esc(newsUrl(n))+'" target="_blank" rel="noopener">Открыть на сайте <span aria-hidden="true">→</span></a>'+
      '<button type="button" class="btn" data-share>Поделиться</button></div>'+
    '</div></div></div>';
  }
  function share(btn){
    var url=newsUrl(current);
    if(navigator.share){navigator.share({title:current.title,text:current.summary||'',url:url}).catch(function(){});return;}
    var done=function(){btn.textContent='Ссылка скопирована ✓';};
    if(navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done,function(){window.prompt('Скопируйте ссылку:',url);});
    else window.prompt('Скопируйте ссылку:',url);
  }
  function openModal(n){
    current=n;
    if(!host){
      host=document.createElement('div');
      host.setAttribute('style','position:fixed;inset:0;z-index:2147483000;display:block;margin:0;padding:0;border:0;');
      root=host.attachShadow({mode:'open'});
      root.addEventListener('click',function(e){
        var t=e.target;
        var sh=t.closest&&t.closest('[data-share]'); if(sh){share(sh);return;}
        if((t.classList&&t.classList.contains('ov'))||(t.closest&&t.closest('[data-close]'))) requestClose();
      });
      document.body.appendChild(host);
      savedOverflow=document.documentElement.style.overflow;
      document.documentElement.style.overflow='hidden';
    }
    root.innerHTML='<style>'+MODAL_CSS+'</style>'+modalHtml(n);
    var x=root.querySelector('.x'); if(x) x.focus({preventScroll:true});
    // Запись в истории без смены адреса: «Назад» на телефоне закрывает окно, а не уводит со страницы.
    if(!pushed){try{history.pushState({ekbnModal:1},'');pushed=true;}catch(_){}}
  }
  function closeUI(){
    if(!host)return;
    host.remove(); host=null; root=null; current=null;
    document.documentElement.style.overflow=savedOverflow||'';
  }
  function requestClose(){
    if(pushed){pushed=false;history.back();}   // popstate ниже закроет окно
    else closeUI();
  }
  window.addEventListener('popstate',function(){pushed=false;closeUI();});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'&&host)requestClose();});

  // ---------- виджет ----------
  function render(el,rows){
    var shadow=el.shadowRoot||el.attachShadow({mode:'open'});
    var items=rows.map(function(n,i){
      return '<li><a href="'+esc(newsUrl(n))+'" data-i="'+i+'">'+
        '<p class="t">'+esc(n.title)+'</p>'+
        (n.summary?'<p class="s">'+esc(n.summary)+'</p>':'')+
        '<div class="d mono">'+esc(dayLabel(n.published_at))+'</div></a></li>';
    }).join('');
    shadow.innerHTML='<style>'+LIST_CSS+'</style><div class="w">'+
      '<div class="head"><h2>Новости <span class="hl">одной строкой</span></h2></div>'+
      '<ul>'+items+'</ul>'+
      '<div class="foot"><a class="all" href="'+SITE+'/">Все новости →</a></div></div>';
    shadow.addEventListener('click',function(e){
      var a=e.target.closest&&e.target.closest('[data-i]'); if(!a)return;
      if(e.ctrlKey||e.metaKey||e.shiftKey||e.button===1)return;   // открыть в новой вкладке, как обычную ссылку
      var n=ITEMS[+a.getAttribute('data-i')]; if(!n)return;
      e.preventDefault(); openModal(n);
    });
  }

  function load(){
    var el=document.getElementById(mountId);
    if(!el||!el.attachShadow)return;
    injectFonts();
    var url=SB+'/rest/v1/news?select=slug,title,summary,body,published_at,news_media(position,kind,token,width,height)'+
      '&order=published_at.desc&news_media.order=position.asc&limit='+LIMIT;
    fetch(url,{headers:{apikey:KEY,Authorization:'Bearer '+KEY}})
      .then(function(r){if(!r.ok)throw 0;return r.json();})
      .then(function(rows){
        if(!Array.isArray(rows)||!rows.length)return;   // пусто — молча не показываем
        ITEMS=rows; render(el,rows);
      }).catch(function(){});
  }

  if(document.readyState!=='loading')load();
  else document.addEventListener('DOMContentLoaded',load);
})();
