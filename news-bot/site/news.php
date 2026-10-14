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
    echo '<body style="font-family:system-ui,sans-serif;max-width:600px;margin:60px auto;padding:0 16px;text-align:center;color:#16151A;background:#FBFAF7">';
    echo '<h1>' . $msg . '</h1><p>' . ($code === 404 ? 'Возможно, её сняли с публикации.' : 'Попробуйте обновить страницу.') . '</p>';
    echo '<p><a href="' . h($SITE) . '/" style="color:#E5133C">← Все новости</a></p></body></html>';
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
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@700;800&family=Onest:wght@400;500;600;700&display=swap" rel="stylesheet">
<script type="application/ld+json"><?php echo $ldJson; ?></script>
<style>
  :root{--ink:#16151A;--ink-2:#2C2A26;--muted:#6B6A73;--line:#E7E3DA;--accent:#E5133C;--paper:#FBFAF7;--surface-2:#F3F0E9;}
  *{box-sizing:border-box;} body{margin:0;font-family:'Onest',system-ui,sans-serif;background:var(--paper);color:var(--ink);-webkit-font-smoothing:antialiased;}
  .wrap{max-width:760px;margin:0 auto;padding:22px 16px 60px;}
  a{color:var(--accent);}
  .back{display:inline-block;color:var(--muted);font-weight:600;margin-bottom:18px;text-decoration:none;}
  .back:hover{color:var(--accent);}
  h1{font-family:'Montserrat',sans-serif;font-weight:800;font-size:clamp(24px,5.4vw,38px);line-height:1.08;letter-spacing:-.01em;margin:0;}
  .date{color:var(--muted);font-size:14px;margin-top:10px;}
  .sum{font-size:18px;line-height:1.45;color:var(--ink-2);font-weight:500;margin:14px 0 0;}
  .media{margin-top:18px;display:flex;flex-direction:column;gap:12px;}
  .media img,.media video{display:block;max-width:100%;height:auto;max-height:80vh;margin:0 auto;border-radius:16px;background:var(--surface-2);}
  .media video{width:100%;background:#000;}
  .body{margin-top:18px;font-size:17px;line-height:1.7;color:var(--ink-2);}
  .body p{margin:0 0 14px;white-space:pre-line;overflow-wrap:anywhere;}
  .foot{margin-top:30px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:14px;display:flex;flex-wrap:wrap;gap:8px 18px;}
  .foot a{text-decoration:none;font-weight:600;}
</style>
</head>
<body>
  <article class="wrap">
    <a class="back" href="<?php echo h($SITE); ?>/">← Все новости</a>
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
    <div class="foot">
      <a href="<?php echo h($SITE); ?>/">Новости одной строкой</a>
      <a href="https://afisha.ekb-guide.ru/">Афиша Екатеринбурга</a>
      <a href="https://ekb-guide.ru/">ЕКБ ГИД</a>
    </div>
  </article>
</body>
</html>
