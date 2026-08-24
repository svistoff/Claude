/* Виджет-вставка афиши ЕКБ ГИД для главной ekb-guide.ru
   Использование на странице:
     <div id="ekb-afisha-widget"></div>
     <script src="https://afisha.ekb-guide.ru/embed.js" defer></script>
   Можно задать свой контейнер: <script ... data-target="мой_id"></script>
*/
(function(){
  var SB='https://sb.ekb-guide.ru';
  var KEY='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhibWRwcW5zZXl3cGh3Z3hzbmxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MjE1NzYsImV4cCI6MjA5NTI5NzU3Nn0.wLuTKZ-uhCQ69iEm6gyJrsgaP0NgVL-PBad3kJD7uHU';
  var AFISHA='https://afisha.ekb-guide.ru';
  var LIMIT=10;
  var cs=document.currentScript;
  var mountId=(cs&&cs.getAttribute('data-target'))||'ekb-afisha-widget';

  var MONTHS=['','января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
  var WD=['','пн','вт','ср','чт','пт','сб','вс'];
  function esc(s){s=(s==null?'':''+s);return s.replace(/[&<>"']/g,function(m){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];});}
  function proxify(u){return (typeof u==='string')?u.replace('https://hbmdpqnseywphwgxsnlg.supabase.co',SB):u;}
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
    if(ev.schedule_type==='weekly'){var a=(ev.weekdays||[]).map(function(w){return WD[w];}).filter(Boolean).join(', ');return 'по '+a+(t?', '+t:'');}
    return dayStr(ev.starts_on)+(t?', '+t:'');
  }

  function injectOnce(){
    if(document.getElementById('ekbg-embed-css'))return;
    var l=document.createElement('link');l.rel='stylesheet';
    l.href='https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800&family=Onest:wght@400;600;700&display=swap';
    document.head.appendChild(l);
    var s=document.createElement('style');s.id='ekbg-embed-css';
    s.textContent=[
      '.ekbg-afisha{font-family:Onest,system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:#16151A;max-width:100%;box-sizing:border-box;}',
      '.ekbg-afisha *{box-sizing:border-box;}',
      '.ekbg-head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 0 14px;}',
      '.ekbg-head h3{font-family:Montserrat,sans-serif;font-weight:800;font-size:clamp(20px,4vw,26px);margin:0;letter-spacing:-.01em;}',
      '.ekbg-all{color:#E5133C;font-weight:700;text-decoration:none;font-size:15px;white-space:nowrap;}',
      '.ekbg-all:hover{color:#B00E30;}',
      '.ekbg-row{display:flex;gap:14px;overflow-x:auto;padding:2px 2px 10px;scrollbar-width:none;-webkit-overflow-scrolling:touch;}',
      '.ekbg-row::-webkit-scrollbar{display:none;}',
      '.ekbg-card{flex:0 0 auto;width:200px;text-decoration:none;color:inherit;background:#fff;border:1px solid #E7E3DA;border-radius:14px;overflow:hidden;transition:transform .15s,box-shadow .15s;display:block;}',
      '.ekbg-card:hover{transform:translateY(-3px);box-shadow:0 12px 30px rgba(0,0,0,.12);}',
      '.ekbg-img{aspect-ratio:3/4;background:linear-gradient(135deg,#efe9dc,#e3dccf);}',
      '.ekbg-img img{width:100%;height:100%;object-fit:cover;display:block;}',
      '.ekbg-b{padding:10px 12px 12px;}',
      '.ekbg-when{color:#E5133C;font-weight:700;font-size:12px;}',
      '.ekbg-cat{color:#6B6A73;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.03em;}',
      '.ekbg-t{font-family:Montserrat,sans-serif;font-weight:700;font-size:14px;line-height:1.2;margin:4px 0 0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;}',
      '.ekbg-p{margin-top:6px;font-weight:700;font-size:13px;}',
      '@media(max-width:600px){.ekbg-card{width:158px;}}'
    ].join('');
    document.head.appendChild(s);
  }

  function render(events,cats){
    var el=document.getElementById(mountId);if(!el)return;
    var catName={};(cats||[]).forEach(function(c){catName[c.id]=c.name;});
    var cards=events.map(function(ev){
      // Приоритет превью: реальная афиша, иначе логотип заведения (для видео-анонсов без постера).
      var img=proxify(ev.cover_image_url)||proxify(ev.venues&&ev.venues.logo_url);
      var cn=catName[ev.category_id]||'';
      return '<a class="ekbg-card" href="'+AFISHA+'/afisha/'+esc(ev.slug)+'">'+
        '<div class="ekbg-img">'+(img?'<img src="'+esc(img)+'" loading="lazy" alt="'+esc(ev.title)+'" onerror="this.style.display=\'none\'">':'')+'</div>'+
        '<div class="ekbg-b">'+(cn?'<div class="ekbg-cat">'+esc(cn)+'</div>':'')+
        '<div class="ekbg-when">'+esc(fmt(ev))+'</div>'+
        '<div class="ekbg-t">'+esc(ev.title)+'</div>'+
        (ev.price?'<div class="ekbg-p">'+esc(ev.price)+'</div>':'')+'</div></a>';
    }).join('');
    el.innerHTML='<div class="ekbg-afisha"><div class="ekbg-head"><h3>Афиша Екатеринбурга</h3>'+
      '<a class="ekbg-all" href="'+AFISHA+'/">Смотреть все →</a></div><div class="ekbg-row">'+cards+'</div></div>';
  }

  function load(){
    injectOnce();
    var today=new Date().toISOString().slice(0,10);
    var evUrl=SB+'/rest/v1/events?status=eq.published&ends_on=gte.'+today+
      '&select=title,slug,starts_on,ends_on,start_time,schedule_type,weekdays,price,cover_image_url,category_id,venues(logo_url)&order=starts_on.asc&limit='+LIMIT;
    Promise.all([
      fetch(evUrl,{headers:{apikey:KEY}}).then(function(r){return r.json();}),
      fetch(SB+'/rest/v1/categories?select=id,name',{headers:{apikey:KEY}}).then(function(r){return r.json();})
    ]).then(function(res){
      var events=res[0],cats=res[1];
      var el=document.getElementById(mountId);
      if(Array.isArray(events)&&events.length) render(events,Array.isArray(cats)?cats:[]);
      else if(el) el.innerHTML='';
    }).catch(function(){});
  }

  if(document.readyState!=='loading') load();
  else document.addEventListener('DOMContentLoaded',load);
})();
