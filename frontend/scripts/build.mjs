import { cpSync, mkdirSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const dist = resolve(root, "dist");
rmSync(dist, { recursive: true, force: true });
mkdirSync(dist, { recursive: true });
cpSync(resolve(root, "index.html"), resolve(dist, "index.html"));
cpSync(resolve(root, "styles.css"), resolve(dist, "styles.css"));
cpSync(resolve(root, "public/demo"), resolve(dist, "demo"), { recursive: true });
mkdirSync(resolve(dist, "vendor/images"), { recursive: true });
cpSync(resolve(root, "node_modules/leaflet/dist/leaflet.css"), resolve(dist, "vendor/leaflet.css"));
cpSync(resolve(root, "node_modules/leaflet/dist/images"), resolve(dist, "vendor/images"), { recursive: true });
await build({
  entryPoints: [resolve(root, "src/main.mjs")],
  bundle: true,
  format: "esm",
  outfile: resolve(dist, "main.mjs"),
});
console.log(`Built static console at ${dist}`);
