/* ==================================================================
   CONFIGURACIÓN
   Esta página la sirve Django en la raíz ("/"), en el MISMO puerto que
   la API (ver supermotos_backend/urls.py -> vista `frontend`). Por eso
   API_URL se deja vacío: las llamadas fetch usan ruta relativa
   ("/api/productos/...") y resuelven contra el propio origen, sin CORS
   ni depender de a qué puerto quedó pegado el backend.
   USAR_DEMO controla si se usa el inventario de ejemplo (solo para abrir
   el HTML suelto, con doble clic o Live Server, sin backend corriendo).
   ================================================================== */
const API_URL = "";        // "" = mismo origen (recomendado). Solo pon una URL absoluta para apuntar a otro backend (ej. Railway en producción).
const USAR_DEMO = false;   // true = usar INVENTARIO de ejemplo en vez del backend real

/* ================= DATOS DEMO (solo si no hay API) ================= */
const INVENTARIO = [
  {id:1, nombre:"Kit de arrastre", ref:"06406-KYJ-900", modelo:"CB160F DLX", precio:138000, stock:6},
  {id:2, nombre:"Pastillas freno delanteras", ref:"06455-KYJ-901", modelo:"CB160F DLX", precio:42000, stock:12},
  {id:3, nombre:"Filtro de aire", ref:"17210-KRE-D20", modelo:"XR150L", precio:29500, stock:9},
  {id:4, nombre:"Bujía NGK CPR8EA-9", ref:"31916-KRM-841", modelo:"Varios modelos", precio:18500, stock:25},
  {id:5, nombre:"Aceite Honda HP4 20W-50", ref:"HP4-20W50-1L", modelo:"Todos", precio:34000, stock:40},
  {id:6, nombre:"Bomba de gasolina", ref:"16700-K56-N01", modelo:"CB190R", precio:185000, stock:3},
  {id:7, nombre:"Kit cilindro completo", ref:"12100-KRE-D00", modelo:"XR150L", precio:265000, stock:2},
  {id:8, nombre:"Llanta trasera 100/80-17", ref:"42711-KYJ-D01", modelo:"CB160F DLX", precio:158000, stock:5},
];
/* Pesos colombianos, formato determinista: puntos de miles, sin decimales.
   No usa toLocaleString("es-CO") porque en un navegador sin datos ICU/Intl
   completos el mismo número sale como "42,000" o "42000" (nunca "$42", pero
   inconsistente de un dispositivo a otro). */
const fmt = n => "$" + Math.round(Number(n) || 0).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");

/* ================= PLACA DE PRODUCTO (sin foto elegida) =================
   Ana elige a mano la foto de cada producto desde el admin (imagen subida
   o URL pegada tras buscarla en Google Imágenes). Nada se asigna solo.
   Mientras un producto no tenga foto, se muestra esta "placa" tipo tienda
   online — marca, nombre grande y referencia — en vez de íconos o dibujos
   técnicos que podrían no corresponder al producto real. */
function placaHtml(p){
  const marca = esc((p.marca || "Honda").toUpperCase());
  const cat = esc((p.categoria || "").toUpperCase());
  return `<div class="placa">
    <span class="placa-marca">${marca}</span>
    ${cat ? `<span class="placa-watermark">${cat}</span>` : ""}
    <span class="placa-nombre">${esc(p.nombre)}</span>
    ${p.ref ? `<span class="placa-ref">${esc(p.ref)}</span>` : ""}
  </div>`;
}

