// The SolidSeas reference viewer: the service's file list, a part or an assembly drawn in
// 3D from its display mesh (/v1/mesh, a glTF binary), its bill of materials (/v1/bom) and
// its custom properties. `solidseas serve --viewer` serves this page and everything it
// loads; it fetches nothing from anywhere else, which its Content-Security-Policy holds it
// to. The token stays in this page's memory and travels only in the Authorization header,
// to this page's own origin; reloading the page forgets it. docs/API.md 8.18 describes it.

import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";

const byId = (id) => document.getElementById(id);
const ui = {
  form: byId("token-form"),
  token: byId("token"),
  status: byId("status"),
  root: byId("root"),
  crumbs: byId("crumbs"),
  entries: byId("entries"),
  more: byId("more"),
  name: byId("doc-name"),
  facts: byId("facts"),
  tabs: [byId("tab-model"), byId("tab-bom"), byId("tab-props")],
  panes: [byId("pane-model"), byId("pane-bom"), byId("pane-props")],
  stage: document.querySelector(".stage"),
  canvas: byId("view"),
  modelNote: byId("model-note"),
  bom: byId("bom"),
  bomNote: byId("bom-note"),
  props: byId("props"),
  propsNote: byId("props-note"),
};

let token = null; // in memory only
let root = null;
let folder = "";
let cursor = null;
let listing = 0; // the listing whose answers may still be shown
let opened = 0; // the document whose answers may still be shown

// ----------------------------------------------------------------------------- the service
class ServiceError extends Error {
  constructor(status, error) {
    super(error && typeof error.message === "string" ? error.message : `The service answered ${status}.`);
    this.status = status;
    this.code = error && typeof error.code === "string" ? error.code : null;
  }
}

async function call(route, params = {}, binary = false) {
  const query = new URLSearchParams(params).toString();
  const response = await fetch(`/v1/${route}${query ? `?${query}` : ""}`, {
    headers: { Authorization: `Bearer ${token}` },
    credentials: "omit",
    redirect: "error",
    cache: "no-cache",
  });
  if (!response.ok) {
    let error = null;
    try {
      error = (await response.json()).error;
    } catch {
      // not the service's JSON: the status says enough
    }
    throw new ServiceError(response.status, error);
  }
  if (binary) {
    return response.arrayBuffer();
  }
  const envelope = await response.json();
  if (!envelope || envelope.ok !== true) {
    throw new ServiceError(response.status, envelope && envelope.error);
  }
  return envelope.data;
}

function say(text) {
  ui.status.textContent = text;
}

function make(tag, className, text) {
  const node = document.createElement(tag);
  if (className) {
    node.className = className;
  }
  if (text !== undefined && text !== null) {
    node.textContent = String(text);
  }
  return node;
}

// ----------------------------------------------------------------------------- roots and folders
ui.form.addEventListener("submit", (event) => {
  event.preventDefault();
  const given = ui.token.value.trim();
  ui.token.value = "";
  if (given) {
    token = given;
    loadRoots();
  }
});

ui.root.addEventListener("change", () => {
  root = ui.root.value;
  openFolder("");
});

ui.more.addEventListener("click", () => openFolder(folder, true));

async function loadRoots() {
  say("Connecting...");
  try {
    const data = await call("roots");
    const roots = Array.isArray(data.roots) ? data.roots : [];
    ui.root.replaceChildren(
      ...roots.map((r) => {
        const option = make("option", null, r.state === "ready" ? r.id : `${r.id} (${r.state})`);
        option.value = r.id;
        return option;
      }),
    );
    ui.root.disabled = roots.length === 0;
    if (roots.length === 0) {
      say("The service serves no folder.");
      return;
    }
    say("Connected. The token is kept in this page only: reloading it asks for the token again.");
    root = roots[0].id;
    ui.root.value = root;
    openFolder("");
  } catch (error) {
    token = null;
    say(error.status === 401 ? "The service did not accept that token." : error.message);
  }
}

async function openFolder(path, more = false) {
  const run = more ? listing : ++listing;
  if (!more) {
    folder = path;
    cursor = null;
    ui.entries.replaceChildren();
    drawCrumbs();
  }
  ui.more.hidden = true;
  const params = { root, include: "preview,preview_data", limit: "100" };
  if (folder) {
    params.path = folder;
  }
  if (more && cursor) {
    params.cursor = cursor;
  }
  try {
    const data = await call("list", params);
    if (run !== listing) {
      return;
    }
    for (const entry of data.entries) {
      ui.entries.append(entryItem(entry));
    }
    cursor = typeof data.next_cursor === "string" ? data.next_cursor : null;
    ui.more.hidden = !cursor;
    if (!more && data.entries.length === 0) {
      ui.entries.append(make("li", "note", "No folder or SOLIDWORKS file here."));
    }
  } catch (error) {
    if (run === listing) {
      say(error.message);
    }
  }
}

