<?php
// SEO-страница одной новости: /n/<slug> (rewrite в nginx → news.php?slug=...).
// Скрытая или несуществующая новость → 404.
require __DIR__ . '/sb-config.php';

$slug = isset($_GET['slug']) ? preg_replace('/[^A-Za-z0-9_-]/', '', trim($_GET['slug'])) : '';

function not_found($SITE, $code = 404) {
    http_response_code($code);
    header('Content-Type: text/html; charset=utf-8');
    $msg = $code === 404 ? 'Новость не найдена' : 'Не удалось загрузить новость';
    echo '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
    echo '<meta name="robots" content="noindex"><title>' . $msg . ' — ЕКБ ГИД</title></head>';
    echo '<body style="font-family:system-ui,sans-serif;max-width:600px;margin:60px auto;padding:0 16px;text-align:center;color:#191512;background:#F4F1E9">';
    echo '<h1>' . $msg . '</h1><p>' . ($code === 404 ? 'Возможно, её сняли с публикации.' : 'Попробуйте обновить страницу.') . '</p>';
    echo '<p><a href="' . h($SITE) . '/" style="color:#191512">← Все новости</a></p></body></html>';
    exit;
}

if ($slug === '') { header('Location: ' . $SITE . '/', true, 302); exit; }

$rows = sb_get('news?slug=eq.' . rawurlencode($slug)
    . '&select=slug,title,summary,body,published_at,news_media(position,kind,token,width,height)'
    . '&news_media.order=position.asc&limit=1');
if ($rows === null) not_found($SITE, 503);
if (empty($rows)) not_found($SITE);
$n = $rows[0];

$canonical = $SITE . '/n/' . $n['slug'];
$media = isset($n['news_media']) && is_array($n['news_media']) ? $n['news_media'] : array();
$firstPhoto = null;
foreach ($media as $m) { if ($m['kind'] === 'photo') { $firstPhoto = $m; break; } }
$ogImage = $firstPhoto ? $MEDIA . rawurlencode($firstPhoto['token']) : null;

$descRaw = $n['summary'] ?: $n['body'] ?: $n['title'];
$desc = mb_substr(trim(preg_replace('/\s+/u', ' ', $descRaw)), 0, 200, 'UTF-8');

$ld = array(
    '@context' => 'https://schema.org',
    '@type' => 'NewsArticle',
    'headline' => mb_substr($n['title'], 0, 110, 'UTF-8'),
    'datePublished' => iso_ekb($n['published_at']),
    'mainEntityOfPage' => $canonical,
    'url' => $canonical,
    'inLanguage' => 'ru',
    'publisher' => array('@type' => 'Organization', 'name' => 'ЕКБ ГИД', 'url' => 'https://ekb-guide.ru/'),
);
if ($desc) $ld['description'] = $desc;
$images = array();
foreach ($media as $m) { if ($m['kind'] === 'photo') $images[] = $MEDIA . rawurlencode($m['token']); }
if ($images) $ld['image'] = $images;
$ldJson = json_encode($ld, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES | JSON_HEX_TAG);