/* ================= CAPA DE API ================= */
function mapProducto(p){
  return {id:p.id, nombre:p.nombre, ref:p.referencia || p.codigo_celeste,
          modelo:p.modelos_compatibles || p.categoria || "Honda",
          categoria:p.categoria || "", marca:p.marca || "Honda",
          precio:parseFloat(p.precio), stock:p.stock,
          foto: p.foto || null};  // foto elegida por Ana en el admin; null = mostrar placa
}
async function apiBuscar(q){
  if(USAR_DEMO){
    const t = q.toLowerCase();
    const items = INVENTARIO.filter(p =>
      (p.nombre+" "+p.modelo+" "+p.ref).toLowerCase().includes(t) ||
      t.split(" ").every(w => (p.nombre+" "+p.modelo).toLowerCase().includes(w)));
    return {items, fallback:false};
  }
  try{
    // priorizar_stock (no con_stock): el buscador del bot NO debe excluir
    // los agotados -- los reordena al final para poder ofrecer "avísenme
    // cuando llegue" en vez de decir que el producto no existe. con_stock
    // aquí SÍ los quitaría del todo (ver tienda/busqueda.py y ProductoViewSet).
    const r = await fetch(`${API_URL}/api/productos/?buscar=${encodeURIComponent(q)}&priorizar_stock=1`);
    const items = (await r.json()).map(mapProducto);
    // X-Busqueda-Fallback: el backend no encontró todas las palabras juntas
    // y relajó la búsqueda (ver tienda/busqueda.py); el bot matiza el mensaje.
    return {items, fallback: r.headers.get("X-Busqueda-Fallback") === "1"};
  }catch(e){ console.error(e); return {items:[], fallback:false}; }
}
async function apiCatalogo(){
  if(USAR_DEMO) return INVENTARIO;
  try{
    // con_stock=1 acá SÍ debe filtrar de verdad: el catálogo de la página no
    // muestra agotados (a diferencia del buscador del bot, ver apiBuscar).
    const r = await fetch(`${API_URL}/api/productos/?con_stock=1`);
    return (await r.json()).slice(0,8).map(mapProducto);
  }catch(e){ console.error(e); return []; }
}
const CHIP_KEYWORDS_DEMO = {
  frenos:["freno","pastilla","banda","disco","zapata"],
  filtros:["filtro"],
  aceites:["aceite","lubricante"],
  electrico:["bujia","bateria","cdi","bobina","farol","direccional","stop"],
  transmision:["arrastre","cadena","piñon","sprocket","clutch","embrague","corona"],
  llantas:["llanta","neumatico","rin","caucho","tubo"],
};
async function apiPorCategoria(cat){
  if(USAR_DEMO){
    const palabras = CHIP_KEYWORDS_DEMO[cat] || [];
    return INVENTARIO.filter(p => palabras.some(w => p.nombre.toLowerCase().includes(w)));
  }
  try{
    const r = await fetch(`${API_URL}/api/productos/?categoria=${encodeURIComponent(cat)}&con_stock=1`);
    return (await r.json()).map(mapProducto);
  }catch(e){ console.error(e); return []; }
}
async function apiCrearCotizacion(datos){
  if(USAR_DEMO) return {id: 42};
  const r = await fetch(`${API_URL}/api/cotizaciones/`, {method:"POST",
    headers:{"Content-Type":"application/json"}, body:JSON.stringify(datos)});
  return await r.json();
}
/* ================= CONTACTO DEL ALMACÉN (fuente única: /api/config/) =================
   Ningún dato de contacto se quema en el HTML: WhatsApp, teléfono fijo y
   dirección salen de ConfiguracionSitio (admin). Los valores por defecto son
   VACÍOS a propósito: si /api/config/ se cae, el sitio degrada (esconde el
   botón de WhatsApp, muestra el canal alterno) en vez de mandar clientes a un
   número inventado con el mensaje bien formado y sin aviso. */
let CONFIG_SITIO = {whatsapp_asesor:"", nombre_asesor:"", telefono_fijo:"", direccion:""};
async function cargarConfig(){
  if(USAR_DEMO) return;
  try{
    const r = await fetch(`${API_URL}/api/config/`);
    CONFIG_SITIO = await r.json();
  }catch(e){ console.error(e); }   // se queda con los vacíos -> degrada, no miente
}
const configListo = cargarConfig();

/* El número del asesor es el único dato que, mal configurado, rompe TODOS los
   botones de WhatsApp del sitio. Se valida más estricto que el del cliente
   (10-15 dígitos, no 7: siempre lleva indicativo de país). Si no es plausible
   devuelve "" y quien llama esconde el botón y muestra el canal alterno. */
function waAsesor(){
  const d = String(CONFIG_SITIO.whatsapp_asesor || "").replace(/\D/g, "");
  return (d.length >= 10 && d.length <= 15) ? d : "";
}

/* Canal alterno cuando no hay WhatsApp válido: teléfono fijo y/o dirección,
   lo que Ana haya cargado. Si no cargó ninguno devuelve "" y quien llama
   simplemente no muestra nada (mejor vacío que un dato de ejemplo). */
function canalAlternoHtml(){
  const tel = CONFIG_SITIO.telefono_fijo, dir = CONFIG_SITIO.direccion;
  if(!tel && !dir) return "";
  return `<div class="canal-alterno">` +
    (tel ? `<i data-lucide="phone" class="lucide"></i> ${esc(tel)}` : "") +
    (tel && dir ? "<br>" : "") +
    (dir ? `<i data-lucide="map-pin" class="lucide"></i> ${esc(dir)}` : "") +
    `</div>`;
}

function linkWhatsApp(numero, texto){
  const limpio = String(numero || "").replace(/\D/g, "");
  return `https://wa.me/${limpio}?text=${encodeURIComponent(texto)}`;
}

/* Contacto del pie de página y de la sección de taller: misma fuente única.
   Lo que Ana no haya cargado, no se muestra (sin datos de ejemplo). */
