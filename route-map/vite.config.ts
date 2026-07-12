/// <reference types="node" />
import { createReadStream, existsSync, statSync } from "node:fs";
import { extname, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import type { Connect, PluginOption } from "vite";
import { defineConfig } from "vitest/config";

// The webapp is a read-only consumer of the pipelines' working-tree output
// under the repo-root `guides/<id>/data/` tree (route-map/CLAUDE.md rule 6).
// That tree is gitignored and lives OUTSIDE route-map/, so the dev server
// mounts the two relevant stage dirs at stable URLs. The guide is chosen by
// VITE_GUIDE_ID, defaulting to the single existing guide so `npm run dev` is a
// genuine one-command start.
const GUIDE_ID = process.env.VITE_GUIDE_ID ?? "wetterstein";
const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url));
const GUIDE_DATA_ROOT = resolve(REPO_ROOT, "guides", GUIDE_ID, "data");

// URL scheme (stable — later tickets' src/data adapter fetches these):
//   /guide-data/parse-routes/03_structured/routes.json
//   /guide-data/fetch-pois/04_final/pois.geojson
//   /guide-data/fetch-pois/04_final/route_pois.jsonl
// i.e. `/guide-data/` maps onto `guides/<id>/data/`, mirroring the on-disk
// layout minus the guide prefix. Only the two owned stage dirs are exposed.
const DATA_URL_PREFIX = "/guide-data/";
const EXPOSED_STAGE_DIRS = [
	"parse-routes/03_structured/",
	"fetch-pois/04_final/",
];

const MIME_BY_EXT: Record<string, string> = {
	".json": "application/json; charset=utf-8",
	".geojson": "application/geo+json; charset=utf-8",
	".jsonl": "application/x-ndjson; charset=utf-8",
};

function serveGuideData(): PluginOption {
	const middleware: Connect.NextHandleFunction = (req, res, next) => {
		const url = req.url;
		if (!url || (req.method !== "GET" && req.method !== "HEAD")) {
			next();
			return;
		}
		const pathname = decodeURIComponent(url.split("?")[0] ?? "");
		if (!pathname.startsWith(DATA_URL_PREFIX)) {
			next();
			return;
		}

		const rel = pathname.slice(DATA_URL_PREFIX.length);
		if (!EXPOSED_STAGE_DIRS.some((dir) => rel.startsWith(dir))) {
			res.statusCode = 404;
			res.end("Not found");
			return;
		}

		const filePath = resolve(GUIDE_DATA_ROOT, rel);
		// Path-traversal guard: resolved path must stay inside the guide data root.
		if (
			filePath !== GUIDE_DATA_ROOT &&
			!filePath.startsWith(GUIDE_DATA_ROOT + sep)
		) {
			res.statusCode = 403;
			res.end("Forbidden");
			return;
		}
		if (!existsSync(filePath) || !statSync(filePath).isFile()) {
			res.statusCode = 404;
			res.end(`Not found: ${rel} (has the pipeline produced it yet?)`);
			return;
		}

		res.setHeader(
			"Content-Type",
			MIME_BY_EXT[extname(filePath)] ?? "application/octet-stream",
		);
		res.setHeader("Cache-Control", "no-cache");
		if (req.method === "HEAD") {
			res.end();
			return;
		}
		createReadStream(filePath).pipe(res);
	};

	return {
		name: "route-map:serve-guide-data",
		configureServer(server) {
			server.middlewares.use(middleware);
		},
		configurePreviewServer(server) {
			server.middlewares.use(middleware);
		},
	};
}

export default defineConfig({
	plugins: [react(), serveGuideData()],
	server: {
		// Allow Vite's own fs access to reach the repo-root guide data tree.
		fs: { allow: [REPO_ROOT] },
	},
	test: {
		// route-map/CLAUDE.md: Vitest is node-env only, for the pure src/data
		// adapter's load/join logic — the one sanctioned automated-test point.
		environment: "node",
	},
});
