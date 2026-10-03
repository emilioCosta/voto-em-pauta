const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");

const root = path.resolve(__dirname, "..", "out");
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "/informeC";
const port = Number(process.env.PORT || 4173);
const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".pdf": "application/pdf",
  ".sqlite3": "application/vnd.sqlite3",
  ".wasm": "application/wasm",
};

http.createServer((request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, "http://localhost").pathname);
  if (pathname !== basePath && !pathname.startsWith(`${basePath}/`)) {
    response.writeHead(404).end("Not found");
    return;
  }

  let relativePath = pathname.slice(basePath.length) || "/";
  if (relativePath === "/") relativePath = "/index.html";
  let filePath = path.resolve(root, `.${relativePath}`);
  if (filePath !== root && !filePath.startsWith(`${root}${path.sep}`)) {
    response.writeHead(403).end("Forbidden");
    return;
  }
  if (fs.existsSync(filePath) && fs.statSync(filePath).isDirectory()) {
    filePath = path.join(filePath, "index.html");
  }

  response.setHeader("Content-Type", mimeTypes[path.extname(filePath)] || "application/octet-stream");
  const stream = fs.createReadStream(filePath);
  stream.on("error", () => response.writeHead(404).end("Not found"));
  stream.pipe(response);
}).listen(port, "127.0.0.1", () => {
  console.log(`Pages preview: http://127.0.0.1:${port}${basePath}/`);
});