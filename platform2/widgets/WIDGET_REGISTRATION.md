# Registering NavNet Widgets in the NavNet Dashboard

## Step 1 — Create widget bundle

1. Log into NavNet as Tenant Admin
2. **Widget Library** → **+** → **Create new widget bundle**
3. Name: `NavNet AI`
4. Save

## Step 2 — Add NavNet Chat widget

1. Open the `NavNet AI` bundle → **+ Add widget type**
2. Select **Latest values** widget type
3. Set title: `NavNet Chat`
4. Switch to the **HTML** tab — paste the full contents of `navnet_chat.html`
5. Switch to **Settings schema** tab — add this JSON schema:
   ```json
   {
     "schema": {
       "type": "object",
       "title": "NavNet Chat Settings",
       "properties": {
         "FASTAPI_URL": {
           "title": "AI Services URL",
           "type": "string",
           "default": "http://localhost:8000"
         }
       },
       "required": ["FASTAPI_URL"]
     },
     "form": ["FASTAPI_URL"]
   }
   ```
6. Save

## Step 3 — Add NavNet WorkOrders widget

1. Same bundle → **+ Add widget type**
2. Select **Latest values** widget type
3. Set title: `NavNet WorkOrders`
4. HTML tab — paste full contents of `navnet_workorders.html`
5. Settings schema tab — same schema as above
6. Save

## Step 4 — Add widgets to a device dashboard

1. Open any device dashboard → **Edit** mode
2. **+ Add widget** → `NavNet AI` bundle
3. For **NavNet Chat**:
   - Add at least one telemetry key as datasource (e.g. `temperature`)
   - In **Widget settings**: set `FASTAPI_URL` to `http://<your-server>:8000`
4. For **NavNet WorkOrders**:
   - Datasource: the same device (no keys required — entity_id is all that matters)
   - Widget settings: same `FASTAPI_URL`
5. Save dashboard

## Verification checklist

- [ ] NavNet Chat: device name appears in header, telemetry pills populate
- [ ] NavNet Chat: type a question, hit Ctrl+Enter → SSE response streams
- [ ] NavNet Chat: LLM includes `work_order` block → green card appears below response
- [ ] NavNet WorkOrders: open work orders appear within 2 seconds of page load
- [ ] NavNet WorkOrders: changing status via dropdown → PATCH updates, card disappears/changes
- [ ] Both widgets: `FASTAPI_URL` is configurable per widget instance (not hardcoded)
- [ ] Both widgets: render correctly on tablet viewport (NavNet responsive layout)
