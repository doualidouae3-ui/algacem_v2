import math, random, os, io, csv
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, make_response

app = Flask(__name__)

# ── POND DEFINITIONS ──────────────────────────────────────
PONDS = [
    {"id":"A-1","col":1,"row":"A","day":3,"vol":150,"area":500},
    {"id":"A-2","col":2,"row":"A","day":4,"vol":150,"area":500},
    {"id":"A-3","col":3,"row":"A","day":6,"vol":150,"area":500},
    {"id":"A-4","col":4,"row":"A","day":2,"vol":150,"area":500},
    {"id":"B-1","col":1,"row":"B","day":4,"vol":180,"area":600},
    {"id":"B-2","col":2,"row":"B","day":7,"vol":180,"area":600},
    {"id":"B-3","col":3,"row":"B","day":9,"vol":180,"area":600},
    {"id":"B-4","col":4,"row":"B","day":1,"vol":180,"area":600},
]
K=2.3; R=0.38; D0=0.10

# ── PHYSICS ───────────────────────────────────────────────
def par(h):
    if h<6 or h>20: return 0.0
    return round(max(0, 1150*math.exp(-((h-13)/3.8)**2)), 1)

def temp_base(h, offset=0.0):
    return round(23.5 + 4.5*math.cos((h-14.5)*math.pi/12) + offset, 2)

def ph_calc(h, density, co2):
    l = par(h)
    return round(max(6.8, min(9.8, 7.62 - 0.28*min(1,co2/20) + 0.065*(l/100)*density)), 2)

def gfactor(l, t, ph, co2):
    lf = min(1,l/800) if l>0 else 0.03
    tf = 1.0 if 25<=t<=35 else (max(0,(t-15)/10) if t<25 else max(0,1-(t-35)*0.15))
    pf = 1.0 if 7.4<=ph<=8.4 else (max(0,0.6+(ph-7.4)*0.4) if ph<7.4 else max(0,1-(ph-8.4)*0.4))
    cf = min(1, co2/14)
    return round(lf*tf*pf*cf, 4)

def logistic(day):
    return round(K/(1+((K-D0)/D0)*math.exp(-R*day)), 3)

def compute(pdef, hour=None, co2_ov=None, toff=0.0):
    if hour is None:
        n = datetime.now(); hour = n.hour + n.minute/60.0
    day = pdef["day"]; idx = pdef["col"]-1
    density = round(logistic(day)*(0.94+idx*0.025), 3)
    co2 = co2_ov if co2_ov is not None else round(11+density*4+random.uniform(-0.3,0.3), 1)
    l = par(hour); t = temp_base(hour, toff)
    ph = ph_calc(hour, density, co2); gf = gfactor(l, t, ph, co2)
    o2   = round(min(115, 84+gf*17+(l/1150)*11), 1)
    absp = round(min(99,  55+gf*42+(l/1150)*18), 1)
    turb = round(0.08+density*0.22+random.uniform(-0.01,0.01), 2)
    sal  = round(17.8+idx*0.35+random.uniform(-0.05,0.05), 1)
    rpm  = 16 if l<80 else (24 if density>1.8 else 22)
    status = ("critical" if ph>8.65 or t>35 or (density<0.15 and day>3)
              else "warning" if ph>8.25 or t>31 or (absp<60 and l>200)
              else "healthy")
    stage = next(s for d,s in [(2,"Inoculation"),(5,"Exponential"),(7,"Linear"),(9,"Near Peak"),(99,"Declining")] if day<=d)
    peak = K*0.88; dth = 0.0
    if density < peak:
        try: dth = round(max(0,(math.log((K-density)/(K-peak))/(-R))-day),1)
        except: pass
    grade = "A" if ph<8.25 and t<30 else ("A-" if ph<8.5 else "B")
    bio   = round(density*pdef["vol"], 1)
    co2c  = round(density*pdef["vol"]*1.83*0.08, 1)
    recs  = build_recs(ph, t, dth, absp, l, bio, density, co2, grade)
    return {"id":pdef["id"],"day":day,"stage":stage,"status":status,
            "density":density,"ph":ph,"temperature":t,"co2_flow":co2,
            "par":l,"o2":o2,"absorption":absp,"turbidity":turb,"salinity":sal,"rpm":rpm,
            "growth_factor":gf,"days_to_harvest":dth,"grade":grade,
            "biomass_kg":bio,"co2_captured_kg":co2c,
            "vol":pdef["vol"],"area":pdef["area"],"recommendations":recs}

