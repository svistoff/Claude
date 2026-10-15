/* Виджет-вставка афиши ЕКБ ГИД для главной ekb-guide.ru (Tilda, блок «Embed code» / T123)
   Использование на странице:
     <div id="ekb-afisha-widget"></div>
     <script src="https://afisha.ekb-guide.ru/embed.js" defer></script>
   Можно задать свой контейнер: <script ... data-target="мой_id"></script>
   и другой адрес страницы добавления анонса: <script ... data-submit-url="https://..."></script>
   Клик по карточке открывает анонс во всплывающем окне прямо на странице.
*/
(function(){
  var SB='https://sb.ekb-guide.ru';
  var KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhibWRwcW5zZXl3cGh3Z3hzbmxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MjE1NzYsImV4cCI6MjA5NTI5NzU3Nn0.wLuTKZ-uhCQ69iEm6gyJrsgaP0NgVL-PBad3kJD7uHU';
  var AFISHA='https://afisha.ekb-guide.ru';
  var LIMIT=10;
  var cs=document.currentScript;
  var mountId=(cs&&cs.getAttribute('data-target'))||'ekb-afisha-widget';
  var SUBMIT=(cs&&cs.getAttribute('data-submit-url'))||AFISHA+'/submit.html';

  var MONTHS=['','января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  var WD=['','пн','вт','ср','чт','пт','сб','вс'];
  var EVENTS=[], CATS={};
  function esc(s){s=(s==null?'':''+s);return s.replace(/[&<>"']/g,function(m){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];});}
  function safeUrl(u){return (typeof u==='string'&&/^https?:\/\//i.test(u))?u:'';}
  function proxify(u){u=safeUrl(u);return u?u.replace('https://hbmdpqnseywphwgxsnlg.supabase.co',SB):'';}
  function eventUrl(ev){return ev.slug?AFISHA+'/afisha/'+encodeURIComponent(ev.slug):AFISHA+'/';}
  function dayStr(d){if(!d)return '';var p=(''+d).split('-');return parseInt(p[2],10)+' '+MONTHS[parseInt(p[1],10)];}
  function hourWord(time){
    if(!time)return '';
    var h=parseInt((''+time).slice(0,2),10),m100=h%100,m10=h%10,word;
    if(m100>=11&&m100<=14)word='часов';else if(m10===1)word='час';else if(m10>=2&&m10<=4)word='часа';else word='часов';
    return h+' '+word;
  }
  function fmt(ev){
    var t=ev.start_time?hourWord(ev.start_time):'';
    if(ev.schedule_type==='range'&&ev.ends_on) return dayStr(ev.starts_on)+' – '+dayStr(ev.ends_on)+(t?', '+t:'');
    if(ev.schedule_type==='weekly'){var a=(ev.weekdays||[]).map(function(w){return WD[w];}).filter(Boolean).join(', ');return 'по '+a+(t?', '+t:'')+(ev.ends_on?' · до '+dayStr(ev.ends_on):'');}
    return dayStr(ev.starts_on)+(t?', '+t:'');
  }

  function injectOnce(){
    if(document.getElementById('ekbg-embed-css'))return;
    var l=document.createElement('link');l.rel='stylesheet';
    l.href='https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;600&display=swap';
    document.head.appendChild(l);
    var s=document.createElement('style');s.id='ekbg-embed-css';
    // Дизайн-код ЕКБ ГИД (как ekb-guide.ru/price). Цвета заданы прямо в правилах, а не CSS-переменными,
    // чтобы стили Tilda не могли их перебить.
    var INK='#191512',MUTED='#6F6A60',LINE='#E4DFCF',CARD='#FFFDF7',PAPER='#F4F1E9',HL='#F5E24B',HLS='#FCF4B4';
    var DISP="Montserrat,-apple-system,'Segoe UI',sans-serif",SANS="Inter,-apple-system,'Segoe UI',Roboto,sans-serif",MONO="'JetBrains Mono',ui-monospace,monospace";
    s.textContent=[
      '.ekbg-afisha{font-family:'+SANS+';color:'+INK+';max-width:100%;box-sizing:border-box;line-height:1.5;}',
      '.ekbg-afisha *{box-sizing:border-box;}',
      '.ekbg-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:baseline;gap:8px 16px;margin:0 0 18px;}',
      '.ekbg-head h3{font-family:'+DISP+';font-weight:700;text-transform:uppercase;font-size:clamp(24px,3.5vw,38px);line-height:1.03;letter-spacing:-.005em;margin:0;color:'+INK+';}',
      '.ekbg-hl{background-image:linear-gradient('+HL+','+HL+');background-repeat:no-repeat;background-position:0 82%;background-size:100% 64%;padding:.02em .16em;-webkit-box-decoration-break:clone;box-decoration-break:clone;}',
      '.ekbg-hlink{color:'+INK+';font-weight:600;font-size:15px;white-space:nowrap;text-decoration:underline;text-decoration-color:'+HL+';text-decoration-thickness:3px;text-underline-offset:3px;}',
      '.ekbg-hlink:hover{background:'+HLS+';}',
      '.ekbg-row{display:flex;gap:16px;overflow-x:auto;padding:2px 2px 12px;scrollbar-width:none;-webkit-overflow-scrolling:touch;}',
      '.ekbg-row::-webkit-scrollbar{display:none;}',
      '.ekbg-card{flex:0 0 auto;width:210px;text-decoration:none;color:inherit;background:'+CARD+';border:1px solid '+LINE+';border-radius:20px;overflow:hidden;transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;display:block;cursor:pointer;}',
      '.ekbg-card:hover{transform:translateY(-3px);border-color:'+INK+';box-shadow:0 10px 26px rgba(25,21,18,.09);}',
      '.ekbg-img{aspect-ratio:3/4;background:repeating-linear-gradient(135deg,rgba(25,21,18,.05) 0 8px,transparent 8px 16px),'+PAPER+';border-bottom:1px solid '+LINE+';}',
      '.ekbg-img img{width:100%;height:100%;object-fit:cover;display:block;}',
      '.ekbg-b{padding:12px 14px 14px;}',
      '.ekbg-cat{display:inline-block;font-family:'+MONO+';font-size:10px;font-weight:600;letter-spacing:.1em;text-transform:uppercase;background:'+HLS+';color:'+INK+';border-radius:6px;padding:3px 8px;margin-bottom:8px;}',
      '.ekbg-when{font-family:'+MONO+';font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:'+INK+';}',
      '.ekbg-t{font-family:'+DISP+';font-weight:700;font-size:15px;line-height:1.2;margin:6px 0 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}',
      '.ekbg-p{margin-top:8px;font-family:'+DISP+';font-weight:700;font-size:14px;}',
      '.ekbg-foot{margin-top:10px;}',
      '.ekbg-btn{display:inline-flex;align-items:center;gap:8px;font-family:'+DISP+';font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;padding:13px 24px;border-radius:999px;border:1.5px solid '+HL+';background:'+HL+';color:'+INK+' !important;text-decoration:none;transition:transform .16s ease,box-shadow .16s ease;}',
      '.ekbg-btn:hover{transform:translateY(-2px);box-shadow:0 8px 18px rgba(245,226,75,.55);}',
      /* на телефоне блок Tilda идёт от края до края — даём поля 16px; карточки при этом листаются во всю ширину */
      '@media(max-width:600px){.ekbg-card{width:164px;}.ekbg-b{padding:12px 12px 14px;}.ekbg-when{font-size:10px;letter-spacing:.02em;}.ekbg-btn{display:flex;justify-content:center;}'+
        '.ekbg-head,.ekbg-foot{padding:0 16px;}.ekbg-row{padding:2px 16px 12px;scroll-padding-left:16px;}}',

      /* Всплывающее окно. Живёт прямо в <body>, а не внутри блока Tilda: у блоков Tilda бывают
         transform/overflow, которые ломают position:fixed. Стили заданы явно, чтобы не зависеть от CSS Tilda. */
      '.ekbg-ov{position:fixed;inset:0;z-index:2147483000;background:rgba(25,21,18,.55);display:flex;align-items:center;justify-content:center;padding:18px;}',
      '.ekbg-ov,.ekbg-ov *{box-sizing:border-box;}',
      '.ekbg-mod{width:min(760px,100%);max-height:92vh;overflow:auto;-webkit-overflow-scrolling:touch;background:'+CARD+';border-radius:24px;box-shadow:0 10px 26px rgba(25,21,18,.09);font-family:'+SANS+';color:'+INK+';text-align:left;line-height:1.55;font-size:16px;}',
      '.ekbg-mb{padding:26px 28px 28px;}',
      '.ekbg-mt{display:flex;justify-content:space-between;align-items:flex-start;gap:14px;}',
      '.ekbg-mt h2{font-family:'+DISP+';font-weight:700;font-size:clamp(21px,3.2vw,30px);line-height:1.1;margin:0;padding:0;color:'+INK+';letter-spacing:-.005em;text-transform:none;}',
      '.ekbg-x{flex:0 0 auto;width:42px;height:42px;border-radius:50%;border:1.5px solid '+LINE+';background:'+CARD+';color:'+INK+';cursor:pointer;font-size:16px;line-height:1;padding:0;margin:0;}',
      '.ekbg-x:hover{border-color:'+INK+';}',
      '.ekbg-perf{color:'+MUTED+';font-size:15px;margin-top:6px;}',
      '.ekbg-poster{display:block;max-width:100%;max-height:60vh;width:auto;height:auto;margin:16px auto;border-radius:16px;}',
      '.ekbg-mod video{display:block;margin:16px auto;width:auto;max-width:100%;max-height:70vh;background:'+INK+';border-radius:16px;}',
      '.ekbg-meta{display:flex;flex-wrap:wrap;gap:8px 16px;color:'+MUTED+';margin:14px 0 4px;font-family:'+MONO+';font-size:12px;letter-spacing:.04em;text-transform:uppercase;}',
      '.ekbg-meta b{color:'+INK+';font-weight:600;}',
      '.ekbg-desc{line-height:1.6;color:'+INK+';white-space:pre-line;margin-top:16px;font-size:16px;}',
      '.ekbg-acts{display:flex;flex-wrap:wrap;align-items:center;gap:12px 18px;margin-top:22px;}',
      '.ekbg-ticket{display:inline-flex;align-items:center;gap:8px;background:'+HL+';border:1.5px solid '+HL+';color:'+INK+' !important;border-radius:999px;padding:13px 24px;font-family:'+DISP+';font-weight:700;font-size:14px;text-transform:uppercase;letter-spacing:.02em;text-decoration:none;transition:transform .16s ease,box-shadow .16s ease;}',
      '.ekbg-ticket:hover{transform:translateY(-2px);box-shadow:0 8px 18px rgba(245,226,75,.55);}',
      '.ekbg-share{border:1.5px solid '+INK+';background:transparent;color:'+INK+';border-radius:999px;padding:13px 24px;font-family:'+DISP+';font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;cursor:pointer;margin:0;transition:transform .16s ease,background .16s ease,color .16s ease;}',
      '.ekbg-share:hover{background:'+INK+';color:'+PAPER+';transform:translateY(-2px);}',
      '.ekbg-more{color:'+MUTED+';font-weight:600;font-size:14px;text-decoration:underline;text-underline-offset:3px;}',
      '.ekbg-more:hover{color:'+INK+';}',
      '@media(max-width:600px){.ekbg-ov{align-items:flex-end;padding:0;}.ekbg-mod{width:100%;border-radius:20px 20px 0 0;}.ekbg-mb{padding:20px 18px 26px;}'+
        '.ekbg-ticket,.ekbg-share{width:100%;justify-content:center;}}',
      '@media (prefers-reduced-motion:reduce){.ekbg-afisha *,.ekbg-ov *{transition:none!important;}}'
    ].join('');
    document.head.appendChild(s);
  }

  // ---------- всплывающее окно ----------
  var ov=null, pushed=false, savedOverflow=null, current=null;
  function shareEvent(btn){
    if(!current)return;
    var url=eventUrl(current);
    if(navigator.share){ navigator.share({title:current.title,url:url}).catch(function(){}); return; }
    var done=function(){ btn.textContent='Ссылка скопирована ✓'; };
    if(navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(url).then(done,function(){ window.prompt('Скопируйте ссылку на событие:',url); });
    else window.prompt('Скопируйте ссылку на событие:',url);
  }
  function modalHtml(ev){
    var v=ev.venues||{};
    var cover=proxify(ev.cover_image_url);   // в окне — только настоящая афиша, логотип заведения сюда не подставляем
    var video=proxify(ev.video_url);
    var ticket=safeUrl(ev.external_url);
    var cat=CATS[ev.category_id]||'';
    var addr=v.address?(v.address+(v.city?', '+v.city:'')):'';
    var text=ev.full_description||ev.short_description||'';
    return '<div class="ekbg-mod" role="dialog" aria-modal="true" aria-label="'+esc(ev.title)+'"><div class="ekbg-mb">'+
      '<div class="ekbg-mt"><h2>'+esc(ev.title)+'</h2><button type="button" class="ekbg-x" data-ekbg-close aria-label="Закрыть">✕</button></div>'+
      (ev.performer?'<div class="ekbg-perf">'+esc(ev.performer)+'</div>':'')+
      (cover?'<img class="ekbg-poster" src="'+esc(cover)+'" alt="'+esc(ev.title)+'" onerror="this.remove()">':'')+
      (video?'<video src="'+esc(video)+'" controls playsinline preload="metadata"></video>':'')+
      '<div class="ekbg-meta"><span><b>'+esc(fmt(ev))+'</b></span>'+
        (cat?'<span>'+esc(cat)+'</span>':'')+
        (v.name?'<span>'+esc(v.name)+'</span>':'')+
        (addr?'<span>'+esc(addr)+'</span>':'')+
        (ev.price?'<span><b>'+esc(ev.price)+'</b></span>':'')+
      '</div>'+
      (text?'<div class="ekbg-desc">'+esc(text)+'</div>':'')+
      '<div class="ekbg-acts">'+
        (ticket?'<a class="ekbg-ticket" href="'+esc(ticket)+'" target="_blank" rel="noopener">Билеты и подробности →</a>':'')+
        (ev.slug?'<button type="button" class="ekbg-share" data-ekbg-share>Поделиться</button>':'')+
        '<a class="ekbg-more" href="'+esc(eventUrl(ev))+'">Страница события на афише →</a>'+
      '</div>'+
    '</div></div>';
  }
  function openModal(ev){
    if(!ov){
      ov=document.createElement('div');ov.className='ekbg-ov';
      ov.addEventListener('click',function(e){
        var sh=e.target.closest&&e.target.closest('[data-ekbg-share]');
        if(sh){ shareEvent(sh); return; }
        if(e.target===ov||(e.target.closest&&e.target.closest('[data-ekbg-close]'))) requestClose();
      });
      document.body.appendChild(ov);
      savedOverflow=document.documentElement.style.overflow;
      document.documentElement.style.overflow='hidden';
    }
    ov.innerHTML=modalHtml(ev); current=ev;
    var m=ov.querySelector('.ekbg-mod'); if(m) m.scrollTop=0;
    // Запись в истории без смены адреса: кнопка «Назад» на телефоне закрывает окно, а не уводит со страницы.
    if(!pushed){ try{history.pushState({ekbgModal:1},'');pushed=true;}catch(_){} }
  }
  function closeUI(){
    if(!ov)return;
    ov.remove(); ov=null;
    document.documentElement.style.overflow=savedOverflow||'';
  }
  function requestClose(){
    if(pushed){ pushed=false; history.back(); }   // popstate ниже закроет окно
    else closeUI();
  }
  window.addEventListener('popstate',function(){ pushed=false; closeUI(); });
  document.addEventListener('keydown',function(e){ if(e.key==='Escape'&&ov) requestClose(); });

  // ---------- виджет ----------
  function render(events){
    var el=document.getElementById(mountId);if(!el)return;
    var cards=events.map(function(ev,i){
      // Приоритет превью: реальная афиша, иначе логотип заведения (для видео-анонсов без постера).
      var img=proxify(ev.cover_image_url)||proxify(ev.venues&&ev.venues.logo_url);
      var cn=CATS[ev.category_id]||'';
      return '<a class="ekbg-card" href="'+esc(eventUrl(ev))+'" data-ekbg-i="'+i+'">'+
        '<div class="ekbg-img">'+(img?'<img src="'+esc(img)+'" loading="lazy" alt="'+esc(ev.title)+'" onerror="this.style.display=\'none\'">':'')+'</div>'+
        '<div class="ekbg-b">'+(cn?'<div class="ekbg-cat">'+esc(cn)+'</div>':'')+
        '<div class="ekbg-when">'+esc(fmt(ev))+'</div>'+
        '<div class="ekbg-t">'+esc(ev.title)+'</div>'+
        (ev.price?'<div class="ekbg-p">'+esc(ev.price)+'</div>':'')+'</div></a>';
    }).join('');
    el.innerHTML='<div class="ekbg-afisha"><div class="ekbg-head"><h3>Афиша <span class="ekbg-hl">Екатеринбурга</span></h3>'+
      '<a class="ekbg-hlink" href="'+esc(SUBMIT)+'">Предложить анонс</a></div>'+
      '<div class="ekbg-row">'+cards+'</div>'+
      '<div class="ekbg-foot"><a class="ekbg-btn" href="'+AFISHA+'/">Смотреть все <span aria-hidden="true">→</span></a></div></div>';
    el.addEventListener('click',function(e){
      var a=e.target.closest&&e.target.closest('[data-ekbg-i]');
      if(!a)return;
      // Ctrl/Cmd/средняя кнопка — пусть откроется афиша в новой вкладке, как обычная ссылка.
      if(e.ctrlKey||e.metaKey||e.shiftKey||e.button===1)return;
      var ev=EVENTS[+a.getAttribute('data-ekbg-i')]; if(!ev)return;
      e.preventDefault();
      openModal(ev);
    });
  }

  function load(){
    injectOnce();
    var today=new Date().toISOString().slice(0,10);
    var evUrl=SB+'/rest/v1/events?status=eq.published&ends_on=gte.'+today+
      '&select=id,title,slug,performer,short_description,full_description,price,external_url,cover_image_url,video_url,'+
      'starts_on,ends_on,start_time,schedule_type,weekdays,category_id,venues(name,address,city,logo_url)'+
      '&order=starts_on.asc&limit='+LIMIT;
    Promise.all([
      fetch(evUrl,{headers:{apikey:KEY}}).then(function(r){return r.json();}),
      fetch(SB+'/rest/v1/categories?select=id,name',{headers:{apikey:KEY}}).then(function(r){return r.json();})
    ]).then(function(res){
      var events=res[0],cats=res[1];
      var el=document.getElementById(mountId);
      (Array.isArray(cats)?cats:[]).forEach(function(c){CATS[c.id]=c.name;});
      if(Array.isArray(events)&&events.length){ EVENTS=events; render(events); }
      else if(el) el.innerHTML='';
    }).catch(function(){});
  }

  if(document.readyState!=='loading') load();
  else document.addEventListener('DOMContentLoaded',load);
})();
