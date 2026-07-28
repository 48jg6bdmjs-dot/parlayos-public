export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    let path = url.pathname;
    if (path === "/" || path === "") path = "/parlayos.html";

    try {
      let res = await env.ASSETS.fetch(new Request(new URL(path, url.origin), request));
      if (res.status === 404 && path!== "/parlayos.html") {
        res = await env.ASSETS.fetch(new Request(new URL("/parlayos.html", url.origin), request));
      }
      return res;
    } catch {
      return await env.ASSETS.fetch(new Request(new URL("/parlayos.html", url.origin), request));
    }
  }
};