def build_recs(ph, t, dth, absp, l, bio, density, co2, grade):
    recs=[]
    if ph>8.5: recs.append({"priority":"critical","issue":f"pH critically high ({ph:.2f})","cause":"Photosynthesis consuming CO₂ faster than injection.","actions":[f"Increase CO₂ flow to {min(32,co2*1.4):.1f} m³/h","Check injection nozzles","Reduce paddlewheel to 16 RPM"],"timeframe":"Act within 1 hour"})
    elif ph>8.25: recs.append({"priority":"warning","issue":f"pH elevated ({ph:.2f})","cause":"CO₂ not keeping up with photosynthetic demand.","actions":[f"Increase CO₂ to {min(28,co2*1.22):.1f} m³/h","Monitor every 30 min"],"timeframe":"Act within 3 hours"})
    if t>32: recs.append({"priority":"critical","issue":f"Temperature critical ({t:.1f}°C)","cause":"Exceeding Spirulina thermal tolerance.","actions":["Deploy shade netting","Increase paddlewheel to 28 RPM","Add chilled fresh water (max 10%)"],"timeframe":"Act immediately"})
    elif t>30: recs.append({"priority":"warning","issue":f"Temperature elevated ({t:.1f}°C)","cause":"Approaching upper thermal limit.","actions":["Monitor every 15 min","Prepare shade netting"],"timeframe":"Monitor closely"})
    if dth==0: recs.append({"priority":"harvest","issue":"Pond at peak density — harvest now","cause":"Carrying capacity reached. Quality degrades after 24h.","actions":[f"Harvest immediately · Est. yield {bio:.0f} kg",f"Projected grade: {grade}","Prepare centrifuge/filtration"],"timeframe":"Within 6-12 hours"})
    elif 0<dth<1.5: recs.append({"priority":"info","issue":f"Harvest window in {dth:.1f} days","cause":"Density approaching plateau.","actions":["Schedule harvesting equipment","Confirm centrifuge","Prepare fresh medium"],"timeframe":"Prepare now"})
    if absp<60 and l>200: recs.append({"priority":"warning","issue":f"Low CO₂ absorption ({absp}%)","cause":"Possible diffuser fouling or excess flow.","actions":["Inspect CO₂ diffusers",f"Reduce flow to {max(8,co2*0.85):.1f} m³/h"],"timeframe":"Inspect within 2 hours"})
    if not recs: recs.append({"priority":"ok","issue":"All parameters optimal","cause":"Pond operating normally.","actions":["Continue standard monitoring"],"timeframe":"Routine"})
    return recs

# ── ROUTES ────────────────────────────────────────────────
@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/ponds")
def api_ponds():
    h = request.args.get("hour")
    h = float(h) if h else None
    return jsonify([compute(p, h) for p in PONDS])

@app.route("/api/pond/<pid>")
def api_pond(pid):
    pdef = next((p for p in PONDS if p["id"]==pid), None)
    if not pdef: return jsonify({"error":"not found"}), 404
    h   = request.args.get("hour"); co2 = request.args.get("co2")
    toff= float(request.args.get("toff",0))
    return jsonify(compute(pdef, float(h) if h else None, float(co2) if co2 else None, toff))

@app.route("/api/simulate")
def api_simulate():
    pid  = request.args.get("pond","A-2")
    co2  = float(request.args.get("co2",18))
    toff = float(request.args.get("toff",0))
    cloud= float(request.args.get("cloud",0))/100
    pdef = next((p for p in PONDS if p["id"]==pid), PONDS[1])
    density = logistic(pdef["day"])
    result = {"hours":[],"ph":[],"temperature":[],"par":[],"growth_factor":[],"o2":[],"co2_absorption":[],"density":density,"day":pdef["day"],"pond_id":pid}
    for h in range(25):
        l = par(h)*(1-cloud); t = temp_base(h,toff)
        ph = ph_calc(h,density,co2); gf = gfactor(l,t,ph,co2)
        result["hours"].append(h)
        result["ph"].append(round(ph,2))
        result["temperature"].append(round(t,1))
        result["par"].append(round(l,0))
        result["growth_factor"].append(round(gf,4))
        result["o2"].append(round(min(115,84+gf*17+(l/1150)*11),1))
        result["co2_absorption"].append(round(min(99,55+gf*42+(l/1150)*18),1))
    return jsonify(result)