function pintarContacto(){
  const num = waAsesor();
  const dir = CONFIG_SITIO.direccion, tel = CONFIG_SITIO.telefono_fijo;
  const footer = document.getElementById("footerContacto");
  if(footer){
    footer.innerHTML = [
      dir && `<i data-lucide="map-pin" class="lucide"></i> ${esc(dir)}`,
      tel && `<i data-lucide="phone" class="lucide"></i> ${esc(tel)}`,
      num && `<i data-lucide="message-circle" class="lucide"></i> WhatsApp: ${esc(num)}`,
    ].filter(Boolean).join("<br>") || "Datos de contacto no configurados todavía.";
  }
  // La tarjeta "Dirección" de la sección de taller: se llena o se oculta
  // entera (una tarjeta con título y sin contenido se ve rota).
  const td = document.getElementById("tallerDireccion");
  if(td){
    td.textContent = dir;
    const card = td.closest(".taller-info-item");
    if(card) card.style.display = dir ? "" : "none";
  }
  lucide.createIcons();
}
function mensajeCotizarMoto(m){
  return `Hola, me interesa la ${m.nombre} (${fmt(m.precio)}). ¿Me pueden dar más información?`;
}
/* Resumen detallado de una cotización de repuestos, dirigido al WhatsApp
   del almacén (no al del cliente). Se arma con los mismos items que ya
   quedaron guardados vía apiCrearCotizacion(), para que el asesor reciba
   exactamente lo mismo que quedó registrado en el sistema. */
function mensajeResumenCotizacion(numero, datosCliente, items){
  const lista = items.map((p, i) => `${i + 1}. ${p.nombre} - ${fmt(p.precio)}`).join("\n");
  const total = items.reduce((s, p) => s + p.precio, 0);
  return `Hola, les escribo por la cotización #${numero} que acabo de generar en la página:\n\n` +
    `*Cliente:* ${datosCliente.nombre}\n` +
    `*WhatsApp:* ${datosCliente.telefono}\n\n` +
    `*Productos:*\n${lista}\n\n` +
    `*Total:* ${fmt(total)}\n\n` +
    `¿Me confirman disponibilidad y cómo coordinamos el pago?`;
}
function mapMoto(m){
  return {id:m.id, nombre:m.nombre, marca:m.marca || "Honda", precio:parseFloat(m.precio),
          cilindraje:m.cilindraje || "", categoria:m.categoria || "",
          descripcion:m.descripcion || "", foto:m.foto || null, destacada:m.destacada};
}
const MOTOS_DEMO = [
  {id:1, nombre:"CB 160F DLX", marca:"Honda", precio:8990000, cilindraje:"162 cc", categoria:"naked",
   descripcion:"Naked deportiva de uso diario, motor de 162cc y panel digital.", foto:null, destacada:false},
  {id:2, nombre:"XR150L", marca:"Honda", precio:10990000, cilindraje:"150 cc", categoria:"enduro",
   descripcion:"Doble propósito robusta para ciudad y trocha.", foto:null, destacada:true},
  {id:3, nombre:"CB190R", marca:"Honda", precio:11990000, cilindraje:"184 cc", categoria:"naked",
   descripcion:"La naked más potente de la línea, frenos de disco en ambas ruedas.", foto:null, destacada:true},
];
async function apiMotos(){
  if(USAR_DEMO) return MOTOS_DEMO;
  try{
    const r = await fetch(`${API_URL}/api/motos/`);
    return (await r.json()).map(mapMoto);
  }catch(e){ console.error(e); return []; }
}

/* ================= ÍCONOS =================
   Dibuja los íconos Lucide presentes en el HTML estático (nav, hero, chips,
   taller, diferenciales, footer, cascarón del chat). Las funciones que
   agregan contenido dinámico (catálogo, motos, mensajes del bot) vuelven a
   llamar lucide.createIcons() después de renderizar, para que los íconos
   nuevos también se dibujen. */
lucide.createIcons();

/* ================= NAV MÓVIL ================= */
const burger = document.getElementById("burger");
const navLinks = document.getElementById("navLinks");
burger.onclick = () => navLinks.classList.toggle("open");
navLinks.querySelectorAll("a").forEach(a => a.addEventListener("click", () => navLinks.classList.remove("open")));

/* ================= SCROLL REVEAL ================= */
if("IntersectionObserver" in window){
  const io = new IntersectionObserver(entries => {
    entries.forEach(e => { if(e.isIntersecting){ e.target.classList.add("in-view"); io.unobserve(e.target); } });
  }, {threshold:.12});
  document.querySelectorAll(".reveal").forEach(el => io.observe(el));
}else{
  document.querySelectorAll(".reveal").forEach(el => el.classList.add("in-view"));
}

