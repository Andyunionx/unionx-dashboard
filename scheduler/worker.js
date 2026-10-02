/**
 * UnionX — Scheduler confiable de los pulsos (Cloudflare Worker "patient-cloud-327e").
 *
 * Reemplaza al cron de GitHub Actions (se atrasa horas o se salta corridas). Cada cron
 * de Cloudflare hace workflow_dispatch de un workflow en GitHub. El Worker es tonto a
 * propósito: solo dispara; la lógica (ventana horaria del correo, validaciones) vive en
 * cada workflow.
 *
 * Triggers (Settings → Triggers → Cron Triggers del Worker):
 *   "30 11 * * 1-5"  → Pulso Diario (email_diario.yml), L-V 08:30 CLT en horario de verano (UTC−3) / 07:30 en invierno (UTC−4)
 *   "0 * * * *"      → Cyber Pulso (cyber_pulso.yml), cada hora, SOLO dentro de la ventana CYBER
 *
 * Secrets: GH_TOKEN (PAT fine-grained, Actions: Read & Write sobre el repo), TRIGGER_KEY (opcional).
 * Vars: GH_OWNER, GH_REPO, GH_WORKFLOW (el del pulso diario), GH_REF.
 */
// Cyber octubre 2026: lun 5-oct 06:00 CLT → lun 12-oct 06:00 CLT (CLT = UTC−3 en octubre).
// Fuera de esta ventana el cron horario no hace nada. Para el próximo Cyber, cambiar solo estas fechas.
const CYBER = { desde: '2026-10-05T09:00:00Z', hasta: '2026-10-12T09:00:00Z', workflow: 'cyber_pulso.yml' };
const CRON_HORARIO = '0 * * * *';

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
      'User-Agent': 'unionx-pulso-scheduler',
    },
    body: JSON.stringify({ ref }),
  });
  if (!resp.ok) {
    const txt = await resp.text();
    console.log(`[scheduler] DISPATCH ${workflow} FALLÓ ${resp.status}: ${txt.slice(0, 300)}`);
    throw new Error(`dispatch ${workflow} ${resp.status}`);
  }
  console.log(`[scheduler] ${workflow} disparado OK @ ${new Date().toISOString()}`);
}

function enCyber(ms) {
  return ms >= Date.parse(CYBER.desde) && ms < Date.parse(CYBER.hasta);
}

export default {
  async scheduled(event, env, ctx) {
    if (event.cron === CRON_HORARIO) {
      if (!enCyber(Date.now())) {
        console.log('[scheduler] cron horario fuera del Cyber: no dispara');
        return;
      }
      await dispatch(env, CYBER.workflow);
      return;
    }
    // cualquier otro cron (el de las 11:30 UTC L-V) = Pulso Diario
    await dispatch(env, env.GH_WORKFLOW || 'email_diario.yml');
  },

  // Manual: GET /trigger?k=<TRIGGER_KEY>[&wf=cyber]
  async fetch(request, env, ctx) {
    const u = new URL(request.url);
    if (u.pathname === '/trigger') {
      if (!env.TRIGGER_KEY || u.searchParams.get('k') !== env.TRIGGER_KEY) {
        return new Response('no autorizado', { status: 401 });
      }
      const wf = u.searchParams.get('wf') === 'cyber' ? CYBER.workflow : (env.GH_WORKFLOW || 'email_diario.yml');
      await dispatch(env, wf);
      return new Response(`${wf} disparado`, { status: 200 });
    }
    return new Response('unionx pulso scheduler OK', { status: 200 });
  },
};