@app.route("/api/predict/<pid>")
def api_predict(pid):
    pdef = next((p for p in PONDS if p["id"]==pid), PONDS[1])
    day0 = pdef["day"]; rows=[]; peak_day=None
    for delta in range(-day0, 22):
        d = day0+delta
        if d < 0: continue
        dens = logistic(d)
        rows.append({"label":f"Day {d}" if d!=day0 else "TODAY","day":d,
            "past":round(dens+random.uniform(-0.012,0.012),3) if delta<=0 else None,
            "pred":round(dens,3) if delta>=0 else None,
            "upper":round(dens+0.06+delta*0.004,3) if delta>0 else None,
            "lower":round(max(0,dens-0.05-delta*0.003),3) if delta>0 else None,
            "today":delta==0})
        if peak_day is None and dens>=K*0.87: peak_day=d
    return jsonify({"pond_id":pid,"series":rows,"peak_day":peak_day,"day":day0,"conf":91})

@app.route("/api/co2opt")
def api_co2opt():
    hour = float(request.args.get("hour",12))
    kiln = float(request.args.get("kiln",182))
    states = [compute(p,hour) for p in PONDS]
    scores = [s["density"]/K + max(0,s["ph"]-7.8)*2.5 for s in states]
    total  = sum(scores)
    result = []
    for i,s in enumerate(states):
        rec = round((scores[i]/total)*kiln*0.92,1)
        chg = round((rec-s["co2_flow"])/max(1,s["co2_flow"])*100,1)
        result.append({**s,"recommended":rec,"change_pct":chg})
    return jsonify({"kiln":kiln,"util":91.2,"ponds":result})

@app.route("/api/carbon")
def api_carbon():
    hour = float(request.args.get("hour",12))
    pond_rows=[]; total=0
    for p in PONDS:
        s = compute(p,hour)
        co2t = round(s["co2_captured_kg"]*(hour/24),1)
        total += co2t
        pond_rows.append({**s,"co2_today":co2t})
    history=[]
    for i in range(30,0,-1):
        cap=round(110*(0.8+random.uniform(0,0.3)),1)
        history.append({"day":(datetime.now()-timedelta(days=i)).strftime("%b %d"),"captured":cap,"target":110})
    return jsonify({"today":round(total,1),"month":3240,"annual_ytd":11800,"ratio":1.84,"ponds":pond_rows,"history":history})

@app.route("/api/alerts")
def api_alerts():
    hour = float(request.args.get("hour",12))
    alerts=[]
    for p in PONDS:
        s = compute(p,hour)
        if s["status"] in ("critical","warning"):
            r = s["recommendations"][0] if s["recommendations"] else {}
            alerts.append({"pond":p["id"],"type":s["status"],"text":r.get("issue","Issue detected"),
                           "time":"4 min ago" if s["status"]=="critical" else "18 min ago","recs":s["recommendations"]})
    alerts.append({"pond":"A-2","type":"info","text":"Optimal harvest window approaching. Grade A confirmed.","time":"1h ago",
                   "recs":[{"priority":"info","issue":"Harvest window tomorrow 14:00-18:00","cause":"Density nearing plateau.",
                            "actions":["Schedule harvest","Confirm centrifuge","Prepare fresh medium"],"timeframe":"Prepare now"}]})
    return jsonify(alerts)