function drawCrumbs() {
  const parts = folder ? folder.split("/") : [];
  const crumbs = [crumb(root, "")];
  parts.forEach((part, i) => crumbs.push(crumb(part, parts.slice(0, i + 1).join("/"))));
  ui.crumbs.replaceChildren(...crumbs);
}

function crumb(text, path) {
  const item = make("li");
  const button = make("button", null, text);
  button.type = "button";
  button.addEventListener("click", () => openFolder(path));
  item.append(button);
  return item;
}

const BASE64 = /^[A-Za-z0-9+/]*={0,2}$/;

function thumbnail(preview) {
  const image = make("img", "thumb");
  image.alt = "";
  const data = preview && preview.data_base64;
  const mime = preview && preview.mime;
  if (typeof data === "string" && (mime === "image/png" || mime === "image/bmp") && BASE64.test(data)) {
    image.src = `data:${mime};base64,${data}`;
  }
  return image;
}

function entryItem(entry) {
  const item = make("li");
  const button = make("button", "entry");
  button.type = "button";
  const name = entry.path.split("/").pop();
  const label = make("span", "entry-name");
  label.append(make("span", null, name));
  if (entry.type === "folder") {
    button.append(make("span", "folder-mark", "folder"), label);
    button.disabled = entry.status !== "ok";
    button.addEventListener("click", () => openFolder(entry.path));
  } else {
    const kind = entry.status === "ok" ? entry.doc_type || "file" : entry.error?.message || entry.status;
    label.append(make("span", "entry-kind", kind));
    button.append(thumbnail(entry.preview), label);
    button.disabled = entry.status !== "ok";
    button.addEventListener("click", () => {
      for (const other of ui.entries.querySelectorAll(".entry[aria-current]")) {
        other.removeAttribute("aria-current");
      }
      button.setAttribute("aria-current", "true");
      openDocument(entry.path, name, entry.doc_type);
    });
  }
  item.append(button);
  return item;
}

// ----------------------------------------------------------------------------- a document
ui.tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => {
    ui.tabs.forEach((t, j) => t.setAttribute("aria-selected", String(i === j)));
    ui.panes.forEach((pane, j) => {
      pane.hidden = i !== j;
    });
    if (i === 0) {
      resize();
    }
  });
});

function openDocument(path, name, docType) {
  const run = ++opened;
  const at = { root, path };
  const current = () => run === opened;
  ui.name.textContent = name;
  ui.facts.replaceChildren();
  showModel(null);
  ui.modelNote.textContent = "Reading the 3D model...";
  ui.modelNote.classList.remove("warn");
  ui.bom.replaceChildren();
  ui.bomNote.textContent =
    docType === "assembly" ? "Reading the bill of materials..." : "Only an assembly has a bill of materials.";
  ui.props.replaceChildren();
  ui.propsNote.textContent = "Reading the properties...";

  call("document", at).then(
    (summary) => current() && showFacts(summary),
    (error) => current() && say(error.message),
  );
  call("mesh", at, true).then(
    (buffer) => current() && readModel(buffer, current),
    (error) => current() && modelNote(error.message, true),
  );
  call("properties", at).then(
    (data) => current() && showProperties(data),
    (error) => {
      if (current()) {
        ui.propsNote.textContent = error.message;
      }
    },
  );
  if (docType === "assembly") {
    call("bom", { ...at, type: "indented" }).then(
      (data) => current() && showBom(data),
      (error) => {
        if (current()) {
          ui.bomNote.textContent = error.message;
        }
      },
    );
  }
}

function showFacts(summary) {
  const facts = [
    ["Type", summary.doc_type],
    ["Configuration", summary.active_configuration],
    ["Saved with", summary.saved_version && summary.saved_version.release],
    ["Size", summary.file && typeof summary.file.size === "number" ? `${Math.ceil(summary.file.size / 1024)} KB` : null],
    ["Modified", summary.file && summary.file.modified_utc ? summary.file.modified_utc.slice(0, 16).replace("T", " ") : null],
  ];
  ui.facts.replaceChildren(
    ...facts
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([label, value]) => {
        const row = make("div");
        row.append(make("dt", null, label), make("dd", null, value));
        return row;
      }),
  );
}

function table(target, header, rows) {
  const head = make("thead");
  const headRow = make("tr");
  for (const title of header) {
    headRow.append(make("th", null, title));
  }
  head.append(headRow);
  const body = make("tbody");
  for (const cells of rows) {
    const row = make("tr");
    for (const cell of cells) {
      row.append(cell instanceof Node ? cell : make("td", typeof cell === "number" ? "number" : null, cell ?? ""));
    }
    body.append(row);
  }
  target.replaceChildren(head, body);
}

function showProperties(data) {
  const props = Array.isArray(data.properties) ? data.properties : [];
  ui.propsNote.textContent = props.length
    ? `Configuration ${data.configuration ?? "(none)"}: the properties it shows, its own and the file's.`
    : "The file stores no custom properties.";
  table(
    ui.props,
    ["Name", "Value"],
    props.map((p) => [p.name, p.text ?? p.value]),
  );
}

