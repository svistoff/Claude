<?php
require __DIR__ . '/sb-config.php';

$slug = isset($_GET['slug']) ? preg_replace('/[^A-Za-z0-9_-]/', '', trim($_GET['slug'])) : '';

// ---------- Индекс (если slug не задан): список событий ----------
if ($slug === '') {
    $events = sb_get('events?status=eq.published&select=title,slug,starts_on,start_time,schedule_type,ends_on,weekdays,cover_image_url&order=starts_on.asc');
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
    echo '<title>Все события — Афиша Екатеринбурга | ЕКБ ГИД</title>';
    echo '<link rel="canonical" href="' . h($SITE) . '/afisha/">';
    echo '<style>body{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:760px;margin:0 auto;padding:24px;color:#16151A}a{color:#E5133C;text-decoration:none}h1{font-size:26px}li{margin:8px 0}</style></head><body>';
    echo '<h1>Афиша Екатеринбурга — все события</h1><ul>';
    foreach ($events as $e) {
        echo '<li><a href="' . h($SITE) . '/afisha/' . h($e['slug']) . '">' . h($e['title']) . '</a> — ' . h(sched_text($e, $MONTHS, $WD)) . '</li>';
    }
    echo '</ul><p><a href="' . h($SITE) . '/">← На главную афишу</a></p></body></html>';
    exit;
}

// ---------- Страница события ----------
$rows = sb_get('events?slug=eq.' . rawurlencode($slug) . '&status=eq.published&select=*&limit=1');
if (empty($rows)) {
    http_response_code(404);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><meta charset="utf-8"><title>Событие не найдено — Афиша ЕКБ ГИД</title>';
    echo '<div style="font-family:system-ui;max-width:600px;margin:60px auto;text-align:center;color:#16151A">';
    echo '<h1>Событие не найдено</h1><p>Возможно, оно уже прошло.</p><p><a href="' . h($SITE) . '/" style="color:#E5133C">← На главную афишу</a></p></div>';
    exit;
}
$ev = $rows[0];

$venue = null; $cat = null;
if (!empty($ev['venue_id'])) { $v = sb_get('venues?id=eq.' . rawurlencode($ev['venue_id']) . '&select=name,address,city,logo_url&limit=1'); if (!empty($v)) $venue = $v[0]; }
if (!empty($ev['category_id'])) { $c = sb_get('categories?id=eq.' . rawurlencode($ev['category_id']) . '&select=name&limit=1'); if (!empty($c)) $cat = $c[0]; }

$canonical = $SITE . '/afisha/' . $ev['slug'];
$cover = proxify($ev['cover_image_url']);
$video = proxify($ev['video_url']);
// Превью/OG-картинка: реальная афиша, иначе логотип заведения (для видео-анонсов без постера).
// В самой странице ($cover) логотип не подставляем — он не должен дублироваться рядом с видео.
$previewImage = $cover ?: ($venue && !empty($venue['logo_url']) ? proxify($venue['logo_url']) : null);
$dateStr = sched_text($ev, $MONTHS, $WD);
$venueName = $venue ? $venue['name'] : '';
$venueAddr = $venue ? trim(($venue['address'] ?: '') . (!empty($venue['city']) ? ', ' . $venue['city'] : '')) : '';

// title / description
$titleTag = $ev['title'] . ($venueName ? ' — ' . $venueName : '') . ' | Афиша Екатеринбурга';
$descRaw = $ev['meta_description'] ?: ($ev['short_description'] ?: ($ev['title'] . ($venueName ? ', ' . $venueName : '') . '. ' . $dateStr . '. Афиша Екатеринбурга — ЕКБ ГИД.'));
$desc = mb_substr(trim(preg_replace('/\s+/u', ' ', $descRaw)), 0, 200, 'UTF-8');

// JSON-LD Event
$ld = array(
    '@context' => 'https://schema.org',
    '@type' => 'Event',
    'name' => $ev['title'],
    'startDate' => iso_dt($ev['starts_on'], $ev['start_time']),
    'eventStatus' => 'https://schema.org/EventScheduled',
    'eventAttendanceMode' => 'https://schema.org/OfflineEventAttendanceMode',
    'url' => $canonical,
    'organizer' => array('@type' => 'Organization', 'name' => 'ЕКБ ГИД', 'url' => $SITE),
);
if (!empty($ev['ends_on'])) $ld['endDate'] = iso_dt($ev['ends_on'], $ev['end_time'] ?: $ev['start_time']);
if ($previewImage) $ld['image'] = array($previewImage);
if ($desc) $ld['description'] = $desc;
$ld['location'] = array('@type' => 'Place', 'name' => $venueName ?: 'Екатеринбург', 'address' => $venueAddr ?: 'Екатеринбург');
if (!empty($ev['performer'])) $ld['performer'] = array('@type' => 'PerformingGroup', 'name' => $ev['performer']);
if (!empty($ev['price'])) {
    preg_match('/\d[\d\s]*/u', $ev['price'], $m);
    $num = isset($m[0]) ? preg_replace('/\s+/', '', $m[0]) : '';
    $ld['offers'] = array('@type' => 'Offer', 'priceCurrency' => 'RUB', 'price' => ($num !== '' ? $num : '0'), 'availability' => 'https://schema.org/InStock', 'url' => ($ev['external_url'] ?: $canonical));
}
$ldJson = json_encode($ld, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);