/* ================= CATÁLOGO EN LA PÁGINA ================= */
const grid = document.getElementById("gridCatalogo");
let CATALOGO = [];
function renderGrid(lista){
  grid.innerHTML = "";
  if(!lista.length){
    grid.innerHTML = `<div class="grid-cat-empty"><i data-lucide="search" class="lucide"></i> No encontramos repuestos para este filtro. Prueba con otro o pregúntale al asistente virtual.</div>`;
    lucide.createIcons();
    return;
  }
  lista.forEach(p=>{
    const c = document.createElement("div");
    c.className = "card";
    c.innerHTML = `
      <div class="card-img">
        ${p.foto ? `<span class="tag">${esc(p.modelo.split(",")[0])}</span>` : ""}
        ${p.stock>0 && p.stock<=4 ? `<span class="tag-stock">Últimas ${p.stock}</span>` : ""}
        ${p.stock<=0 ? `<span class="tag-stock" style="background:#6b7078"><i data-lucide="circle-x" class="lucide"></i> Agotado</span>` : ""}
        ${p.foto
          ? `<img src="${esc(p.foto)}" alt="${esc(p.nombre)}" loading="lazy" style="width:100%;height:100%;object-fit:cover">`
          : placaHtml(p)}
      </div>
      <div class="card-body">
        <h3 title="${esc(p.nombre)}">${esc(p.nombre)}</h3>
        <div class="ref">Ref: ${esc(p.ref)}</div>
        <div class="precio">${fmt(p.precio)}</div>
        <div class="stock">${p.stock>0 ? `<i data-lucide="check-circle" class="lucide"></i> ${p.stock} en stock` : `<span style="color:var(--rojo)"><i data-lucide="circle-x" class="lucide"></i> Agotado por ahora</span>`}</div>
        <button onclick="cotizarDesdePagina(${p.id})"><i data-lucide="message-circle" class="lucide"></i> Cotizar</button>
      </div>`;
    grid.appendChild(c);
  });
  lucide.createIcons();
}
async function pintarCatalogo(){
  CATALOGO = await apiCatalogo();
  renderGrid(CATALOGO);
}
async function filtrar(cat, btn){
  document.querySelectorAll("#chips .chip").forEach(c => c.classList.remove("active"));
  btn.classList.add("active");
  grid.innerHTML = `<div class="card-img" style="grid-column:1/-1;height:6px;border-radius:6px"></div>`;
  const lista = cat === "" ? await apiCatalogo() : await apiPorCategoria(cat);
  CATALOGO = lista.length || cat === "" ? lista : CATALOGO;
  renderGrid(lista);
}
pintarCatalogo();

/* ================= MOTOS EN LA PÁGINA ================= */
const gridMotos = document.getElementById("gridMotos");
function renderMotos(lista){
  gridMotos.innerHTML = "";
  if(!lista.length){
    gridMotos.innerHTML = `<div class="grid-cat-empty"><i data-lucide="bike" class="lucide"></i> Muy pronto vas a poder ver aquí el catálogo de motos nuevas. Mientras tanto, escríbenos por el chat.</div>`;
    lucide.createIcons();
    return;
  }
  const num = waAsesor();
  lista.forEach(m=>{
    const c = document.createElement("div");
    c.className = "moto-card";
    // Sin WhatsApp válido: en vez del botón, el canal alterno (o nada si Ana
    // tampoco cargó teléfono/dirección). Nunca un botón que va a la nada.
    const ctaWa = num
      ? `<a class="btn-wa" href="${linkWhatsApp(num, mensajeCotizarMoto(m))}" target="_blank" rel="noopener"><i data-lucide="message-circle" class="lucide"></i> Cotizar por WhatsApp</a>`
      : canalAlternoHtml();
    c.innerHTML = `
      <div class="moto-img">
        ${m.destacada ? `<span class="moto-destacada"><i data-lucide="star" class="lucide"></i> Destacada</span>` : ""}
        ${m.foto
          ? `<img src="${esc(m.foto)}" alt="${esc(m.nombre)}" loading="lazy">`
          : placaHtml(m)}
      </div>
      <div class="moto-body">
        <div class="moto-meta">
          ${m.cilindraje ? `<span class="moto-chip">${esc(m.cilindraje)}</span>` : ""}
          ${m.categoria ? `<span class="moto-chip">${esc(m.categoria)}</span>` : ""}
        </div>
        <h3>${esc(m.nombre)}</h3>
        <div class="moto-precio">${fmt(m.precio)}</div>
        ${m.descripcion ? `<p class="moto-desc" id="desc-${m.id}">${esc(m.descripcion)}</p>` : ""}
        <div class="moto-ctas">
          ${ctaWa}
          ${m.descripcion ? `<button class="btn-detalle" onclick="toggleDetalleMoto(${m.id})">Ver detalle</button>` : ""}
        </div>
      </div>`;
    gridMotos.appendChild(c);
  });
  lucide.createIcons();
}
function toggleDetalleMoto(id){
  const el = document.getElementById(`desc-${id}`);
  if(el) el.classList.toggle("open");
}
async function pintarMotos(){
  await configListo;
  renderMotos(await apiMotos());
}
pintarMotos();

/* ================= TALLER (informativo, ya no agenda citas) ================= */
async function pintarTallerWa(){
  await configListo;
  pintarContacto();   // pie de página + dirección de la sección de taller
  const a = document.getElementById("tallerWa");
  if(!a) return;
  const num = waAsesor();
  if(num){
    a.href = linkWhatsApp(num,
      "Hola, quiero información sobre el servicio de taller de SuperMotos La 4ta");
  }else{
    // Sin WhatsApp válido: la tarjeta-enlace pasa a mostrar el canal alterno,
    // o se oculta si Ana tampoco cargó teléfono/dirección.
    const alt = canalAlternoHtml();
    a.removeAttribute("href"); a.removeAttribute("target");
    if(alt){
      a.style.cursor = "default";
      a.querySelector("div").innerHTML = "<h4>¿Necesitas el taller?</h4>" + alt;
    }else{
      a.style.display = "none";
    }
    lucide.createIcons();
  }
}
pintarTallerWa();

