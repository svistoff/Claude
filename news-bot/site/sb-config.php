<?php
// Общие настройки и помощники для SEO-страниц новостей (по образцу afisha-site/sb-config.php).
// Ключ — публичный anon (тот же, что в index.html), RLS отдаёт только опубликованное.
$SB_URL = 'https://sb.ekb-guide.ru';
$SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhibWRwcW5zZXl3cGh3Z3hzbmxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MjE1NzYsImV4cCI6MjA5NTI5NzU3Nn0.wLuTKZ-uhCQ69iEm6gyJrsgaP0NgVL-PBad3kJD7uHU';
$SITE   = 'https://news.ekb-guide.ru';
$MEDIA  = 'https://video.ekb-guide.ru/m/';

function sb_get($path) {
    global $SB_URL, $SB_KEY;
    $ch = curl_init($SB_URL . '/rest/v1/' . $path);
    curl_setopt_array($ch, array(
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_HTTPHEADER => array('apikey: ' . $SB_KEY, 'Authorization: Bearer ' . $SB_KEY, 'Accept: application/json'),
        CURLOPT_TIMEOUT => 10,
        CURLOPT_CONNECTTIMEOUT => 6,
    ));
    $res = curl_exec($ch);
    $code = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    curl_close($ch);
    if ($res === false || $code >= 400) return null;   // null — ошибка, array() — пусто
    $data = json_decode($res, true);
    return is_array($data) ? $data : null;
}
function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }

$MONTHS = array('', 'января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря');

// Дата публикации по Екатеринбургу: «14 октября 2026»
function ekb_dt($iso) {
    $d = new DateTime($iso);
    $d->setTimezone(new DateTimeZone('Asia/Yekaterinburg'));
    return $d;
}
function day_str($iso, $MONTHS) {
    if (!$iso) return '';
    $d = ekb_dt($iso);
    return intval($d->format('j')) . ' ' . $MONTHS[intval($d->format('n'))] . ' ' . $d->format('Y');
}
function iso_ekb($iso) {
    return $iso ? ekb_dt($iso)->format('Y-m-d\TH:i:sP') : '';
}
// Текст новости → абзацы, ссылки кликабельные (сначала экранируем, потом размечаем)
function paragraphs($text) {
    $out = '';
    foreach (preg_split('/\n\s*\n/u', trim((string)$text)) as $p) {
        $p = trim($p);
        if ($p === '') continue;
        $p = h($p);
        $p = preg_replace('~(https?://[^\s<>"\']+[^\s<>"\'.,;:!?)\]])~u', '<a href="$1" target="_blank" rel="noopener">$1</a>', $p);
        $out .= '<p>' . $p . '</p>';
    }
    return $out;
}