function showBom(data) {
  const rows = Array.isArray(data.rows) ? data.rows : [];
  ui.bomNote.textContent = rows.length
    ? `Configuration ${data.configuration ?? "(none)"}${data.complete ? "" : ": incomplete, some rows are in doubt"}.`
    : "The bill of materials is empty.";
  table(
    ui.bom,
    ["Item", "Part number", "Description", "Qty", "Total"],
    rows.map((r) => {
      const item = make("td", null, r.item);
      item.style.paddingLeft = `${8 + 16 * (Number.isInteger(r.level) ? Math.min(r.level, 12) : 0)}px`;
      return [item, r.part_number, r.description, r.quantity, r.total_quantity];
    }),
  );
}

// ----------------------------------------------------------------------------- the 3D view
let view = null; // made on first use: a renderer, a scene, a camera and its controls
let model = null; // what is drawn now

function makeView() {
  let renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: ui.canvas, antialias: true });
  } catch {
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(35, 1, 0.001, 1000);
  scene.add(camera);
  scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7078, 1.6));
  const headlight = new THREE.DirectionalLight(0xffffff, 1.8);
  headlight.position.set(0.5, 1, 1);
  camera.add(headlight);
  const controls = new OrbitControls(camera, ui.canvas);
  const made = { renderer, scene, camera, controls };
  controls.addEventListener("change", () => render(made));
  new ResizeObserver(() => resize()).observe(ui.stage);
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
    background(made);
    render(made);
  });
  background(made);
  return made;
}

function background(v) {
  const color = getComputedStyle(document.documentElement).getPropertyValue("--view-bg").trim();
  v.scene.background = new THREE.Color(color || "#eceff3");
}

function render(v = view) {
  if (v) {
    v.renderer.render(v.scene, v.camera);
  }
}

function resize() {
  if (!view) {
    return;
  }
  const width = ui.stage.clientWidth;
  const height = ui.stage.clientHeight;
  if (width && height) {
    view.renderer.setSize(width, height, false);
    view.camera.aspect = width / height;
    view.camera.updateProjectionMatrix();
    render();
  }
}

function modelNote(text, warn = false) {
  ui.modelNote.textContent = text;
  ui.modelNote.classList.toggle("warn", warn);
}

function dispose(object) {
  object.traverse((node) => {
    if (node.geometry) {
      node.geometry.dispose();
    }
    if (node.material) {
      for (const material of Array.isArray(node.material) ? node.material : [node.material]) {
        material.dispose();
      }
    }
  });
}

function showModel(object) {
  if (model && view) {
    view.scene.remove(model);
    dispose(model);
  }
  model = object;
  if (view && model) {
    view.scene.add(model);
  }
  render();
}

function readModel(buffer, current) {
  if (!view) {
    view = makeView();
    if (!view) {
      modelNote("This browser cannot draw 3D here: WebGL is not available.", true);
      return;
    }
    resize();
  }
  new GLTFLoader().parse(
    buffer,
    "",
    (gltf) => {
      if (current()) {
        placeModel(gltf.scene);
      }
    },
    () => {
      if (current()) {
        modelNote("The 3D model could not be read.", true);
      }
    },
  );
}

const PLACEHOLDER = 0xd08a2c;

function placeModel(scene) {
  const info = (scene.userData && scene.userData.solidseas) || {};
  const group = new THREE.Group();
  group.add(scene);
  const box = new THREE.Box3().setFromObject(scene);
  for (const skipped of Array.isArray(info.skipped_listed) ? info.skipped_listed : []) {
    if (!Array.isArray(skipped.box)) {
      continue;
    }
    const placeholder = new THREE.Box3(
      new THREE.Vector3().fromArray(skipped.box[0]),
      new THREE.Vector3().fromArray(skipped.box[1]),
    );
    group.add(new THREE.Box3Helper(placeholder, PLACEHOLDER));
    box.union(placeholder);
  }
  showModel(group);
  frame(box);
  const parts = info.instances ?? 0;
  const boxes = info.skipped ?? 0;
  let note =
    info.doc_type === "part"
      ? `${info.triangles} triangles, from the part's ${info.source === "bodies" ? "bodies" : "display mesh"}.`
      : `${parts} part instance${parts === 1 ? "" : "s"} drawn from the assembly's own display data.`;
  if (boxes) {
    note += ` ${boxes} shown as boxes: the assembly does not store their meshes.`;
  }
  modelNote(`${note} Drag to turn, scroll to zoom, right-drag to pan.`, boxes > 0);
}

function frame(box) {
  if (!view || box.isEmpty()) {
    return;
  }
  const { camera, controls } = view;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3()).length() || 1;
  const distance = (size / 2 / Math.tan(THREE.MathUtils.degToRad(camera.fov) / 2)) * 1.15;
  camera.position.copy(center).add(new THREE.Vector3(1, 0.8, 1.3).normalize().multiplyScalar(distance));
  camera.near = distance / 1000;
  camera.far = distance * 100;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
  render();
}