/* ================= WIDGET ================= */
const panel = document.getElementById("panel");
const fabDot = document.getElementById("fabDot");
const chat = document.getElementById("chat");
const inp = document.getElementById("inp");
const statusEl = document.getElementById("status");
let cotizacion = [];      // items {producto, cantidad:1}
let saludado = false;
let captura = null;       // cuando el bot espera un dato escrito (nombre/teléfono)
let ultimosResultados = [];  // los productos del último buscar(): los botones
                             // "Agregar"/"Avísenme" de cada tarjeta del chat
                             // los buscan acá por id (ver agregarDesdeChat)

function toggleChat(){
  panel.classList.toggle("open");
  fabDot.style.display = "none";
  if(panel.classList.contains("open") && !saludado){
    saludado = true;
    setTimeout(saludo, 400);
  }
}
function abrirChat(){ if(!panel.classList.contains("open")) toggleChat(); }
function cotizarDesdePagina(id){
  const p = CATALOGO.find(x=>x.id===id);
  if(!p) return;
  abrirChat();
  const arranca = ()=>{ clearButtons(); userMsg("Quiero cotizar: "+p.nombre); setTimeout(()=>agregar(p), 400); };
  if(!saludado){ setTimeout(arranca, 1600); } else { arranca(); }
}

function horaTxt(){
  return new Date().toLocaleTimeString("es-CO",{hour:"numeric",minute:"2-digit",hour12:true}).toLowerCase();
}
function scrollChat(){ chat.scrollTop = chat.scrollHeight; }
function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;"); }

function userMsg(txt){
  const d = document.createElement("div");
  d.className = "msg out";
  d.innerHTML = esc(txt) + `<span class="meta">${horaTxt()} <span class="check"><i data-lucide="check-check" class="lucide"></i></span></span>`;
  chat.appendChild(d); scrollChat();
  lucide.createIcons();
}
function botMsg(html, delay=850){
  return new Promise(res=>{
    statusEl.textContent = "escribiendo…";
    const t = document.createElement("div");
    t.className = "typing";
    t.innerHTML = "<span></span><span></span><span></span>";
    chat.appendChild(t); scrollChat();
    setTimeout(()=>{
      t.remove();
      statusEl.textContent = "en línea";
      const d = document.createElement("div");
      d.className = "msg in";
      d.innerHTML = html + `<span class="meta">${horaTxt()}</span>`;
      chat.appendChild(d); scrollChat();
      lucide.createIcons();
      res();
    }, delay);
  });
}
function botButtons(opts){
  clearButtons();
  const g = document.createElement("div");
  g.className = "btn-group"; g.id = "activeBtns";
  const contenido = o => (o.icon ? `<i data-lucide="${o.icon}" class="lucide"${o.iconColor ? ` style="color:${o.iconColor}"` : ""}></i> ` : "") + esc(o.label);
  opts.forEach(o=>{
    if(o.href){
      // enlace real (ej. WhatsApp): la navegación debe ser directa desde el
      // click, no via setTimeout, o el navegador puede bloquearla como popup.
      const a = document.createElement("a");
      a.className = "qbtn"; a.innerHTML = contenido(o);
      a.href = o.href; a.target = "_blank"; a.rel = "noopener";
      a.onclick = ()=>{ userMsg(o.label); clearButtons(); };
      g.appendChild(a);
    }else{
      const b = document.createElement("button");
      b.className = "qbtn"; b.innerHTML = contenido(o);
      b.onclick = ()=>{ clearButtons(); userMsg(o.label); setTimeout(o.action, 350); };
      g.appendChild(b);
    }
  });
  chat.appendChild(g); scrollChat();
  lucide.createIcons();
}
function clearButtons(){
  const g = document.getElementById("activeBtns");
  if(g) g.remove();
}
function chatProdHtml(p, extra){
  const miniatura = p.foto
    ? `<img src="${esc(p.foto)}" loading="lazy" style="width:100%;height:100%;object-fit:cover;border-radius:9px">`
    : placaHtml(p);
  return `<div class="chat-prod">
    <div class="foto-tile">${miniatura}</div>
    <div class="info">${extra}</div>
  </div>`;
}