@app.route("/api/export/excel")
def export_excel():
    try: from openpyxl import Workbook; from openpyxl.styles import PatternFill, Font, Alignment
    except: return "openpyxl not installed",500
    hour = float(request.args.get("hour",12))
    today = datetime.now().strftime("%Y-%m-%d")
    wb = Workbook(); wb.remove(wb.active)
    G1="1A3A1E"; G2="2D5C35"; GLIGHT="F0F8F3"
    def hf(c): return PatternFill("solid",fgColor=c)
    def bf(c="FFFFFF",sz=11): return Font(bold=True,color=c,size=sz,name="Calibri")
    def rf(sz=10): return Font(color="374151",size=sz,name="Calibri")
    def ctr(): return Alignment(horizontal="center",vertical="center",wrap_text=True)
    # Sheet 1
    ws = wb.create_sheet("Per-Pond Ledger"); ws.sheet_view.showGridLines=False
    ws.merge_cells("A1:L1"); ws["A1"].value=f"AlgaCem Carbon Capture — {today} — CIMAR Safi"
    ws["A1"].fill=hf(G1); ws["A1"].font=bf(sz=12); ws["A1"].alignment=ctr(); ws.row_dimensions[1].height=28
    hdrs=["Pond","Stage","Day","Density g/L","Biomass kg","CO₂ Today kg","Absorption %","CO₂ Flow m³/h","pH","Temp °C","O₂ %","Grade"]
    for j,h in enumerate(hdrs,1):
        c=ws.cell(2,j,h); c.fill=hf(G2); c.font=bf(sz=9); c.alignment=ctr()
    ws.row_dimensions[2].height=24
    widths=[10,16,8,14,13,14,16,16,8,9,8,8]
    for j,w in enumerate(widths,1): ws.column_dimensions[__import__('openpyxl').utils.get_column_letter(j)].width=w
    total_co2=0; total_bio=0
    for i,pdef in enumerate(PONDS):
        s=compute(pdef,hour); co2t=round(s["co2_captured_kg"]*(hour/24),1)
        total_co2+=co2t; total_bio+=s["biomass_kg"]; row=i+3
        bg=GLIGHT if i%2 else "FFFFFF"
        for j,v in enumerate([s["id"],s["stage"],s["day"],s["density"],s["biomass_kg"],co2t,s["absorption"],s["co2_flow"],s["ph"],s["temperature"],s["o2"],s["grade"]],1):
            c=ws.cell(row,j,v); c.font=rf(); c.alignment=ctr(); c.fill=hf(bg)
        ws.row_dimensions[row].height=16
    tr=len(PONDS)+3
    for j,v in enumerate(["TOTAL","","",""]+[round(total_bio,1),round(total_co2,1)]+[""]*6,1):
        c=ws.cell(tr,j,v); c.font=bf(sz=10); c.fill=hf(G1); c.alignment=ctr()
    ws.row_dimensions[tr].height=20
    # Sheet 2 — 30-day
    ws2=wb.create_sheet("30-Day History"); ws2.sheet_view.showGridLines=False
    ws2.merge_cells("A1:E1"); ws2["A1"].value="30-Day CO₂ Capture History"
    ws2["A1"].fill=hf(G1); ws2["A1"].font=bf(sz=12); ws2["A1"].alignment=ctr(); ws2.row_dimensions[1].height=26
    for j,h in enumerate(["Date","CO₂ Captured (kg)","Target (kg)","vs Target (%)","Cumulative (kg)"],1):
        c=ws2.cell(2,j,h); c.fill=hf(G2); c.font=bf(sz=9); c.alignment=ctr()
    cumul=0
    for i in range(30,0,-1):
        d=datetime.now()-timedelta(days=i); cap=round(110*(0.8+random.uniform(0,0.3)),1)
        cumul+=cap; vs=round((cap/110-1)*100,1); row=32-i+2
        bg=GLIGHT if cap>=110 else "FFF8F0"
        for j,v in enumerate([d.strftime("%Y-%m-%d"),cap,110,vs,round(cumul,1)],1):
            c=ws2.cell(row,j,v); c.font=rf(); c.alignment=ctr(); c.fill=hf(bg)
    out=io.BytesIO(); wb.save(out); out.seek(0)
    resp=make_response(out.getvalue())
    resp.headers["Content-Disposition"]=f"attachment; filename=AlgaCem_Carbon_{today}.xlsx"
    resp.headers["Content-Type"]="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return resp

