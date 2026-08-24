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
// В выдаче время показываем часами без минут, с русским склонением (19 часов, 22 часа, 21 час).
// В базе start_time/end_time не меняем — округление только на отображении.
function hour_word($time) {
    if (!$time) return '';
    $h = intval(substr($time, 0, 2));
    $mod100 = $h % 100;
    $mod10 = $h % 10;
    if ($mod100 >= 11 && $mod100 <= 14) $word = 'часов';
    elseif ($mod10 === 1) $word = 'час';
    elseif ($mod10 >= 2 && $mod10 <= 4) $word = 'часа';
    else $word = 'часов';
    return $h . ' ' . $word;
}
function sched_text($ev, $MONTHS, $WD) {
    $t = !empty($ev['start_time']) ? hour_word($ev['start_time']) : '';
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
