# Screenshots of the user guide

The images of the user guide (`services/webapp/ng/src/assets/guide/img`) are taken from a local stack, by going through a whole task with **fictitious** copies. Never point these scripts at real student data: the guide is public.

| Script | Does |
|--------|------|
| `make_demo_data.py` | draws 8 copies on the default templates (invented names, matricules `2999xxx`, a handwriting font), the Moodle zip and grading worksheet of the class, and `page-de-garde.png` |
| `capture.mjs` | logs in, creates a template, creates the task, confirms the matricules, grades every copy, finalises, and saves the PNG screenshots plus the frames of the animations |
| `frames_to_gif.py` | turns the frames into the GIFs of the guide, and strings a few of them into `parcours.gif` |

## Requirements

- the local stack (`docker compose up -d`). To leave a running stack alone, start a second one under another project name, with no host port except nginx on another one, and its own Mongo volume:

  ```yaml
  # compose.guide.yml
  services:
    redis: {ports: !reset []}
    mongo: {ports: !reset []}
    webapp: {ports: !reset []}
    nginx:
      ports: !override ["127.0.0.1:8090:80"]
  volumes:
    mongo-data: {name: rmn-guide-mongo-data}
  ```

  `docker compose -p rmn-guide -f docker-compose.yml -f compose.guide.yml up -d --build`
- Python with PyMuPDF and Pillow (`pip install -r requirements.txt`);
- Node 26: `npm ci && npx playwright install chromium`.

## Regenerate the images

```sh
# a demo account with the default templates (ADMIN_API_KEY is in .env)
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" --form username=prof.demo@exemple.invalid \
  --form password=<password> --form role=Administrateur http://127.0.0.1:8090/api/admin/signup
curl -X POST -H "X-Admin-Key: $ADMIN_API_KEY" --form user_id=prof.demo@exemple.invalid \
  http://127.0.0.1:8090/api/admin/template

IMG=../../services/webapp/ng/src/assets/guide/img
python make_demo_data.py --out demo --img-dir $IMG
RMN_URL=http://127.0.0.1:8090 RMN_PASSWORD=<password> node capture.mjs
python frames_to_gif.py --out $IMG
```

`capture.mjs` reads `RMN_URL`, `RMN_USER` (default `prof.demo@exemple.invalid`), `RMN_PASSWORD`, `DEMO_DIR`, `IMG_DIR` and `STEPS` (default `template,task,matricules,grading,finalize`, to redo only part of the run on an existing task). It expects an account with no task named « Démo MTH1102 Final »: start from an empty database. On a failure it saves `frames/error.png`.

The handwriting font (Caveat, SIL Open Font License) is downloaded into `.cache/` on first use. `demo/`, `frames/`, `.cache/` and `node_modules/` are not committed.

The screenshots of Moodle itself are not automated: the chapters of the guide mark with a `TODO capture` comment where one is expected.
