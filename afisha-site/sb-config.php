<?php
// Общие настройки и помощники для SEO-страниц афиши
$SB_URL = 'https://sb.ekb-guide.ru';
$SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhibWRwcW5zZXl3cGh3Z3hzbmxnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk3MjE1NzYsImV4cCI6MjA5NTI5NzU3Nn0.wLuTKZ-uhCQ69iEm6gyJrsgaP0NgVL-PBad3kJD7uHU';
$SITE   = 'https://afisha.ekb-guide.ru';

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
    curl_close($ch);
    if ($res === false) return array();
    $data = json_decode($res, true);
    return is_array($data) ? $data : array();
}
function h($s) { return htmlspecialchars((string)$s, ENT_QUOTES, 'UTF-8'); }
function proxify($u) { return str_replace('https://hbmdpqnseywphwgxsnlg.supabase.co', 'https://sb.ekb-guide.ru', (string)$u); }

$MONTHS = array('', 'января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря');
$WD = array('', 'пн','вт','ср','чт','пт','сб','вс');

function day_str($d, $MONTHS) {
    if (!$d) return '';
    $p = explode('-', $d);
    if (count($p) < 3) return $d;
    return intval($p[2]) . ' ' . $MONTHS[intval($p[1])];
}
// Время в выдаче — ЧЧ:ММ (18:00), из start_time вида 18:00:00.
function time_str($time) {
    return $time ? substr($time, 0, 5) : '';
}
function sched_text($ev, $MONTHS, $WD) {
    $t = !empty($ev['start_time']) ? time_str($ev['start_time']) : '';
    if (($ev['schedule_type'] ?? 'single') === 'range' && !empty($ev['ends_on'])) {
        return day_str($ev['starts_on'], $MONTHS) . ' – ' . day_str($ev['ends_on'], $MONTHS) . ($t ? ', ' . $t : '');
    }
    if (($ev['schedule_type'] ?? '') === 'weekly') {
        $days = array();
        foreach (($ev['weekdays'] ?: array()) as $w) { if (isset($WD[$w])) $days[] = $WD[$w]; }
        return 'по ' . implode(', ', $days) . ($t ? ', ' . $t : '') . (!empty($ev['ends_on']) ? ' · до ' . day_str($ev['ends_on'], $MONTHS) : '');
    }
    return day_str($ev['starts_on'], $MONTHS) . ($t ? ', ' . $t : '');
}
function iso_dt($date, $time) {
    if (!$date) return '';
    $t = $time ? substr($time, 0, 8) : '00:00:00';
    if (strlen($t) === 5) $t .= ':00';
    return $date . 'T' . $t . '+05:00';
}

// Шрифты и стили SEO-страниц (event.php) по дизайн-коду ЕКБ ГИД — как ekb-guide.ru/price.
function page_assets() {
    return '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        . '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@600;700&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500;600&display=swap" rel="stylesheet">'
        . '<style>'
        . ':root{--paper:#F4F1E9;--card:#FFFDF7;--ink:#191512;--muted:#6F6A60;--line:#E4DFCF;--hl:#F5E24B;--hl-soft:#FCF4B4;--shadow:0 10px 26px rgba(25,21,18,.09);'
        . "--disp:'Montserrat',-apple-system,'Segoe UI',sans-serif;--sans:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;--mono:'JetBrains Mono',ui-monospace,monospace;}"
        . '*{box-sizing:border-box;}'
        . 'body{margin:0;font-family:var(--sans);font-size:16px;line-height:1.55;background:var(--paper);color:var(--ink);-webkit-font-smoothing:antialiased;}'
        . 'a{color:inherit;}'
        . '.wrap{max-width:760px;margin:0 auto;padding:32px 22px 80px;}'
        . '.back{display:inline-block;font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);text-decoration:none;margin-bottom:24px;}'
        . '.back:hover{color:var(--ink);}'
        . '.eyebrow{display:inline-block;font-family:var(--mono);font-size:11px;font-weight:600;letter-spacing:.18em;text-transform:uppercase;color:var(--muted);border:1px solid var(--line);border-radius:999px;padding:6px 13px;margin-bottom:18px;background:var(--card);}'
        . 'h1{font-family:var(--disp);font-weight:700;text-transform:uppercase;font-size:clamp(28px,4.6vw,46px);line-height:1.05;letter-spacing:-.005em;margin:0 0 12px;}'
        . '.hl{background-image:linear-gradient(var(--hl),var(--hl));background-repeat:no-repeat;background-position:0 82%;background-size:100% 64%;padding:.02em .16em;-webkit-box-decoration-break:clone;box-decoration-break:clone;}'
        . '.lead{color:var(--muted);font-size:clamp(16px,1.7vw,20px);margin:0 0 16px;}'
        . '.poster{display:block;max-width:100%;max-height:70vh;width:auto;height:auto;margin:22px 0;border-radius:16px;border:1px solid var(--line);}'
        . 'video{display:block;margin:22px 0;width:auto;max-width:100%;max-height:75vh;background:var(--ink);border-radius:16px;}'
        . '.meta{display:flex;flex-wrap:wrap;gap:8px 18px;font-family:var(--mono);font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:var(--muted);margin:12px 0 20px;}'
        . '.meta b{color:var(--ink);font-weight:600;}'
        . '.desc{line-height:1.65;white-space:pre-line;max-width:640px;}'
        . '.btns{display:flex;flex-wrap:wrap;gap:12px;margin:28px 0 8px;}'
        . '.btn{display:inline-flex;align-items:center;gap:8px;font-family:var(--disp);font-size:14px;font-weight:700;text-transform:uppercase;letter-spacing:.02em;padding:13px 24px;border-radius:999px;border:1.5px solid var(--ink);color:var(--ink);background:transparent;text-decoration:none;transition:transform .16s ease,box-shadow .16s ease,background .16s ease,color .16s ease;}'
        . '.btn:hover{transform:translateY(-2px);}'
        . '.btn-primary{background:var(--hl);border-color:var(--hl);}'
        . '.btn-primary:hover{box-shadow:0 8px 18px rgba(245,226,75,.55);}'
        . '.btn:not(.btn-primary):hover{background:var(--ink);color:var(--paper);}'
        . '.foot{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);color:var(--muted);font-size:14px;}'
        . '.foot a{color:var(--ink);text-decoration:underline;text-decoration-color:var(--hl);text-decoration-thickness:3px;text-underline-offset:3px;}'
        . '.list{list-style:none;padding:0;margin:26px 0 0;display:flex;flex-direction:column;gap:10px;}'
        . '.list a{display:block;background:var(--card);border:1px solid var(--line);border-radius:20px;padding:16px 20px;text-decoration:none;transition:transform .18s ease,border-color .18s ease,box-shadow .18s ease;}'
        . '.list a:hover{transform:translateY(-3px);border-color:var(--ink);box-shadow:var(--shadow);}'
        . '.list .t{display:block;font-family:var(--disp);font-weight:700;font-size:17px;line-height:1.2;}'
        . '.list .d{display:block;font-family:var(--mono);font-size:11.5px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);margin-top:6px;}'
        . '.nf{text-align:center;padding-top:48px;}.nf .btns{justify-content:center;}'
        . '@media (max-width:640px){.wrap{padding:22px 16px 56px;}.btn{width:100%;justify-content:center;}}'
        . '@media (prefers-reduced-motion:reduce){*{transition:none!important;}}'
        . '</style>';
}
