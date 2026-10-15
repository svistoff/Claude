<?php
require __DIR__ . '/sb-config.php';

$slug = isset($_GET['slug']) ? preg_replace('/[^A-Za-z0-9_-]/', '', trim($_GET['slug'])) : '';

// ---------- Индекс (если slug не задан): список событий ----------
if ($slug === '') {
    $events = sb_get('events?status=eq.published&select=title,slug,starts_on,start_time,schedule_type,ends_on,weekdays,cover_image_url&order=starts_on.asc');
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
    echo '<title>Все события — Афиша Екатеринбурга | ЕКБ ГИД</title>';
    echo '<meta name="description" content="Все события афиши Екатеринбурга: концерты, вечеринки, выставки, рестораны и городские события — ЕКБ ГИД.">';
    echo '<link rel="canonical" href="' . h($SITE) . '/afisha/">';
    echo page_assets() . '</head><body><div class="wrap">';
    echo '<a class="back" href="' . h($SITE) . '/">← Афиша Екатеринбурга</a><br>';
    echo '<span class="eyebrow">ЕКБ ГИД · Афиша</span>';
    echo '<h1>Все <span class="hl">события</span></h1><ul class="list">';
    foreach ($events as $e) {
        echo '<li><a href="' . h($SITE) . '/afisha/' . h($e['slug']) . '"><span class="t">' . h($e['title']) . '</span><span class="d">' . h(sched_text($e, $MONTHS, $WD)) . '</span></a></li>';
    }
    echo '</ul><div class="foot">Афиша Екатеринбурга · <a href="' . h($SITE) . '/">ЕКБ ГИД</a></div></div></body></html>';
    exit;
}

// ---------- Страница события ----------
$rows = sb_get('events?slug=eq.' . rawurlencode($slug) . '&status=eq.published&select=*&limit=1');
if (empty($rows)) {
    http_response_code(404);
    header('Content-Type: text/html; charset=utf-8');
    echo '<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">';
    echo '<title>Событие не найдено — Афиша ЕКБ ГИД</title><meta name="robots" content="noindex">' . page_assets() . '</head><body>';
    echo '<div class="wrap nf"><span class="eyebrow">Афиша Екатеринбурга</span><h1>Событие <span class="hl">не найдено</span></h1>';
    echo '<p class="lead">Возможно, оно уже прошло — загляните в афишу, там много другого.</p>';
    echo '<div class="btns"><a class="btn btn-primary" href="' . h($SITE) . '/">Смотреть афишу <span aria-hidden="true">→</span></a></div></div></body></html>';
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
$descRaw = ($ev['meta_description'] ?? null) ?: ($ev['short_description'] ?: ($ev['title'] . ($venueName ? ', ' . $venueName : '') . '. ' . $dateStr . '. Афиша Екатеринбурга — ЕКБ ГИД.'));
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
if (!empty($ev['ends_on'])) $ld['endDate'] = iso_dt($ev['ends_on'], ($ev['end_time'] ?? null) ?: $ev['start_time']);
if ($previewImage) $ld['image'] = array($previewImage);
if ($desc) $ld['description'] = $desc;
$ld['location'] = array('@type' => 'Place', 'name' => $venueName ?: 'Екатеринбург', 'address' => $venueAddr ?: 'Екатеринбург');
// performer: исполнитель, иначе площадка как организация (Google рекомендует поле всегда)
if (!empty($ev['performer'])) $ld['performer'] = array('@type' => 'PerformingGroup', 'name' => $ev['performer']);
elseif ($venueName) $ld['performer'] = array('@type' => 'Organization', 'name' => $venueName);
// offers: всегда — ссылка на билеты/страницу, цена если распознана, validFrom = когда событие появилось в афише
$offer = array('@type' => 'Offer', 'url' => ($ev['external_url'] ?: $canonical), 'availability' => 'https://schema.org/InStock');
$priceText = (string)($ev['price'] ?? '');
if ($priceText !== '' && mb_stripos($priceText, 'бесплат', 0, 'UTF-8') !== false) {
    $offer['price'] = '0'; $offer['priceCurrency'] = 'RUB';
} elseif (preg_match('/\d[\d\s]*/u', $priceText, $m)) {
    $offer['price'] = preg_replace('/\s+/u', '', $m[0]); $offer['priceCurrency'] = 'RUB';
}
$validFromRaw = ($ev['published_at'] ?? null) ?: (($ev['created_at'] ?? null) ?: null);
$validFromTs = $validFromRaw ? strtotime($validFromRaw) : false;
$offer['validFrom'] = $validFromTs ? date('c', $validFromTs) : iso_dt($ev['starts_on'], null);
$ld['offers'] = $offer;
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
<script type="application/ld+json"><?php echo $ldJson; ?></script>
<?php echo page_assets(); ?>
</head>
<body>
  <div class="wrap">
    <a class="back" href="<?php echo h($SITE); ?>/">← Афиша Екатеринбурга</a><br>
    <span class="eyebrow"><?php echo h($cat ? $cat['name'] : 'Афиша Екатеринбурга'); ?></span>
    <h1><?php echo h($ev['title']); ?></h1>
    <?php if (!empty($ev['performer'])): ?><p class="lead"><?php echo h($ev['performer']); ?></p><?php endif; ?>
    <?php if ($cover): ?><img class="poster" src="<?php echo h($cover); ?>" alt="<?php echo h($ev['title']); ?>"><?php endif; ?>
    <?php if ($video): ?><video src="<?php echo h($video); ?>" controls playsinline></video><?php endif; ?>
    <div class="meta">
      <span><b><?php echo h($dateStr); ?></b></span>
      <?php if ($venueName): ?><span><?php echo h($venueName); ?><?php echo $venueAddr ? ', ' . h($venueAddr) : ''; ?></span><?php endif; ?>
      <?php if (!empty($ev['price'])): ?><span><b><?php echo h($ev['price']); ?></b></span><?php endif; ?>
    </div>
    <?php if (!empty($ev['full_description']) || !empty($ev['short_description'])): ?>
      <div class="desc"><?php echo h($ev['full_description'] ?: $ev['short_description']); ?></div>
    <?php endif; ?>
    <div class="btns">
      <?php if (!empty($ev['external_url'])): ?><a class="btn btn-primary" href="<?php echo h($ev['external_url']); ?>" target="_blank" rel="noopener">Билеты и подробности <span aria-hidden="true">→</span></a><?php endif; ?>
      <a class="btn" href="<?php echo h($SITE); ?>/">Вся афиша</a>
    </div>
    <div class="foot">Событие в афише Екатеринбурга · <a href="<?php echo h($SITE); ?>/">ЕКБ ГИД</a></div>
  </div>
</body>
</html>
