// Kopiert die Handy-App aus der Integration nach www/ (Inhalt der Android-App).
// Der Service Worker bleibt weg, dafür kommt capacitor.js dazu.
const fs = require("fs");
const path = require("path");

const SRC = path.join(__dirname, "..", "einkaufsliste", "integration", "einkaufsliste", "app");
const OUT = path.join(__dirname, "www");
const FILES = ["app.js", "app.css", "manifest.json", "icon-192.png", "icon-512.png"];

fs.rmSync(OUT, { recursive: true, force: true });
fs.mkdirSync(OUT);
for (const file of FILES) fs.copyFileSync(path.join(SRC, file), path.join(OUT, file));
fs.copyFileSync(require.resolve("@capacitor/core/dist/capacitor.js"), path.join(OUT, "capacitor.js"));

const html = fs.readFileSync(path.join(SRC, "index.html"), "utf8");
const script = '<script src="app.js"></script>';
if (!html.includes(script)) throw new Error("index.html: <script src=\"app.js\"> nicht gefunden");
fs.writeFileSync(path.join(OUT, "index.html"), html.replace(script, `<script src="capacitor.js"></script>\n  ${script}`));
console.log(`App nach ${OUT} kopiert`);
