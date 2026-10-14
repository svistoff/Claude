/* Виджет «Новости одной строкой» для ekb-guide.ru (Tilda, блок T123 «HTML-код»)
   Использование на странице:
     <div id="ekb-news-widget"></div>
     <script src="https://news.ekb-guide.ru/news-embed.js?v=1" defer></script>
   Параметры (атрибуты <script>):
     data-target="мой_id"  — свой контейнер (по умолчанию ekb-news-widget)
     data-limit="8"        — сколько новостей показать (по умолчанию 6)
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
  var LIMIT=Math.min(Math.max(parseInt((cs&&cs.getAttribute('data-limit'))||'6',10)||6,1),30);
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
    l.href='https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800&family=Onest:wght@400;500;600;700&display=swap';
    document.head.appendChild(l);
  }

  var BASE=':host{all:initial;display:block;}'+
    '*{box-sizing:border-box;}'+
    '.w,.mod{font-family:Onest,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;color:#16151A;-webkit-font-smoothing:antialiased;line-height:1.4;text-align:left;}'+
    'a{color:inherit;}';

  var LIST_CSS=BASE+
    '.head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:6px 12px;margin:0 0 6px;}'+
    'h3{font-family:Montserrat,sans-serif;font-weight:800;font-size:clamp(20px,4vw,26px);line-height:1.1;margin:0;letter-spacing:-.01em;}'+
    'h3 span{color:#E5133C;}'+
    '.all{color:#E5133C;font-weight:700;text-decoration:none;font-size:15px;white-space:nowrap;}'+
    '.all:hover{color:#B00E30;}'+
    'ul{list-style:none;margin:8px 0 0;padding:0;}'+
    'li{border-top:1px solid #E7E3DA;}'+
    'li:last-child{border-bottom:1px solid #E7E3DA;}'+
    'li a{display:block;padding:13px 4px;text-decoration:none;border-radius:10px;transition:background .15s;}'+
    'li a:hover{background:rgba(0,0,0,.03);}'+
    'li a:focus-visible{outline:2px solid #E5133C;outline-offset:2px;}'+
    '.t{font-family:Montserrat,sans-serif;font-weight:700;font-size:16px;line-height:1.25;margin:0;}'+
    '.s{margin:4px 0 0;color:#2C2A26;font-size:14.5px;line-height:1.45;}'+
    '.d{margin-top:5px;color:#6B6A73;font-size:12px;}'+
    '.foot{margin-top:14px;}'+
    '.btn{display:inline-block;border:1.5px solid #E5133C;color:#E5133C;border-radius:999px;padding:10px 20px;font-weight:700;font-size:14px;text-decoration:none;transition:background .15s,color .15s;}'+
    '.btn:hover{background:#E5133C;color:#fff;}'+
    '@media(max-width:600px){.btn{display:block;text-align:center;}}';

  var MODAL_CSS=BASE+
    '.ov{position:fixed;inset:0;background:rgba(16,15,20,.6);display:flex;align-items:center;justify-content:center;padding:18px;}'+
    '.mod{width:min(760px,100%);max-height:92vh;overflow:auto;-webkit-overflow-scrolling:touch;overscroll-behavior:contain;background:#fff;border-radius:22px;box-shadow:0 18px 50px rgba(22,21,26,.25);font-size:16px;}'+
    '.mb{padding:20px 22px 26px;}'+
    '.mt{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;}'+
    'h2{font-family:Montserrat,sans-serif;font-weight:800;font-size:clamp(21px,3.6vw,30px);line-height:1.1;margin:0;letter-spacing:-.01em;}'+
    '.x{flex:0 0 auto;width:42px;height:42px;border-radius:50%;border:1px solid #E7E3DA;background:#fff;color:#16151A;cursor:pointer;font-size:18px;line-height:1;padding:0;margin:0;font-family:inherit;}'+
    '.x:hover{border-color:#16151A;}'+
    '.md{color:#6B6A73;font-size:13.5px;margin-top:8px;}'+
    '.msum{font-size:16.5px;line-height:1.45;color:#2C2A26;margin:12px 0 0;font-weight:500;}'+
    '.gal{margin:16px -22px 0;display:flex;gap:8px;overflow-x:auto;scroll-snap-type:x mandatory;scrollbar-width:none;padding:0 22px;}'+
    '.gal::-webkit-scrollbar{display:none;}'+
    '.gal>*{flex:0 0 auto;scroll-snap-align:center;max-width:100%;max-height:62vh;border-radius:14px;background:#F3F0E9;display:block;}'+
    '.gal.one>*{margin:0 auto;}'+
    '.gal img{width:auto;height:auto;object-fit:contain;}'+
    '.gal video{width:100%;background:#000;}'+
    '.gal.many>*{max-width:88%;}'+
    '.gal.many img{height:min(56vh,420px);width:auto;object-fit:cover;}'+
    '.gal.many video{height:min(56vh,420px);width:auto;}'+
    '.cnt{text-align:center;font-size:12.5px;color:#6B6A73;margin-top:8px;}'+
    '.body{margin-top:16px;font-size:16px;line-height:1.65;color:#2C2A26;}'+
    '.body p{margin:0 0 12px;white-space:pre-line;overflow-wrap:anywhere;}'+
    '.body a{color:#E5133C;}'+
    '.acts{display:flex;flex-wrap:wrap;gap:12px 18px;align-items:center;margin-top:18px;padding-top:16px;border-top:1px solid #E7E3DA;}'+
    '.share{border:1px solid #16151A;background:transparent;color:#16151A;border-radius:999px;padding:11px 20px;font:inherit;font-size:15px;font-weight:700;cursor:pointer;margin:0;}'+
    '.share:hover{background:#16151A;color:#fff;}'+
    '.site{color:#E5133C;font-weight:700;font-size:15px;text-decoration:none;}'+
    '.site:hover{color:#B00E30;}'+
    '@media(max-width:600px){.ov{align-items:flex-end;padding:0;}.mod{width:100%;max-height:94vh;border-radius:18px 18px 0 0;}.mb{padding:16px 16px calc(22px + env(safe-area-inset-bottom));}.gal{margin:14px -16px 0;padding:0 16px;}}';

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
    return '<div class="gal '+(m.length>1?'many':'one')+'">'+items+'</div>'+(m.length>1?'<div class="cnt">'+m.length+' · листайте →</div>':'');
  }
  function modalHtml(n){
    return '<div class="ov"><div class="mod" role="dialog" aria-modal="true" aria-label="'+esc(n.title)+'"><div class="mb">'+
      '<div class="mt"><h2>'+esc(n.title)+'</h2><button type="button" class="x" data-close aria-label="Закрыть">✕</button></div>'+
      '<div class="md">'+esc(dayLabel(n.published_at))+'</div>'+
      (n.summary?'<p class="msum">'+esc(n.summary)+'</p>':'')+
      galleryHtml(n)+
      (n.body?'<div class="body">'+paragraphs(n.body)+'</div>':'')+
      '<div class="acts"><button type="button" class="share" data-share>Поделиться</button>'+
      '<a class="site" href="'+esc(newsUrl(n))+'" target="_blank" rel="noopener">Открыть на сайте →</a></div>'+
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
        '<div class="d">'+esc(dayLabel(n.published_at))+'</div></a></li>';
    }).join('');
    shadow.innerHTML='<style>'+LIST_CSS+'</style><div class="w">'+
      '<div class="head"><h3>Новости <span>одной строкой</span></h3><a class="all" href="'+SITE+'/">Все новости →</a></div>'+
      '<ul>'+items+'</ul>'+
      '<div class="foot"><a class="btn" href="'+SITE+'/">Все новости</a></div></div>';
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