/* ================= FLUJOS DEL BOT ================= */
async function saludo(){
  await botMsg("¡Hola! 👋 Soy el asistente virtual de <b>SuperMotos La 4ta</b>.\nEscríbeme qué repuesto buscas y para qué moto, como si le hablaras a un vendedor. Por ejemplo:\n<i>«frenos para mi cb110»</i>\n<i>«necesito una bujía para wave»</i>\n<i>«cuánto vale el kit de arrastre cb190»</i>");
  await menu();
}
async function menu(){
  botButtons([
    {icon:"search", label:"Buscar un repuesto", action: iniciarBusquedaRepuesto},
    {icon:"receipt", label:"Ver mi cotización" + (cotizacion.length ? ` (${cotizacion.length})` : ""), action: verCotizacion},
    {icon:"user-round", label:"Hablar con un asesor", action: asesor},
  ]);
}
async function iniciarBusquedaRepuesto(){
  // Activa el flujo de búsqueda: el bot invita a escribir y deja el input
  // listo. La búsqueda misma la resuelve buscar(), disparada por procesar()
  // apenas el cliente escriba (ver ENTRADA LIBRE más abajo).
  await botMsg("<i data-lucide=\"search\" class=\"lucide\"></i> ¡Claro! Escríbeme el <b>repuesto y el modelo de tu moto</b>, por ejemplo:\n<i>«pastillas de freno cb160»</i>\n<i>«filtro de aire xr150»</i>\n<i>«bujía para wave»</i>");
  inp.focus();
}
async function buscar(q){
  const {items:res, fallback} = await apiBuscar(q);
  if(!res.length){
    await botMsg(`No encontré "<b>${esc(q)}</b>" en el inventario 😅.\nProbá con otras palabras (ej: <i>pastillas, filtro de aire, bujía, kit de arrastre</i>) o decime el modelo de tu moto.`);
    return menu();
  }
  const hayStock = res.some(p => p.stock > 0);
  let html = hayStock
    ? (fallback
        ? `<i data-lucide="search" class="lucide" style="color:var(--rojo)"></i> No encontré exactamente "<b>${esc(q)}</b>", pero tengo <b>${res.length}</b> parecido(s):`
        : `<i data-lucide="check-circle" class="lucide" style="color:var(--verde)"></i> Encontré <b>${res.length}</b> resultado(s):`)
    : (fallback
        ? `<i data-lucide="triangle-alert" class="lucide" style="color:var(--rojo)"></i> No encontré exactamente "<b>${esc(q)}</b>"; esto es lo más parecido, pero está agotado:`
        : `<i data-lucide="triangle-alert" class="lucide" style="color:var(--rojo)"></i> Encontré <b>${res.length}</b> resultado(s), pero por ahora están agotados:`);
  // Cada resultado mostrado lleva su propio botón, pegado a la tarjeta: así se
  // agrega con un toque el producto que el cliente está mirando, sin tener que
  // reescribir el nombre. Antes solo los 3 primeros tenían botón (abajo, con
  // el nombre cortado a 3 palabras -> etiquetas idénticas cuando compartían
  // prefijo). El agotado lleva "Avísenme", no "Agregar".
  ultimosResultados = res.slice(0, 4);
  ultimosResultados.forEach(p=>{
    const cta = p.stock > 0
      ? `<button class="prod-cta" data-add="${p.id}" onclick="agregarDesdeChat(${p.id})"><i data-lucide="plus" class="lucide"></i> Agregar</button>`
      : `<button class="prod-cta prod-cta--avisar" onclick="avisarmeDesdeChat(${p.id})"><i data-lucide="bell" class="lucide"></i> Avísenme</button>`;
    html += `<span class="divider"></span>` + chatProdHtml(p,
      `<b>${esc(p.nombre)}</b><br>Ref: ${esc(p.ref)}<br>Compatible: ${esc(p.modelo)}<br>Precio: <span class="price">${fmt(p.precio)}</span><br>` +
      (p.stock > 0 ? `Stock: ${p.stock} unidades <i data-lucide="check-circle" class="lucide" style="color:var(--verde)"></i>` : `<span style="color:var(--rojo);font-weight:600">Agotado por ahora <i data-lucide="circle-x" class="lucide"></i></span>`) +
      `<br>${cta}`);
  });
  await botMsg(html, 1100);
  botButtons([{icon:"arrow-left", label:"Accesos rápidos", action: menu}]);
}

/* Los botones "Agregar"/"Avísenme" van DENTRO del mensaje de resultados, así
   que no pueden usar el closure de botButtons(): se cablean con onclick
   inline y buscan el producto por id en ultimosResultados -- mismo patrón que
   cotizarDesdePagina(). Quedan en el historial del chat (clearButtons() no los
   toca), así "agregar el 3º" sigue disponible después de scrollear. */
