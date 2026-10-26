#!/usr/bin/env node
// Puente entre el asistente y Alexa (Amazon), con alexa-remote2 (Apollon77, MIT): lo que Alexa maneja (luces,
// enchufes, termostatos…, de cualquier marca) lo maneja también el asistente, y puede hacer hablar al Echo.
//
// Solo escucha en 127.0.0.1:3457 (lo usa core-orchestrator/alexa.py):
//   GET  /estado                      → {listo, login: "http://IP:3456" mientras falte entrar en Amazon, echos}
//   GET  /dispositivos                → [{id, nombre, tipo, entidad}]  (lo que sale en la app Alexa → Dispositivos)
//   POST /accion  {id, accion, valor} → turnOn / turnOff / setBrightness (0-100) / setPercentage
//   POST /texto   {texto, echo?}      → como si se lo dijeras al Echo («enciende la luz del salón»)
//   POST /decir   {texto, echo?}      → el Echo lo dice en voz alta
//   POST /salir                       → olvida la cuenta (hay que volver a entrar)
//
// La primera vez no hay sesión: abre un «proxy» de inicio de sesión de Amazon en http://IP-del-portátil:3456. La
// persona entra con SU cuenta en su navegador (el asistente nunca ve ni escribe la contraseña). La sesión que da
// Amazon (no la contraseña) se guarda en ~/jarvis/alexa.json (solo legible por el usuario) y se renueva sola.
// En el registro nunca se escriben cookies ni tokens.
"use strict";
const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const Alexa = require("alexa-remote2");

const DATOS = process.env.JARVIS_SECRETOS || path.join(os.homedir(), "jarvis");
const SESION = path.join(DATOS, "alexa.json");
const PUERTO = 3457, PUERTO_LOGIN = 3456;
const PAGINA = process.env.ALEXA_AMAZON || "amazon.es";

let alexa = null, listo = false, urlLogin = "", error = "", cache = { t: 0, lista: [] };