header('Content-Type: text/html; charset=utf-8');
?><!doctype html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><?php echo h($n['title']); ?> — Новости Екатеринбурга | ЕКБ ГИД</title>
<meta name="description" content="<?php echo h($desc); ?>">
<link rel="canonical" href="<?php echo h($canonical); ?>">
<meta property="og:type" content="article">
<meta property="og:title" content="<?php echo h($n['title']); ?>">
<meta property="og:description" content="<?php echo h($desc); ?>">
<meta property="og:url" content="<?php echo h($canonical); ?>">
<meta property="og:site_name" content="Новости одной строкой — ЕКБ ГИД">
<meta property="article:published_time" content="<?php echo h(iso_ekb($n['published_at'])); ?>">
<?php if ($ogImage): ?><meta property="og:image" content="<?php echo h($ogImage); ?>">
<?php if (!empty($firstPhoto['width'])): ?><meta property="og:image:width" content="<?php echo (int)$firstPhoto['width']; ?>"><meta property="og:image:height" content="<?php echo (int)$firstPhoto['height']; ?>">
<?php endif; endif; ?>
<meta name="twitter:card" content="<?php echo $ogImage ? 'summary_large_image' : 'summary'; ?>">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@600&display=swap" rel="stylesheet">
<script type="application/ld+json"><?php echo $ldJson; ?></script>
<style>
  /* Дизайн-код ЕКБ ГИД: см. index.html */
  :root{--paper:#F4F1E9;--card:#FFFDF7;--ink:#191512;--muted:#6F6A60;--line:#E4DFCF;--hl:#F5E24B;--hl-soft:#FCF4B4;
    --disp:'Montserrat',-apple-system,'Segoe UI',sans-serif;--sans:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;--mono:'JetBrains Mono',ui-monospace,monospace;}
  *{box-sizing:border-box;} body{margin:0;font-family:var(--sans);font-size:16px;line-height:1.55;background:var(--paper);color:var(--ink);-webkit-font-smoothing:antialiased;}
  .wrap{max-width:760px;margin:0 auto;padding:22px 16px 72px;}
  .back,.eyebrow,.foot,.date{font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);}
  .back{display:inline-block;text-decoration:none;margin-bottom:26px;}
  .date{display:block;margin-top:12px;}
  .back:hover{color:var(--ink);}
  .eyebrow{display:block;width:max-content;max-width:100%;letter-spacing:.18em;border:1px solid var(--line);border-radius:999px;padding:6px 13px;margin-bottom:20px;background:var(--card);}
  h1{font-family:var(--disp);font-weight:700;font-size:clamp(26px,5.2vw,40px);line-height:1.1;letter-spacing:-.005em;margin:0;}
  .sum{font-size:clamp(17px,1.8vw,19px);line-height:1.5;font-weight:500;margin:16px 0 0;max-width:640px;}
  .media{margin-top:22px;display:flex;flex-direction:column;gap:12px;}
  .media img,.media video{display:block;max-width:100%;height:auto;max-height:80vh;margin:0 auto;border-radius:16px;background:var(--line);}
  .media video{width:100%;background:var(--ink);}
  .body{margin-top:22px;font-size:17px;line-height:1.7;max-width:640px;}
  .body p{margin:0 0 14px;white-space:pre-line;overflow-wrap:anywhere;}
  .body a{color:var(--ink);text-decoration-color:var(--hl);text-decoration-thickness:3px;text-underline-offset:2px;}
  .btn{display:inline-flex;align-items:center;gap:8px;font-family:var(--disp);font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;padding:13px 24px;border-radius:999px;border:1.5px solid var(--hl);background:var(--hl);color:var(--ink);text-decoration:none;margin-top:16px;transition:transform .16s ease,box-shadow .16s ease;}
  .btn:hover{transform:translateY(-2px);box-shadow:0 8px 18px rgba(245,226,75,.55);}
  .foot{margin-top:40px;padding-top:18px;border-top:1px solid var(--line);display:flex;flex-wrap:wrap;gap:8px 20px;}
  .foot a{color:var(--ink);text-decoration:none;}
  .foot a:hover{text-decoration:underline;}
  @media(max-width:600px){.btn{width:100%;justify-content:center;}}
  @media(prefers-reduced-motion:reduce){*{transition:none !important;}}
</style>
</head>
<body>
  <article class="wrap">
    <a class="back" href="<?php echo h($SITE); ?>/">← Все новости</a>
    <span class="eyebrow">Новости одной строкой</span>
    <h1><?php echo h($n['title']); ?></h1>
    <div class="date"><time datetime="<?php echo h(iso_ekb($n['published_at'])); ?>"><?php echo h(day_str($n['published_at'], $MONTHS)); ?></time></div>
    <?php if (!empty($n['summary'])): ?><p class="sum"><?php echo h($n['summary']); ?></p><?php endif; ?>
    <?php if ($media): ?><div class="media">
      <?php foreach ($media as $m): $src = $MEDIA . rawurlencode($m['token']);
        $dims = (!empty($m['width']) && !empty($m['height'])) ? ' width="' . (int)$m['width'] . '" height="' . (int)$m['height'] . '"' : ''; ?>
        <?php if ($m['kind'] === 'video'): ?><video src="<?php echo h($src); ?>" controls playsinline preload="metadata"<?php echo $dims; ?>></video>
        <?php else: ?><img src="<?php echo h($src); ?>" alt="<?php echo h($n['title']); ?>" loading="lazy"<?php echo $dims; ?>><?php endif; ?>
      <?php endforeach; ?>
    </div><?php endif; ?>
    <?php if (!empty($n['body'])): ?><div class="body"><?php echo paragraphs($n['body']); ?></div><?php endif; ?>
    <a class="btn" href="<?php echo h($SITE); ?>/">Все новости <span aria-hidden="true">→</span></a>
    <div class="foot">
      <a href="<?php echo h($SITE); ?>/">Новости одной строкой</a>
      <a href="https://afisha.ekb-guide.ru/">Афиша Екатеринбурга</a>
      <a href="https://ekb-guide.ru/">ЕКБ ГИД</a>
    </div>
  </article>
</body>
</html>