function agregarDesdeChat(id){
  const p = ultimosResultados.find(x => x.id === id);
  if(!p) return;
  const b = document.querySelector(`button.prod-cta[data-add="${id}"]`);
  if(b && b.disabled) return;                 // ya se agregó: no duplicar
  if(b){
    b.disabled = true;
    b.classList.add("prod-cta--hecho");
    b.innerHTML = `<i data-lucide="check" class="lucide"></i> Agregado`;
    lucide.createIcons();
  }
  agregar(p);
}
function avisarmeDesdeChat(id){
  const p = ultimosResultados.find(x => x.id === id);
  if(!p) return;
  clearButtons();
  userMsg("Avísenme cuando llegue: " + p.nombre);
  setTimeout(()=>pedirContactoAgotado(p), 300);
}
/* Un producto agotado NO se agrega a la cotización (agregar() es para lo que
   sí se va a comprar ya); en vez de eso se captura el contacto para avisar
   cuando llegue, igual que pedirDatosPedido() pero guardando la solicitud
   con origen "web-agotado" para que Ana distinga un aviso de stock de un
   pedido real en el admin. */
async function pedirContactoAgotado(p){
  await botMsg(chatProdHtml(p,
    `<i data-lucide="bell" class="lucide"></i> Te aviso apenas llegue <b>${esc(p.nombre)}</b>. Escríbeme tu <b>nombre y número de WhatsApp</b> (ej: <i>Carlos Gómez 3001234567</i>)`));
  captura = (txt)=>confirmarAvisoStock(txt, p);
}
async function confirmarAvisoStock(txt, p){
  const d = extraerDatos(txt);
  if(!d.telefono){
    await botMsg("No logré identificar un número de WhatsApp válido 😅. Escríbeme tu nombre y un número de contacto, por favor.");
    captura = (t)=>confirmarAvisoStock(t, p);
    return;
  }
  try{
    await apiCrearCotizacion({
      nombre_cliente: d.nombre, telefono: d.telefono, origen: "web-agotado",
      items: [{producto_id:p.id, cantidad:1}],
    });
    await botMsg(`<i data-lucide="check-circle" class="lucide" style="color:var(--verde)"></i> ¡Listo, ${esc(d.nombre.split(" ")[0])}! Te contactamos al <b>${esc(d.telefono)}</b> apenas tengamos <b>${esc(p.nombre)}</b> disponible.`);
  }catch(e){
    await botMsg("Tuvimos un problema guardando tu solicitud 😔. Intenta de nuevo o escríbenos al WhatsApp del almacén.");
  }
  await menu();
}
async function agregar(p){
  cotizacion.push(p);
  await botMsg(chatProdHtml(p,
    `<i data-lucide="shopping-cart" class="lucide"></i> <b>${esc(p.nombre)}</b> agregado a tu cotización.<br>Llevas <b>${cotizacion.length}</b> producto(s) — Subtotal: <span class="price">${fmt(cotizacion.reduce((s,x)=>s+x.precio,0))}</span>`));
  botButtons([
    {icon:"receipt", label:"Ver cotización completa", action: verCotizacion},
    {icon:"arrow-left", label:"Accesos rápidos", action: menu},
  ]);
}
async function verCotizacion(){
  if(!cotizacion.length){
    await botMsg("<i data-lucide=\"receipt\" class=\"lucide\"></i> Tu cotización está vacía por ahora.\nEscríbeme qué repuesto buscas y te ayudo enseguida.");
    return menu();
  }
  let total = 0;
  let html = "<i data-lucide=\"receipt\" class=\"lucide\"></i> <b>TU COTIZACIÓN</b>\nSuperMotos La 4ta — Popayán<span class=\"divider\"></span>";
  cotizacion.forEach((p)=>{
    total += p.precio;
    html += chatProdHtml(p, `${esc(p.nombre)}<br><span class="price">${fmt(p.precio)}</span>`);
  });
  html += `<span class="divider"></span><i data-lucide="wallet" class="lucide"></i> <b>TOTAL: <span class="price">${fmt(total)}</span></b>\n<i>Precios válidos por 3 días. No incluye envío.</i>`;
  await botMsg(html, 1200);
  botButtons([
    {icon:"check-circle", label:"Confirmar pedido", action: pedirDatosPedido},
    {icon:"trash-2", label:"Vaciar cotización", action: vaciar},
    {icon:"arrow-left", label:"Menú principal", action: menu},
  ]);
}
async function pedirDatosPedido(){
  await botMsg("¡Perfecto! Para confirmar tu pedido, escríbeme tu <b>nombre y número de WhatsApp</b> (ej: <i>Carlos Gómez 3001234567</i>) <i data-lucide=\"message-circle\" class=\"lucide\"></i>");
  captura = confirmarPedidoConDatos;
}
/* Validación estricta del número de WhatsApp: solo dígitos, sin espacios
   vacíos ni caracteres inválidos, y con una longitud plausible para un
   número real (7 a 15 dígitos, rango general de la norma E.164). Si no
   cumple, se descarta (string vacío) y el flujo vuelve a pedirlo. */
