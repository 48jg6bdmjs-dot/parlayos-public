export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let pathname = url.pathname;

    // Serve parlayos.html for root
    if (pathname === "/" || pathname === "") {
      pathname = "/parlayos.html";
    }

    const assetUrl = new URL(pathname, url.origin);
    const assetRequest = new Request(assetUrl, request);
    
    try {
      let response = await env.ASSETS.fetch(assetRequest);
      
      // If 404 and not already parlayos.html, try parlayos.html
      if (response.status === 404 && pathname !== "/parlayos.html") {
        const fallbackUrl = new URL("/parlayos.html", url.origin);
        response = await env.ASSETS.fetch(new Request(fallbackUrl, request));
      }
      
      return response;
    } catch (e) {
      // Final fallback
      const fallbackUrl = new URL("/parlayos.html", url.origin);
      try {
        return await env.ASSETS.fetch(new Request(fallbackUrl, request));
      } catch {
        return new Response("ParlayOS - file not found", { status: 404 });
      }
    }
  }
};
