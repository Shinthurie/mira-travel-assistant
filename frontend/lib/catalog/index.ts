"use client";
// Our own A2UI catalog (no basic catalog): only these 8 components can ever be drawn.
import { createCatalog } from "@copilotkit/a2ui-renderer";
import { CATALOG_ID, definitions } from "./definitions";
import { renderers } from "./renderers";

// The renderer types props as "resolved bindings"; our renderers re-validate with zod, so we pass them
// through as unknown-props components.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export const miraCatalog = createCatalog(definitions, renderers as any, { catalogId: CATALOG_ID, includeBasicCatalog: false });
