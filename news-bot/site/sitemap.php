<?php
// Карта сайта для Яндекса и Google: главная и страница каждой опубликованной новости.
// Отдаётся по адресу /sitemap.xml (rewrite в nginx).
require __DIR__ . '/sb-config.php';

$rows = sb_get('news?select=slug,published_at&order=published_at.desc&limit=5000');
if ($rows === null) $rows = array();

header('Content-Type: application/xml; charset=utf-8');
echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' . "\n";
echo '  <url><loc>' . h($SITE) . '/</loc><changefreq>hourly</changefreq><priority>1.0</priority></url>' . "\n";
foreach ($rows as $n) {
    if (empty($n['slug'])) continue;
    echo '  <url><loc>' . h($SITE . '/n/' . rawurlencode($n['slug'])) . '</loc><lastmod>' . h(iso_ekb($n['published_at'])) . '</lastmod><priority>0.7</priority></url>' . "\n";
}
echo '</urlset>' . "\n";