function log(...a) {
    const s = a.map(String).join(" ");
    // nada que pueda llevar la sesión: alexa-remote2 vuelca a veces los datos de registro completos
    if (/cookie|token|csrf|macdms|adp_|private|\{/i.test(s)) return;
    console.log(new Date().toISOString().slice(11, 19), s.slice(0, 300));
}

function ipRuta() {
    // la IP con la que el portátil sale a internet (la que ven los demás de casa), no la primera que aparezca
    return new Promise(ok => {
        const s = require("dgram").createSocket("udp4");
        s.on("error", () => { try { s.close(); } catch {} ok(""); });
        s.connect(53, "1.1.1.1", () => { let a = ""; try { a = s.address().address; } catch {} s.close(); ok(a); });
    });
}

function ipLocal() {
    if (process.env.ALEXA_IP) return process.env.ALEXA_IP;
    for (const lista of Object.values(os.networkInterfaces()))
        for (const i of lista || [])
            if (i.family === "IPv4" && !i.internal) return i.address;
    return "127.0.0.1";
}

function leerSesion() {
    try { return JSON.parse(fs.readFileSync(SESION, "utf8")); } catch { return null; }
}

function guardarSesion(datos) {
    const tmp = SESION + ".tmp";
    fs.writeFileSync(tmp, JSON.stringify(datos), { mode: 0o600 });
    fs.renameSync(tmp, SESION);
    fs.chmodSync(SESION, 0o600);
}

async function arrancar() {
    listo = false; error = ""; urlLogin = "";
    alexa = new Alexa();
    const previa = leerSesion();
    const ip = (await ipRuta()) || ipLocal();
    alexa.on("cookie", () => {
        if (alexa.cookieData) { guardarSesion(alexa.cookieData); log("sesión de Amazon guardada/renovada"); }
    });
    alexa.init({
        cookie: previa || undefined,
        formerRegistrationData: previa || undefined,
        proxyOnly: true,
        setupProxy: true,
        proxyOwnIp: ip,
        proxyPort: PUERTO_LOGIN,
        proxyListenBind: "0.0.0.0",
        proxyLogLevel: "warn",
        amazonPage: PAGINA,
        alexaServiceHost: "alexa." + PAGINA,
        acceptLanguage: "es-ES",
        amazonPageProxyLanguage: "es_ES",
        usePushConnection: false,
        bluetooth: false,
        cookieRefreshInterval: 4 * 24 * 3600 * 1000,
        logger: log,
    }, (err) => {
        if (err) {
            const m = String(err.message || err);
            const u = m.match(/https?:\/\/[^\s]+/);
            if (u) { urlLogin = u[0].replace(/[\/.,]+$/, "/"); log("falta entrar en Amazon: " + urlLogin); return; }
            error = m.slice(0, 200); log("error al conectar: " + error);
            setTimeout(arrancar, 10 * 60 * 1000);       // sin internet, Amazon caído…: reintenta
            return;
        }
        listo = true; urlLogin = "";
        if (alexa.cookieData) guardarSesion(alexa.cookieData);
        log("conectado a Alexa: " + echos().map(e => e.nombre).join(", "));
    });
}

function echos() {
    if (!alexa || !alexa.serialNumbers) return [];
    return Object.values(alexa.serialNumbers)
        .filter(d => (d.capabilities || []).includes("TTS_ANNOUNCEMENT") || /ECHO|KNIGHT|ROOK|FIRE/i.test(d.deviceFamily || ""))
        .map(d => ({ serie: d.serialNumber, nombre: d.accountName, familia: d.deviceFamily, en_linea: !!d.online }));
}

function echoElegido(nombre) {
    const lista = echos();
    if (!lista.length) return null;
    if (nombre) {
        const n = nombre.toLowerCase();
        const e = lista.find(x => x.nombre.toLowerCase().includes(n));
        if (e) return e.serie;
    }
    return (lista.find(x => x.en_linea) || lista[0]).serie;
}

function p(fn, ...args) {
    return new Promise((ok, mal) => fn.call(alexa, ...args, (err, res) => err ? mal(err) : ok(res)));
}

async function dispositivos() {
    if (Date.now() - cache.t < 10 * 60 * 1000 && cache.lista.length) return cache.lista;
    const lista = [];
    const items = await p(alexa.getSmarthomeDevicesV2);
    let entidades = [];
    try { entidades = await p(alexa.getSmarthomeEntities); } catch { entidades = []; }
    const porAparato = {};
    for (const e of entidades || []) {
        const ap = e.providerData && e.providerData.applianceId;
        if (ap) porAparato[ap] = e.id;
    }
    for (const it of items || []) {
        const ap = it.legacyAppliance || {};
        const tipo = (it.displayCategories && it.displayCategories.primary && it.displayCategories.primary.value) ||
                     (ap.applianceTypes || [])[0] || "";
        if (/ALEXA_VOICE_ENABLED|SPEAKER|TABLET|GAME_CONSOLE/i.test(tipo) && !ap.applianceId) continue;
        lista.push({ id: ap.applianceId || it.endpointId || it.id, nombre: it.friendlyName || ap.friendlyName || "",
                     tipo, entidad: porAparato[ap.applianceId] || it.endpointId || "" });
    }
    cache = { t: Date.now(), lista: lista.filter(d => d.nombre) };
    return cache.lista;
}

async function accion(id, acc, valor) {
    const lista = await dispositivos();
    const d = lista.find(x => x.id === id || x.entidad === id);
    if (!d) throw new Error("no conozco ese dispositivo");
    const params = { action: acc };
    if (acc === "setBrightness") params.brightness = Math.max(0, Math.min(100, Number(valor) || 0));
    if (acc === "setPercentage") params.percentage = Math.max(0, Math.min(100, Number(valor) || 0));
    for (const ent of [d.entidad, d.id].filter(Boolean)) {
        try {
            const r = await p(alexa.executeSmarthomeDeviceAction, [ent], params, "APPLIANCE");
            const errs = (r && r.errors) || [];
            if (!errs.length) return { ok: true, via: "directo", nombre: d.nombre };
            if (errs.some(e => e.code === "ENDPOINT_UNREACHABLE")) return { ok: false, motivo: "no responde", nombre: d.nombre };
        } catch (e) { log("acción directa falló: " + String(e.message || e).slice(0, 120)); }
    }
    // si Amazon no acepta la orden directa, se la decimos al Echo como si hablaras
    const frase = { turnOn: `enciende ${d.nombre}`, turnOff: `apaga ${d.nombre}`,
                    setBrightness: `pon ${d.nombre} al ${params.brightness} por ciento`,
                    setPercentage: `pon ${d.nombre} al ${params.percentage} por ciento` }[acc];
    if (!frase) throw new Error("acción no admitida");
    await texto(frase);
    return { ok: true, via: "echo", nombre: d.nombre };
}

async function texto(frase, echo) {
    const serie = echoElegido(echo);
    if (!serie) throw new Error("no encuentro ningún Echo en la cuenta");
    await p(alexa.sendSequenceCommand, serie, "textCommand", String(frase).slice(0, 300));
    return { ok: true };
}

async function decir(frase, echo) {
    const serie = echoElegido(echo);
    if (!serie) throw new Error("no encuentro ningún Echo en la cuenta");
    await p(alexa.sendSequenceCommand, serie, "speak", String(frase).slice(0, 500));
    return { ok: true };
}

function responder(res, code, obj) {
    const b = Buffer.from(JSON.stringify(obj));
    res.writeHead(code, { "Content-Type": "application/json; charset=utf-8", "Content-Length": b.length });
    res.end(b);
}

http.createServer((req, res) => {
    let cuerpo = "";
    req.on("data", c => { cuerpo += c; if (cuerpo.length > 20000) req.destroy(); });
    req.on("end", async () => {
        let j = {};
        try { j = cuerpo ? JSON.parse(cuerpo) : {}; } catch { return responder(res, 400, { error: "JSON" }); }
        try {
            if (req.url === "/estado") return responder(res, 200, { listo, login: urlLogin, error, echos: listo ? echos() : [] });
            if (req.method === "POST" && req.url === "/salir") {
                try { fs.unlinkSync(SESION); } catch {}
                cache = { t: 0, lista: [] };
                try { alexa && alexa.stop && alexa.stop(); } catch {}
                arrancar();
                return responder(res, 200, { ok: true });
            }
            if (!listo) return responder(res, 503, { error: urlLogin ? "falta entrar en Amazon" : (error || "conectando"), login: urlLogin });
            if (req.url === "/dispositivos") return responder(res, 200, await dispositivos());
            if (req.method !== "POST") return responder(res, 404, { error: "no existe" });
            if (req.url === "/accion") return responder(res, 200, await accion(j.id, j.accion, j.valor));
            if (req.url === "/texto") return responder(res, 200, await texto(j.texto, j.echo));
            if (req.url === "/decir") return responder(res, 200, await decir(j.texto, j.echo));
            return responder(res, 404, { error: "no existe" });
        } catch (e) {
            const m = String(e && e.message || e);
            log("error: " + m.slice(0, 150));
            return responder(res, 500, { error: /cookie|token|csrf/i.test(m) ? "la sesión de Amazon ha caducado" : m.slice(0, 200) });
        }
    });
}).listen(PUERTO, "127.0.0.1", () => log(`puente de Alexa en 127.0.0.1:${PUERTO} (${PAGINA})`));

arrancar();