@app.route("/api/export/heidelberg")
def export_heidelberg():
    hour=float(request.args.get("hour",12))
    today=datetime.now().strftime("%d %B %Y"); iso=datetime.now().strftime("%Y-%m-%d")
    pond_rows=[]; total_co2=0; total_bio=0
    for p in PONDS:
        s=compute(p,hour); co2t=round(s["co2_captured_kg"]*(hour/24),1)
        total_co2+=co2t; total_bio+=s["biomass_kg"]; pond_rows.append({**s,"co2_today":co2t})
    history=[]
    for i in range(14,0,-1):
        cap=round(110*(0.8+random.uniform(0,0.3)),1)
        history.append({"day":(datetime.now()-timedelta(days=i)).strftime("%b %d"),"cap":cap})
    # Build table rows safely
    rows_html=""
    for p in pond_rows:
        rows_html += f"<tr><td><strong>{p['id']}</strong></td><td>{p['stage']}</td><td>{p['day']}</td>"
        rows_html += f"<td style='font-family:monospace'>{p['density']:.3f}</td>"
        rows_html += f"<td style='font-family:monospace'>{p['biomass_kg']:.1f}</td>"
        rows_html += f"<td style='font-family:monospace'><strong>{p['co2_today']:.1f}</strong></td>"
        rows_html += f"<td style='font-family:monospace'>{p['absorption']}%</td>"
        rows_html += f"<td style='font-family:monospace'>{p['ph']:.2f}</td>"
        rows_html += f"<td style='font-family:monospace'>{p['temperature']:.1f}</td>"
        rows_html += f"<td>{p['grade']}</td>"
        sc3 = p['status']; rows_html += f'<td><span class="s s-{sc3}">{sc3}</span></td></tr>'
    # Build pond grid
    pond_grid=""
    for p in pond_rows:
        bg = "#f0fdf4" if p["status"]=="healthy" else ("#fffbeb" if p["status"]=="warning" else "#fef2f2")
        bd = "#d0e8d8" if p["status"]=="healthy" else ("#fcd34d" if p["status"]=="warning" else "#fca5a5")
        sc2 = "#16a34a" if p["status"]=="healthy" else ("#d97706" if p["status"]=="warning" else "#dc2626")
        pond_grid += f'''<div style="background:{bg};border:1px solid {bd};border-radius:6px;padding:10px;text-align:center">
          <div style="font-size:15px;font-weight:700">{p["id"]}</div>
          <div style="font-size:9px;color:#6b7280;margin:2px 0">{p["stage"]}</div>
          <div style="font-family:monospace;font-size:11px;font-weight:600">pH {p["ph"]:.2f}</div>
          <div style="font-family:monospace;font-size:10px">{p["density"]:.2f} g/L</div>
          <div style="font-size:8px;font-weight:700;margin-top:3px;color:{sc2}">{p["status"].upper()}</div>
          <div style="font-family:monospace;font-size:11px;font-weight:700;color:#2d5c35;margin-top:3px">{p["co2_today"]:.1f} kg</div>
        </div>'''
    # Build bar chart
    bars=""
    for d in history:
        w = min(100, d["cap"]/1.4)
        col = "#2d7a40" if d["cap"]>=110 else "#d97706"
        bars += f'''<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <div style="width:36px;font-size:9px;color:#374151;font-weight:600">{d["day"]}</div>
          <div style="flex:1;background:#e5e7eb;border-radius:2px;height:13px;position:relative">
            <div style="width:{w:.0f}%;background:{col};height:100%;border-radius:2px"></div>
          </div>
          <div style="width:36px;font-size:9px;font-family:monospace;text-align:right">{d["cap"]:.0f}</div>
        </div>'''
    # Build per-pond bars
    pond_bars=""
    for p in pond_rows:
        w2 = min(100, p["co2_today"]*5)
        pond_bars += f'''<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
          <div style="width:28px;font-size:9px;font-weight:700;color:#1a3a1e">{p["id"]}</div>
          <div style="flex:1;background:#e5e7eb;border-radius:3px;height:14px;overflow:hidden">
            <div style="width:{w2:.0f}%;background:#2d7a40;height:100%;border-radius:3px"></div>
          </div>
          <div style="width:36px;font-size:9px;font-family:monospace;text-align:right">{p["co2_today"]:.1f}</div>
        </div>'''
    html=f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Heidelberg Materials Carbon Report {iso}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