function validarWhatsApp(numero){
  const limpio = String(numero || "").replace(/\D/g, "");
  return (limpio.length >= 7 && limpio.length <= 15) ? limpio : "";
}
function extraerDatos(txt){
  const coincidencia = (txt.match(/\d[\d\s\-]{6,}/) || [""])[0];
  const telefono = validarWhatsApp(coincidencia);
  const nombre = txt.replace(/\d[\d\s\-]{6,}/, "").replace(/[,;]/g, " ").replace(/\s+/g, " ").trim();
  return {nombre: nombre || "Cliente web", telefono};
}
async function confirmarPedidoConDatos(txt){
  const d = extraerDatos(txt);
  if(!d.telefono){
    await botMsg("No logré identificar un número de WhatsApp válido 😅. Escríbeme tu nombre y un número de contacto (solo números, sin espacios raros), por favor.");
    captura = confirmarPedidoConDatos;
    return;
  }
  const itemsCotizados = [...cotizacion];
  try{
    const r = await apiCrearCotizacion({
      nombre_cliente: d.nombre, telefono: d.telefono, origen: "web",
      items: itemsCotizados.map(p=>({producto_id:p.id, cantidad:1})),
    });
    const numero = String(r.id || 42).padStart(4, "0");
    await botMsg(`🎉 ¡Pedido registrado, ${esc(d.nombre.split(" ")[0])}!\nCotización <b>#${numero}</b> guardada.\nUn asesor te contactará al <b>${esc(d.telefono)}</b> para coordinar pago y entrega. 🛵💨`);
    cotizacion = [];
    await configListo;
    const num = waAsesor();
    const botones = [];
    if(num){
      botones.push({icon:"message-circle", iconColor:"var(--verde-wa)", label:"Enviar resumen por WhatsApp",
        href: linkWhatsApp(num, mensajeResumenCotizacion(numero, d, itemsCotizados))});
    }
    botones.push({icon:"user-round", label:"Hablar con un asesor", action: asesor});
    botButtons(botones);
  }catch(e){
    await botMsg("Tuvimos un problema guardando el pedido 😔. Intenta de nuevo en un momento o escríbenos al WhatsApp del almacén.");
    cotizacion = [];
    await menu();
  }
}
async function vaciar(){
  cotizacion = [];
  await botMsg("<i data-lucide=\"trash-2\" class=\"lucide\"></i> Listo, tu cotización quedó vacía.");
  await menu();
}
async function asesor(){
  await configListo;
  const num = waAsesor();
  const intro = num
    ? "También puedes escribirle directo por WhatsApp. 😉"
    : "Déjanos tus datos por el chat y te contactamos.";
  await botMsg(`<i data-lucide="user-round" class="lucide"></i> Te conecto con uno de nuestros asesores.\n<i data-lucide="clock" class="lucide"></i> Tiempo estimado de respuesta: <b>5 minutos</b> (L-S, 8am a 6pm).\n\n${intro}`);
  const botones = [];
  if(num){
    botones.push({icon:"message-circle", iconColor:"var(--verde-wa)", label:"Abrir WhatsApp",
      href: linkWhatsApp(num, "Hola, vengo de la página web y necesito ayuda")});
  }else{
    const alt = canalAlternoHtml();
    if(alt) await botMsg(`<i data-lucide="phone" class="lucide"></i> Por ahora el WhatsApp no está disponible. Puedes contactarnos así:${alt}`);
  }
  botones.push({icon:"receipt", label:"Ver mi cotización" + (cotizacion.length ? ` (${cotizacion.length})` : ""), action: verCotizacion});
  botButtons(botones);
}

/* ================= ENTRADA LIBRE (bot conversacional) =================
   El cliente escribe libre ("frenos para mi cb110", "cuanto vale el kit
   de arrastre cb190") y por defecto se busca en el backend, que ya
   interpreta pieza + modelo (tienda/busqueda.py). Antes de buscar se
   detectan unas pocas intenciones explícitas (saludo, cotización, asesor)
   para no mandar esas frases como si fueran nombre de repuesto. El bot NO
   agenda nada (ver sección "Taller" de la web, es informativa): si el
   cliente pregunta por cita/taller se lo pasa directo a un asesor.*/
async function procesar(txt){
  if(captura){ const fn = captura; captura = null; return fn(txt); }
  const t = txt.toLowerCase().trim();
  if(/^(hola|buenas|buenos dias|buenas tardes|buenas noches|menu|menú|inicio)\b/.test(t)) return saludo();
  if(/\b(cotizaci[oó]n|cotizar|carrito|mi pedido)\b/.test(t)) return verCotizacion();
  if(/\b(cita|agendar|agenda|taller)\b/.test(t)) return asesor();
  if(/\b(asesor|humano|persona real|hablar con alguien)\b/.test(t)) return asesor();
  if(/^gracias/.test(t)){
    await botMsg("¡Con mucho gusto! 🙌 Sigo aquí si necesitas algo más.");
    return menu();
  }
  return buscar(txt);
}
function enviar(){
  const v = inp.value.trim();
  if(!v) return;
  inp.value = "";
  clearButtons();
  userMsg(v);
  setTimeout(()=>procesar(v), 400);
}
document.getElementById("sendBtn").onclick = enviar;
inp.addEventListener("keydown", e=>{ if(e.key==="Enter") enviar(); });