header('Content-Type: text/html; charset=utf-8');
?><!doctype html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title><?php echo h($titleTag); ?></title>
<meta name="description" content="<?php echo h($desc); ?>">
<link rel="canonical" href="<?php echo h($canonical); ?>">
<meta property="og:type" content="article">
<meta property="og:title" content="<?php echo h($ev['title'] . ($venueName ? ' — ' . $venueName : '')); ?>">
<meta property="og:description" content="<?php echo h($desc); ?>">
<meta property="og:url" content="<?php echo h($canonical); ?>">
<meta property="og:site_name" content="Афиша ЕКБ ГИД">
<?php if ($previewImage): ?><meta property="og:image" content="<?php echo h($previewImage); ?>"><?php endif; ?>
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="<?php echo h($ev['title']); ?>">
<meta name="twitter:description" content="<?php echo h($desc); ?>">
<?php if ($previewImage): ?><meta name="twitter:image" content="<?php echo h($previewImage); ?>"><?php endif; ?>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700;800&family=Onest:wght@400;500;600;700&display=swap" rel="stylesheet">
<script type="application/ld+json"><?php echo $ldJson; ?></script>
<style>
  :root{--ink:#16151A;--muted:#6B6A73;--line:#E7E3DA;--accent:#E5133C;--accent-ink:#B00E30;--paper:#FBFAF7;}
  *{box-sizing:border-box;} body{margin:0;font-family:'Onest',system-ui,sans-serif;background:var(--paper);color:var(--ink);-webkit-font-smoothing:antialiased;}
  .wrap{max-width:760px;margin:0 auto;padding:20px 18px 60px;}
  a{color:var(--accent);text-decoration:none;}
  .back{display:inline-block;color:var(--muted);font-weight:600;margin-bottom:16px;}
  h1{font-family:'Montserrat',sans-serif;font-weight:800;font-size:clamp(24px,5vw,36px);line-height:1.05;margin:0 0 6px;}
  .perf{color:var(--muted);font-size:17px;margin-bottom:14px;}
  .poster{display:block;max-width:100%;max-height:70vh;width:auto;height:auto;margin:16px 0;border-radius:16px;}
  video{display:block;margin:16px auto;width:auto;max-width:100%;max-height:75vh;background:#000;border-radius:16px;}
  .meta{display:flex;flex-wrap:wrap;gap:8px 18px;font-size:15px;color:var(--muted);margin:6px 0 14px;}
  .meta b{color:var(--ink);}
  .desc{line-height:1.65;color:#2C2A26;white-space:pre-line;font-size:16px;}
  .ticket{display:inline-block;margin:22px 0 8px;background:var(--accent);color:#fff;border-radius:999px;padding:13px 24px;font-weight:700;}
  .ticket:hover{background:var(--accent-ink);}
  .foot{margin-top:26px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:14px;}
</style>
</head>
<body>
  <div class="wrap">
    <a class="back" href="<?php echo h($SITE); ?>/">← Афиша Екатеринбурга</a>
    <h1><?php echo h($ev['title']); ?></h1>
    <?php if (!empty($ev['performer'])): ?><div class="perf"><?php echo h($ev['performer']); ?></div><?php endif; ?>
    <?php if ($cover): ?><img class="poster" src="<?php echo h($cover); ?>" alt="<?php echo h($ev['title']); ?>"><?php endif; ?>
    <?php if ($video): ?><video src="<?php echo h($video); ?>" controls playsinline></video><?php endif; ?>
    <div class="meta">
      <span><b><?php echo h($dateStr); ?></b></span>
      <?php if ($cat): ?><span><?php echo h($cat['name']); ?></span><?php endif; ?>
      <?php if ($venueName): ?><span><?php echo h($venueName); ?><?php echo $venueAddr ? ', ' . h($venueAddr) : ''; ?></span><?php endif; ?>
      <?php if (!empty($ev['price'])): ?><span><b><?php echo h($ev['price']); ?></b></span><?php endif; ?>
    </div>
    <?php if (!empty($ev['full_description']) || !empty($ev['short_description'])): ?>
      <div class="desc"><?php echo h($ev['full_description'] ?: $ev['short_description']); ?></div>
    <?php endif; ?>
    <?php if (!empty($ev['external_url'])): ?><a class="ticket" href="<?php echo h($ev['external_url']); ?>" target="_blank" rel="noopener">Билеты и подробности →</a><?php endif; ?>
    <div class="foot">Событие в афише Екатеринбурга · <a href="<?php echo h($SITE); ?>/">ЕКБ ГИД</a></div>
  </div>
</body>
</html>
