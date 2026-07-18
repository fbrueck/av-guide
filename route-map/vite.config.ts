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
// mounts every Guide's two relevant stage dirs at stable id-namespaced URLs.
// The middleware no longer selects a Guide — the id is a path segment — so
// `npm run dev` serves every Guide's live tree with no env selection.
const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url));
const GUIDES_ROOT = resolve(REPO_ROOT, "guides");
// The committed Guide manifest (ADR-0005): app/maintainer metadata at the root of
// the shared guides tree, NOT pipeline output, so it sits beside the per-Guide
// data dirs and is served at the id-less `/guide-data/guides.json` URL.
const GUIDES_MANIFEST_PATH = resolve(GUIDES_ROOT, "guides.json");

// URL scheme (stable — the src/data adapter fetches these):
//   /guide-data/<id>/parse-routes/03_structured/routes.json
//   /guide-data/<id>/fetch-pois/04_final/pois.geojson
//   /guide-data/<id>/fetch-pois/04_final/place_pois.jsonl
//   /guide-data/<id>/fetch-pois/04_final/entry_pois.jsonl
// i.e. `/guide-data/<id>/` maps onto `guides/<id>/data/`, mirroring the on-disk
// layout. The `<id>` path segment keys the static snapshot on GitHub Pages
// (which ignores query strings). Only the two owned stage dirs are exposed.
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

		// The Guide manifest is served id-less from `guides/guides.json` — it is
		// the index over Guide ids, not one Guide's data, so it does not take the
		// `<id>/<stage-dir>` path below (ADR-0005). Matched by exact path.
		if (pathname === `${DATA_URL_PREFIX}guides.json`) {
			if (!existsSync(GUIDES_MANIFEST_PATH)) {
				res.statusCode = 404;
				res.end("Not found: guides.json (the Guide manifest is missing)");
				return;
			}
			res.setHeader("Content-Type", MIME_BY_EXT[".json"] ?? "application/json");
			res.setHeader("Cache-Control", "no-cache");
			if (req.method === "HEAD") {
				res.end();
				return;
			}
			createReadStream(GUIDES_MANIFEST_PATH).pipe(res);
			return;
		}

		// Split the leading `<id>` path segment off; the remainder is the
		// stage-relative path within `guides/<id>/data/`.
		const afterPrefix = pathname.slice(DATA_URL_PREFIX.length);
		const slash = afterPrefix.indexOf("/");
		if (slash < 1) {
			res.statusCode = 404;
			res.end("Not found");
			return;
		}
		const guideId = afterPrefix.slice(0, slash);
		const rel = afterPrefix.slice(slash + 1);
		if (!EXPOSED_STAGE_DIRS.some((dir) => rel.startsWith(dir))) {
			res.statusCode = 404;
			res.end("Not found");
			return;
		}

		// Path-traversal guard: the guide's data root must stay inside GUIDES_ROOT
		// (rejects a `..` in the id segment), and the resolved file must stay inside
		// that guide's data root.
		const guideDataRoot = resolve(GUIDES_ROOT, guideId, "data");
		if (!guideDataRoot.startsWith(GUIDES_ROOT + sep)) {
			res.statusCode = 403;
			res.end("Forbidden");
			return;
		}
		const filePath = resolve(guideDataRoot, rel);
		if (
			filePath !== guideDataRoot &&
			!filePath.startsWith(guideDataRoot + sep)
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

export default defineConfig(({ command }) => ({
	// Conditional base: root in dev, the GitHub Pages project-site path in build.
	// It must be conditional — an unconditional `/av-guide/` would make the
	// src/data adapter fetch `/av-guide/guide-data/…` in dev too, which the
	// `configureServer` middleware below (matching the bare `/guide-data/`
	// prefix) would not answer. By design, `/guide-data/` is served two ways:
	// in dev by the live middleware over the gitignored working tree, and in the
	// deployed build by a committed static snapshot (#46 part 2). Both answer the
	// same URL; only the base prefix differs (`/` dev, `/av-guide/` deploy).
	base: command === "build" ? "/av-guide/" : "/",
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
}));
