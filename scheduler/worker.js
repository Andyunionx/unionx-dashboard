/**
 * UnionX — Scheduler confiable (Cloudflare Worker «patient-cloud-327e»).
 *
 * El cron de GitHub Actions (plan gratis) atrasa horas o bota corridas. Este Worker usa el cron de
 * Cloudflare (puntual) y solo hace workflow_dispatch en GitHub; toda la lógica vive en cada workflow.
 *
 * CÓMO SE INSTALA: el Worker en producción se administra desde el panel de Cloudflare, NO con wrangler.
 * Edit code → pegar este archivo → Deploy; después Settings → Triggers → Cron Triggers. NO usar
 * `wrangler deploy` desde esta carpeta: el wrangler.toml tiene otro nombre de Worker y crearía uno nuevo
 * con el cron del Pulso Diario (correo duplicado a todos sus destinatarios).
 *
 * Triggers (Settings → Triggers → Cron Triggers), todos en UTC:
 *   30 11 * * MON-FRI  → Pulso Diario. Usa la variable GH_WORKFLOW (hoy email_diario.yml). SIN CAMBIOS.
 *   52 10 * * *        → Pulso Alarmas Odoo (vigía), todos los días: 07:52 de Chile en horario de verano.
 *   10 * * * *         → agentes, a la hora y 10 (diseño del 12-nov-2026):
 *                          · agente_tickets_nc.yml  lun-sáb, 11-23 UTC
 *                          · agente_factura_ml.yml  lun-vie, 12-21 UTC
 * Qué disparar se decide por el MINUTO de la ejecución (:30 = pulso, :52 = vigía, :10 = agentes), no por el
 * texto del cron, para que no importe cómo lo escriba el panel. Un minuto que no está en la lista NO dispara
 * nada: antes cualquier cron desconocido caía en el Pulso Diario, y agregar un trigger nuevo lo habría mandado
 * de nuevo a todos. Cada bloque queda inerte mientras su trigger no exista en el panel.
 *
 * Secret: GH_TOKEN (PAT fine-grained, Actions: Read & Write sobre el repo). Vars: GH_OWNER, GH_REPO,
 * GH_WORKFLOW, GH_REF. Endpoint manual: GET /trigger?k=<TRIGGER_KEY> dispara el pulso.
 */
const MINUTO_PULSO = 30;
const MINUTO_VIGIA = 52;
const MINUTO_AGENTES = 10;
const VIGIA = 'pulso_alarmas_odoo.yml';
const AGENTES = [
  { workflow: 'agente_tickets_nc.yml', dias: [1, 2, 3, 4, 5, 6], desde: 11, hasta: 23 },
  { workflow: 'agente_factura_ml.yml', dias: [1, 2, 3, 4, 5], desde: 12, hasta: 21 },
];

async function dispatch(env, workflow) {
  const owner = env.GH_OWNER || 'Andyunionx';
  const repo = env.GH_REPO || 'unionx-dashboard';
  const ref = env.GH_REF || 'main';
  const url = `https://api.github.com/repos/${owner}/${repo}/actions/workflows/${workflow}/dispatches`;
  const resp = await fetch(url, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${env.GH_TOKEN}`,
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'unionx-scheduler',
    },
    // Sin inputs: cada workflow decide con sus valores por defecto.
    body: JSON.stringify({ ref }),
  });
  if (!resp.ok) {
    const txt = await resp.text();
    // 422 suele ser ref/branch inválido; 401/403 token; 404 repo/workflow.
    console.log(`[scheduler] ${workflow}: DISPATCH FALLÓ ${resp.status}: ${txt.slice(0, 300)}`);
    return false;
  }
  console.log(`[scheduler] ${workflow}: disparado OK @ ${new Date().toISOString()}`);
  return true;
}

// Qué workflows corresponden a una ejecución programada, según su minuto (y día/hora para los agentes).
function workflowsPara(t, env) {
  const minuto = t.getUTCMinutes();
  if (minuto === MINUTO_PULSO) {
    return [env.GH_WORKFLOW || 'email_diario.yml'];
  }
  if (minuto === MINUTO_VIGIA) {
    return [VIGIA];
  }
  if (minuto === MINUTO_AGENTES) {
    const dia = t.getUTCDay();      // 0 = domingo … 6 = sábado
    const hora = t.getUTCHours();
    return AGENTES.filter(a => a.dias.includes(dia) && hora >= a.desde && hora <= a.hasta).map(a => a.workflow);
  }
  return [];
}

export default {
  async scheduled(event, env, ctx) {
    const t = new Date(event.scheduledTime || Date.now());
    const workflows = workflowsPara(t, env);
    if (!workflows.length) {
      console.log(`[scheduler] ${t.toISOString()}: nada que disparar a esta hora (cron ${event.cron})`);
      return;
    }
    const resultados = await Promise.all(workflows.map(w => dispatch(env, w)));
    if (resultados.includes(false)) {
      throw new Error('algún dispatch falló (ver logs)');
    }
  },

  // GET /trigger?k=<TRIGGER_KEY> dispara el pulso a mano. Sin TRIGGER_KEY configurada, el endpoint queda
  // cerrado (la URL de workers.dev es pública y los bots la escanean).
  async fetch(request, env, ctx) {
    const u = new URL(request.url);
    if (u.pathname === '/trigger') {
      if (!env.TRIGGER_KEY || u.searchParams.get('k') !== env.TRIGGER_KEY) {
        return new Response('no autorizado', { status: 401 });
      }
      const ok = await dispatch(env, env.GH_WORKFLOW || 'email_diario.yml');
      return new Response(ok ? 'pulso disparado' : 'dispatch falló', { status: ok ? 200 : 502 });
    }
    return new Response('unionx scheduler OK', { status: 200 });
  },
};
