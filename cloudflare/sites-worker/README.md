# opsra-sites Worker

Serves every published client site from the R2 bucket `opsra-sites`. The visitor's domain
(without a leading `www.`) is the folder: `shop.com.ng/index.html`, `shop.com.ng/images/hero.jpg`.
The backend fills the bucket (`POST /sites/{id}/publish`, `app/services/site_publish_service.py`).

## Deploy (from your computer)
Run `SITES-WORKER_deploy.bat` (first time it opens a browser to log in to Cloudflare).

## After the first deploy
1. Cloudflare dashboard -> Workers & Pages -> `opsra-sites` -> Settings -> Domains & Routes ->
   add the custom domain `sites.coreaicloudtech.com.ng` (this is the main address clients point at).
2. Per client domain: add it as a custom hostname (Cloudflare for SaaS) or a route. That step is
   built later; until then each domain needs its own route/custom domain on this Worker.

## Behaviour
- GET/HEAD only (others get 405).
- `/` and `/folder/` serve `index.html`.
- Missing file: the site's own `404.html` if it has one, otherwise plain "Not found".
- Honors `If-None-Match` (304) and sends `X-Content-Type-Options: nosniff`.
- Cache headers come from what the backend stored (pages 60 s, images 1 h).

## Tests
`npm test` (Node 20+, no dependencies).

## Standby copy (SITE-STANDBY)
`wrangler.backup.toml` deploys the same code as `opsra-sites-standby` in the BACKUP Cloudflare account. It
serves `live/<domain>/` from the backup bucket (`SITE_PREFIX = "live/"`). The folder is filled on demand by
the Celery task `app.workers.site_worker.prepare_backup_host` (Render Shell on opsra-celery-worker):

    python -c "from app.workers.site_worker import prepare_backup_host as p; print(p('shop.com.ng'))"
    python -c "from app.workers.site_worker import prepare_backup_host as p; print(p())"   # every backed-up site

It reads only the backup bucket. Pointing a domain at the standby (DNS) is manual.
