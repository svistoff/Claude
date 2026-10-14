<?php
// Карта сайта для Яндекса и Google: главная, список всех событий и страница каждого опубликованного события.
// Отдаётся по адресу /sitemap.xml (rewrite в nginx).
require __DIR__ . '/sb-config.php';

$events = sb_get('events?status=eq.published&select=slug&order=starts_on.asc');

header('Content-Type: application/xml; charset=utf-8');
echo '<?xml version="1.0" encoding="UTF-8"?>' . "\n";
echo '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' . "\n";
echo '  <url><loc>' . h($SITE) . '/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>' . "\n";
echo '  <url><loc>' . h($SITE) . '/afisha/</loc><changefreq>daily</changefreq><priority>0.8</priority></url>' . "\n";
foreach ($events as $e) {
    if (empty($e['slug'])) continue;
    echo '  <url><loc>' . h($SITE . '/afisha/' . rawurlencode($e['slug'])) . '</loc><changefreq>weekly</changefreq><priority>0.7</priority></url>' . "\n";
}
echo '</urlset>' . "\n";