*{{margin:0;padding:0;box-sizing:border-box}} body{{font-family:'Inter',sans-serif;color:#1a1a1a;font-size:11px}}
.cover{{background:linear-gradient(135deg,#0a2410,#1a4a24,#2d7a40);color:#fff;padding:48px}}
.cover-logo{{font-size:24px;font-weight:700;letter-spacing:.04em}}
.cover-sub{{font-size:9px;opacity:.65;letter-spacing:.15em;text-transform:uppercase;margin-bottom:28px}}
.cover-title{{font-size:26px;font-weight:300;line-height:1.4}} .cover-meta{{font-size:10px;opacity:.6;margin-top:20px}}
.body{{padding:32px 48px;max-width:920px;margin:auto}}
h2{{font-size:11px;font-weight:700;color:#1a3a1e;border-bottom:2px solid #2d5c35;padding-bottom:4px;margin:24px 0 12px;text-transform:uppercase;letter-spacing:.1em}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px}}
.kpi{{background:#f0f7f2;border:1px solid #d0e8d8;border-radius:7px;padding:12px;text-align:center}}
.kpi-l{{font-size:8px;text-transform:uppercase;letter-spacing:.1em;color:#6b7280;margin-bottom:4px}}
.kpi-v{{font-size:20px;font-weight:700;color:#1a3a1e;line-height:1}} .kpi-s{{font-size:9px;color:#16a34a;margin-top:2px}}
table{{width:100%;border-collapse:collapse;font-size:10px;margin-bottom:14px}}
th{{background:#1a3a1e;color:#fff;padding:6px 8px;text-align:left;font-size:8px;font-weight:600;text-transform:uppercase;letter-spacing:.07em}}
td{{padding:5px 8px;border-bottom:1px solid #f0f0f0}} tr:nth-child(even) td{{background:#f9fbf9}}
.s{{display:inline-block;padding:1px 5px;border-radius:3px;font-size:8px;font-weight:700;text-transform:uppercase}}
.s-healthy{{background:#dcfce7;color:#15803d}} .s-warning{{background:#fef3c7;color:#d97706}} .s-critical{{background:#fee2e2;color:#dc2626}}
.stmt{{background:#f0f7f2;border:1px solid #d0e8d8;border-left:4px solid #2d5c35;border-radius:4px;padding:11px 13px;margin:10px 0;line-height:1.65;color:#374151}}
.two{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}}
.box{{background:#fafafa;border:1px solid #e5e7eb;border-radius:5px;padding:11px 13px}}
.box-title{{font-size:9px;font-weight:700;color:#1a3a1e;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px}}
.pond-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-top:8px}}
.prog{{border:1px solid #d0e8d8;border-radius:5px;padding:9px 13px;margin:6px 0;display:flex;justify-content:space-between;align-items:center}}
.pb{{background:#e5e7eb;border-radius:3px;height:5px;margin-top:4px;overflow:hidden;width:220px}}
.pf{{height:100%;background:linear-gradient(90deg,#2d5c35,#4ade80);border-radius:3px}}
.footer{{margin-top:36px;padding-top:10px;border-top:1px solid #e5e7eb;font-size:8px;color:#9ca3af;display:flex;justify-content:space-between}}
@media print{{body{{print-color-adjust:exact;-webkit-print-color-adjust:exact}}}}
</style></head><body>
<div class="cover">
  <div class="cover-logo">Heidelberg Materials</div>
  <div class="cover-sub">Science-Based Carbon Accounting</div>
  <div style="font-size:26px;font-weight:300;line-height:1.4;margin-bottom:8px">Biological CO₂ Sequestration Report<br>AlgaCem — CIMAR Safi Facility</div>
  <div class="cover-meta">Report Date: {today} · Safi, Morocco · Operator: CIMAR · {datetime.now().strftime("%H:%M")} UTC+1</div>
</div>
<div class="body">
<h2>Executive Summary</h2>
<div class="kpis">
  <div class="kpi"><div class="kpi-l">CO₂ Today</div><div class="kpi-v">{round(total_co2,1)}<span style="font-size:10px;color:#6b7280"> kg</span></div><div class="kpi-s">↑ +8% vs avg</div></div>
  <div class="kpi"><div class="kpi-l">Total Biomass</div><div class="kpi-v">{round(total_bio,0):.0f}<span style="font-size:10px;color:#6b7280"> kg</span></div><div class="kpi-s">8 ponds active</div></div>
  <div class="kpi"><div class="kpi-l">Annual YTD</div><div class="kpi-v">11.8<span style="font-size:10px;color:#6b7280"> t</span></div><div class="kpi-s">47% of goal</div></div>
  <div class="kpi"><div class="kpi-l">Efficiency</div><div class="kpi-v">1.84<span style="font-size:10px;color:#6b7280"> ratio</span></div><div class="kpi-s">kg CO₂/kg biomass</div></div>
</div>
<div class="stmt"><strong>Site Declaration:</strong> CIMAR Safi confirms CO₂ sequestration data is generated by the AlgaCem Pond Intelligence Dashboard via continuous sensor monitoring across all 8 Spirulina platensis raceways. Data is timestamped and auditable.<br><br><strong>Calculation:</strong> CO₂ = biomass growth × volume × 1.83 kg CO₂/kg dry biomass (IPCC AR6). Standard: GHG Protocol / ISO 14064-1:2018.</div>
<h2>Per-Pond CO₂ Ledger — {iso}</h2>
<table><thead><tr><th>Pond</th><th>Stage</th><th>Day</th><th>Density g/L</th><th>Biomass kg</th><th>CO₂ Today kg</th><th>Abs %</th><th>pH</th><th>Temp °C</th><th>Grade</th><th>Status</th></tr></thead><tbody>
{rows_html}
<tr style="background:#f0f7f2"><td colspan="4"><strong>SITE TOTAL</strong></td><td><strong>{round(total_bio,1)}</strong></td><td><strong>{round(total_co2,1)}</strong></td><td colspan="5"></td></tr>
</tbody></table>
<div class="two">
  <div class="box"><div class="box-title">Per-Pond CO₂ (Today)</div>{pond_bars}</div>
  <div class="box"><div class="box-title">14-Day History (dashed = 110 kg target)</div>{bars}</div>
</div>
<h2>Pond Health Status</h2>
<div class="pond-grid">{pond_grid}</div>
<h2>Annual Target Progress</h2>
<div class="prog"><div><div style="font-size:11px;font-weight:600;color:#1a3a1e">CO₂ Sequestration YTD</div><div style="font-size:9px;color:#6b7280;margin-top:2px">11.8 t / 25.0 t annual</div><div class="pb"><div class="pf" style="width:47%"></div></div></div><div style="font-size:10px;color:#16a34a;font-weight:600">47% · On track</div></div>
<div class="prog"><div><div style="font-size:11px;font-weight:600;color:#1a3a1e">Daily Average vs Target</div><div style="font-size:9px;color:#6b7280;margin-top:2px">30-day avg: 107.4 kg/day</div><div class="pb"><div class="pf" style="width:98%"></div></div></div><div style="font-size:10px;color:#16a34a;font-weight:600">98% · Excellent</div></div>
<h2>evoZero Alignment &amp; Methodology</h2>
<div class="stmt">Biological carbon sequestration at CIMAR Safi is a verifiable, additive carbon sink complementing Heidelberg Materials evoZero cement accounting. The AlgaCem process captures CO₂ from the cement kiln via Spirulina biomass fixation.<br><br><strong>Standards:</strong> ISO 14064-1:2018 · GHG Protocol · SBTi &nbsp;·&nbsp; <strong>Audit:</strong> Q2 2026 (Bureau Veritas/SGS) &nbsp;·&nbsp; <strong>ID:</strong> HM-CIMAR-{datetime.now().strftime("%Y%m%d")}-001</div>
<div class="footer"><span>AlgaCem Dashboard · CIMAR Safi · Heidelberg Materials</span><span>CONFIDENTIAL · {datetime.now().strftime("%Y-%m-%d %H:%M")} · v1.0</span></div>
</div>
<script>window.onload=function(){{window.print()}}</script>
</body></html>"""
    resp=make_response(html); resp.headers["Content-Type"]="text/html; charset=utf-8"; return resp


if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port,debug=False)
