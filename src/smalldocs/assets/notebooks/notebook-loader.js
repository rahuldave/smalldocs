/* Adapted from the website's ZIP -> IndexedDB -> JupyterLite notebook loader. */
(function () {
  "use strict";

  const card = document.querySelector(".sd-notebook-loader");
  const status = document.getElementById("notebook-status");
  const params = new URLSearchParams(window.location.search);
  const labBase = new URL("./", window.location.href);
  const siteRoot = new URL("../", labBase);
  const workspace = params.get("path");
  const notebookName = params.get("notebook");
  const app = window.innerWidth < 768 ? "notebooks" : "lab";
  // Both apps use the root baseUrl in the JupyterLite configuration.
  const storagePath = labBase.pathname;

  function safePath(path) {
    return path && !path.startsWith("/") && !path.split("/").some(part => part === ".." || part === "." || !part);
  }

  function openDatabase() {
    return new Promise((resolve, reject) => {
      const request = indexedDB.open("JupyterLite Storage - " + storagePath);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains("files")) request.result.createObjectStore("files");
      };
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  function put(db, path, content, format, type, mimetype) {
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("files", "readwrite");
      const now = new Date().toISOString();
      transaction.objectStore("files").put({
        name: path.split("/").pop(), path, content, format, type, mimetype,
        created: now, last_modified: now, writable: true,
        size: content === null ? 0 : (typeof content === "string" ? content.length : JSON.stringify(content).length)
      }, path);
      transaction.oncomplete = resolve;
      transaction.onerror = () => reject(transaction.error);
      transaction.onabort = () => reject(transaction.error || new Error("Could not save notebook files"));
    });
  }

  function installCell(notebook) {
    for (const cell of notebook.cells) {
      const code = Array.isArray(cell.source) ? cell.source.join("") : cell.source || "";
      if (cell.cell_type !== "code" || !code.includes("# /// script")) continue;
      // SmallDocs writes these lines itself in the copied notebook.
      const dependencies = code.split("\n").map(line => line.trim())
        .filter(line => line.startsWith('#   "') && line.endsWith('",'))
        .map(line => JSON.parse(line.slice(4, -1)));
      cell.source = dependencies.length
        ? ["import micropip\n", "await micropip.install(" + JSON.stringify(dependencies) + ")\n"]
        : ["# This notebook uses the Python standard library.\n"];
      cell.outputs = [];
      cell.execution_count = null;
      break;
    }
  }

  async function run() {
    if (!params.get("zip") || !safePath(workspace) || !safePath(notebookName) || notebookName.includes("/")) {
      throw new Error("Open this page with a notebook's Run in browser button.");
    }
    const zipUrl = new URL(params.get("zip"), siteRoot);
    if (zipUrl.origin !== siteRoot.origin || !zipUrl.pathname.startsWith(siteRoot.pathname + "site_libs/notebooks/")) {
      throw new Error("The notebook bundle must belong to this site.");
    }
    status.textContent = "Downloading notebook and data files...";
    const response = await fetch(zipUrl);
    if (!response.ok) throw new Error("Could not download the notebook (" + response.status + ").");
    const zip = await JSZip.loadAsync(await response.arrayBuffer());
    const file = zip.file(notebookName);
    if (!file) throw new Error("The bundle does not contain " + notebookName + ".");
    const notebook = JSON.parse(await file.async("string"));
    installCell(notebook);

    status.textContent = "Copying files into JupyterLite...";
    const db = await openDatabase();
    try {
      const directories = new Set();
      const names = Object.keys(zip.files).filter(name => !zip.files[name].dir && name !== "README.md");
      for (const name of names) {
        if (!safePath(name)) throw new Error("The bundle contains an invalid file path.");
        const parts = (workspace + "/" + name).split("/");
        for (let n = 1; n < parts.length; n++) directories.add(parts.slice(0, n).join("/"));
      }
      for (const directory of directories) await put(db, directory, null, "json", "directory", "");
      await put(db, workspace + "/" + notebookName, notebook, "json", "notebook", "application/x-ipynb+json");
      const textTypes = {csv: "text/csv", tsv: "text/tab-separated-values", txt: "text/plain", json: "application/json",
        geojson: "application/geo+json", py: "text/x-python", svg: "image/svg+xml"};
      for (const name of names) {
        if (name === notebookName) continue;
        const mime = textTypes[name.split(".").pop().toLowerCase()];
        const content = await zip.files[name].async(mime ? "string" : "base64");
        await put(db, workspace + "/" + name, content, mime ? "text" : "base64", "file", mime || "application/octet-stream");
      }
    } finally {
      db.close();
    }
    status.textContent = "Opening JupyterLite...";
    const destination = new URL(app + "/index.html", labBase);
    destination.searchParams.set("path", workspace + "/" + notebookName);
    window.location.href = destination.href;
  }

  run().catch(error => {
    card.setAttribute("aria-busy", "false");
    status.textContent = error.message;
  });
})();
