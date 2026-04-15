/**
 * Cloudflare Worker: proxy for checkee.info
 * Deploy once, add the worker URL as PROXY_BASE_URL secret in GitHub.
 *
 * Usage: https://your-worker.workers.dev/main.php?sortby=clear_date
 */
export default {
  async fetch(request) {
    const url = new URL(request.url);
    const target = 'https://www.checkee.info' + url.pathname + url.search;

    const response = await fetch(target, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Referer': 'https://www.checkee.info/',
      },
      redirect: 'follow',
    });

    // Pass body and status through; strip problematic headers
    const headers = new Headers(response.headers);
    headers.delete('content-encoding'); // CF decompresses for us
    headers.set('access-control-allow-origin', '*');

    return new Response(response.body, {
      status: response.status,
      headers,
    });
  },
};
