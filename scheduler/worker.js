/**
 * UnionX — Scheduler confiable del pulso (Cloudflare Worker).
 *
 * Reemplaza al cron de GitHub Actions (que dropea runs) por un cron de Cloudflare
 * (confiable). Cada vez que dispara, hace workflow_dispatch del pulso en GitHub.
 *
 * El Worker es deliberadamente TONTO: solo dispara. Toda la lógica vive en el
 * workflow (cyber_pulso.yml): _check_rango (fechas), ventana de email 08:00-24:00
 * (horas pares), Gate 1/Gate 2 de validación. Así esto es fácil de mantener.
 *
 * Secrets requeridos (wrangler secret put):
 *   GH_TOKEN  — PAT fine-grained con permiso Actions: Read & Write sobre el repo.
 *
 * Vars (wrangler.toml [vars]):
 *   GH_OWNER, GH_REPO, GH_WORKFLOW, GH_REF
 */
export default {
  async scheduled(event, env, ctx) {
    const owner = env.GH_OWNER || 'Andyunionx';
    const repo = env.GH_REPO || 'unionx-dashboard';
    const workflow = env.GH_WORKFLOW || 'cyber_pulso.yml';
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
      // Sin inputs → preborrador=false (los 4 destinatarios), force_email=false
      // (la ventana horaria del workflow decide si manda email o solo refresca).
      body: JSON.stringify({ ref }),
    });

    if (!resp.ok) {
      const txt = await resp.text();
      console.log(`[pulso-scheduler] DISPATCH FALLÓ ${resp.status}: ${txt.slice(0, 300)}`);
      // 422 suele ser ref/branch inválido; 401/403 token; 404 repo/workflow.
      throw new Error(`dispatch ${resp.status}`);
    }
    console.log(`[pulso-scheduler] pulso disparado OK @ ${new Date().toISOString()} (cron ${event.cron})`);
  },

  // Endpoint manual opcional: GET /trigger dispara el pulso a mano (para pruebas).
  async fetch(request, env, ctx) {
    const u = new URL(request.url);
    if (u.pathname === '/trigger') {
      await this.scheduled({ cron: 'manual' }, env, ctx);
      return new Response('pulso disparado', { status: 200 });
    }
    return new Response('unionx pulso scheduler OK', { status: 200 });
  },
};
