# Registering Vantage Widgets in ThingsBoard

## Step 1 — Create widget bundle

1. Log into ThingsBoard as Tenant Admin
2. **Widget Library** → **+** → **Create new widget bundle**
3. Name: `Vantage NMS AI`
4. Save

## Step 2 — Add Vantage Chat widget

1. Open the `Vantage NMS AI` bundle → **+ Add widget type**
2. Select **Latest values** widget type
3. Set title: `Vantage Chat`
4. Switch to the **HTML** tab — paste the full contents of `vantage_chat.html`
5. Switch to **Settings schema** tab — add this JSON schema:
   ```json
   {
     "schema": {
       "type": "object",
       "title": "Vantage Chat Settings",
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

## Step 3 — Add Vantage WorkOrders widget

1. Same bundle → **+ Add widget type**
2. Select **Latest values** widget type
3. Set title: `Vantage WorkOrders`
4. HTML tab — paste full contents of `vantage_workorders.html`
5. Settings schema tab — same schema as above
6. Save

## Step 4 — Add widgets to a device dashboard

1. Open any device dashboard → **Edit** mode
2. **+ Add widget** → `Vantage NMS AI` bundle
3. For **Vantage Chat**:
   - Add at least one telemetry key as datasource (e.g. `temperature`)
   - In **Widget settings**: set `FASTAPI_URL` to `http://<your-server>:8000`
4. For **Vantage WorkOrders**:
   - Datasource: the same device (no keys required — entity_id is all that matters)
   - Widget settings: same `FASTAPI_URL`
5. Save dashboard

## Verification checklist

- [ ] Vantage Chat: device name appears in header, telemetry pills populate
- [ ] Vantage Chat: type a question, hit Ctrl+Enter → SSE response streams
- [ ] Vantage Chat: LLM includes `work_order` block → green card appears below response
- [ ] Vantage WorkOrders: open work orders appear within 2 seconds of page load
- [ ] Vantage WorkOrders: changing status via dropdown → PATCH updates, card disappears/changes
- [ ] Both widgets: `FASTAPI_URL` is configurable per widget instance (not hardcoded)
- [ ] Both widgets: render correctly on tablet viewport (ThingsBoard responsive layout)
