export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    // Serve parlayos.html as root
    let path = url.pathname;
    if (path === "/" || path === "") {
      path = "/parlayos.html";
    }
    // Try to fetch from assets
    try {
      // For Workers with assets, env.ASSETS is available
      if (env.ASSETS) {
        const assetRequest = new Request(new URL(path, request.url));
        const response = await env.ASSETS.fetch(assetRequest);
        if (response.status !== 404) {
          return response;
        }
        // Fallback to parlayos.html for SPA
        const fallback = await env.ASSETS.fetch(new Request(new URL("/parlayos.html", request.url)));
        return fallback;
      }
    } catch (e) {
      // Fallback
    }
    
    // Fallback fetch
    return new Response("Hello world - assets not configured. Add wrangler.toml with [assets] directory", {
      headers: { "content-type": "text/plain" }
    });
  }
};