import streamlit as st, sqlite3, hashlib, os, datetime as dt, pandas as pd

BRAND = os.environ.get("CCTS_BRAND", "CarbonTrack CCTS")  # apna brand naam yaha badlo (white-label)
st.set_page_config(BRAND, "🌍", layout="wide")
st.markdown("""<style>
#MainMenu,footer,[data-testid=stToolbar]{visibility:hidden}
.block-container{padding-top:2rem}
h1{color:#0b3d2e}
[data-testid=stMetric]{background:#fff;border:1px solid #dfe9e3;border-left:5px solid #1b8a5a;border-radius:12px;padding:14px 18px;box-shadow:0 2px 8px rgba(0,0,0,.05)}
[data-testid=stSidebar]{background:linear-gradient(180deg,#0b3d2e,#14654a)}
[data-testid=stSidebar] *{color:#fff!important}
[data-testid=stSidebar] .stButton>button{background:transparent;border:1px solid #fff}
.stButton>button,.stDownloadButton>button{border-radius:8px;font-weight:600}
.hero{background:linear-gradient(135deg,#0b3d2e,#1b8a5a);color:#fff;padding:30px 34px;border-radius:16px;margin-bottom:18px}
.hero h1{color:#fff;margin:0}.hero p{margin:6px 0 0;opacity:.9}
</style>""", unsafe_allow_html=True)
DB = "ccts.db"
# Sample factors: kg CO2e per unit. Official/BEE/IPCC factors se replace karo.
FACTORS = {"Electricity (kWh)": 0.82, "Diesel (litre)": 2.68, "Petrol (litre)": 2.31,
           "Coal (kg)": 2.42, "Natural Gas (m3)": 2.0, "LPG (kg)": 2.98}
MENU = {"admin": ["Dashboard", "Emissions", "Compliance", "Wallet", "Marketplace", "Users", "Reports", "Audit Log", "Guide", "Profile"],
        "manager": ["Dashboard", "Emissions", "Wallet", "Reports", "Guide", "Profile"],
        "trader": ["Dashboard", "Wallet", "Marketplace", "Guide", "Profile"],
        "verifier": ["Dashboard", "Verify", "Guide", "Profile"],
        "superadmin": ["Clients", "Guide", "Profile"]}

SECTORS = ["Aluminium", "Cement", "Chlor-Alkali", "Pulp & Paper", "Iron & Steel", "Fertilizer", "Petroleum Refining", "Petrochemicals", "Textile", "Other"]
def fy_of(m):  # Indian financial year: April-March
    y, mo = int(m[:4]), int(m[5:7]); s = y if mo >= 4 else y - 1
    return f"{s}-{str(s + 1)[2:]}"
def cur_fy(): t = dt.date.today(); return fy_of(f"{t.year}-{t.month:02d}")
def fy_list(): s = int(cur_fy()[:4]); return [f"{y}-{str(y + 1)[2:]}" for y in range(s - 2, s + 2)]
def fy_stats(tid, fy):
    rows = [r for r in q("SELECT month,tco2e,verified FROM emissions WHERE tenant_id=?", (tid,)) if fy_of(r["month"]) == fy]
    return sum(r["tco2e"] for r in rows if r["verified"] == 1), sum(1 for r in rows if r["verified"] != 1)
def save_ev(tid, f):
    if not f: return ""
    os.makedirs("evidence", exist_ok=True)
    p = os.path.join("evidence", f"{tid}_{dt.datetime.now():%Y%m%d%H%M%S}_" + "".join(c for c in os.path.basename(f.name) if c.isalnum() or c in "._-"))
    open(p, "wb").write(f.getbuffer()); return p
def now(): return dt.datetime.now().strftime("%Y-%m-%d %H:%M")
def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c
def q(sql, a=()):
    with db() as c: return c.execute(sql, a).fetchall()
def df(rows): return pd.DataFrame([dict(r) for r in rows])
def hp(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 100000).hex()
def add_user(tid, email, pw, role):
    s = os.urandom(16).hex()
    q("INSERT INTO users(tenant_id,email,salt,pw,role) VALUES(?,?,?,?,?)", (tid, email.lower().strip(), s, hp(pw, s), role))
def set_pw(email, pw, tid):
    s = os.urandom(16).hex()
    q("UPDATE users SET salt=?,pw=? WHERE email=? AND tenant_id=?", (s, hp(pw, s), email, tid))
def log(action):
    u = st.session_state.user
    q("INSERT INTO audit(tenant_id,who,action,ts) VALUES(?,?,?,?)", (u["tenant_id"], u["email"], action, now()))
def balance(tid): return round(q("SELECT COALESCE(SUM(qty),0) b FROM ledger WHERE tenant_id=?", (tid,))[0]["b"], 2)

def init():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS tenants(id INTEGER PRIMARY KEY, name TEXT UNIQUE, active INT DEFAULT 1);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, tenant_id INT, email TEXT UNIQUE, salt TEXT, pw TEXT, role TEXT);
        CREATE TABLE IF NOT EXISTS emissions(id INTEGER PRIMARY KEY, tenant_id INT, month TEXT, source TEXT, kind TEXT, qty REAL, tco2e REAL, verified INT DEFAULT 0);
        CREATE TABLE IF NOT EXISTS targets(tenant_id INT, year TEXT, target REAL, PRIMARY KEY(tenant_id,year));
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY, tenant_id INT, kind TEXT, qty REAL, note TEXT, ts TEXT);
        CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, tenant_id INT, side TEXT, qty REAL, price REAL, status TEXT DEFAULT 'open');
        CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY, buyer INT, seller INT, qty REAL, price REAL, ts TEXT);
        CREATE TABLE IF NOT EXISTS cfg(tenant_id INT, fy TEXT, sector TEXT, production REAL, target_gei REAL, PRIMARY KEY(tenant_id,fy));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, tenant_id INT, who TEXT, action TEXT, ts TEXT);
        """)
    for col in ("evidence TEXT DEFAULT ''", "entered_by TEXT DEFAULT ''", "note TEXT DEFAULT ''"):
        try: q(f"ALTER TABLE emissions ADD COLUMN {col}")
        except sqlite3.OperationalError: pass
    if not q("SELECT 1 FROM tenants WHERE id=1"):
        q("INSERT INTO tenants(id,name) VALUES(1,'PLATFORM')")
        add_user(1, "super@ccts.com", os.environ.get("CCTS_SUPER_PW", "Admin@123"), "superadmin")

# ---------- AUTH ----------
def auth_page():
    st.markdown(f"<div class='hero'><h1>🌍 {BRAND}</h1><p>Emission tracking • Verification • Carbon credit wallet • Trading marketplace</p></div>", unsafe_allow_html=True)
    t1, t2 = st.tabs(["Login", "Register Company"])
    with t1:
        e = st.text_input("Email", key="le"); p = st.text_input("Password", type="password", key="lp")
        if st.button("Login"):
            r = q("SELECT u.*, t.name tname, t.active FROM users u JOIN tenants t ON t.id=u.tenant_id WHERE u.email=?", (e.lower().strip(),))
            if not r or hp(p, r[0]["salt"]) != r[0]["pw"]: st.error("Invalid email or password")
            elif not r[0]["active"]: st.error("Your account has been suspended. Please contact support.")
            else:
                st.session_state.user = dict(r[0]); log("Login"); st.rerun()
    with t2:
        cn = st.text_input("Company name"); ae = st.text_input("Admin email"); ap = st.text_input("Admin password (min 8)", type="password")
        if st.button("Create Company"):
            if not cn or "@" not in ae or len(ap) < 8: st.error("Please fill in all fields correctly (password: minimum 8 characters)")
            elif q("SELECT 1 FROM users WHERE email=?", (ae.lower().strip(),)): st.error("Company name or email already exists")
            else:
                try:
                    q("INSERT INTO tenants(name) VALUES(?)", (cn.strip(),))
                    tid = q("SELECT id FROM tenants WHERE name=?", (cn.strip(),))[0]["id"]
                    add_user(tid, ae, ap, "admin"); st.success("Company registered successfully! Please sign in from the Login tab.")
                except sqlite3.IntegrityError: st.error("Company name or email already exists")

# ---------- PAGES ----------
def dashboard(tid):
    fy = cur_fy()
    tot = q("SELECT COALESCE(SUM(tco2e),0) a, COALESCE(SUM(CASE WHEN verified=1 THEN tco2e END),0) v FROM emissions WHERE tenant_id=?", (tid,))[0]
    cf = q("SELECT production,target_gei FROM cfg WHERE tenant_id=? AND fy=?", (tid, fy)); ver, _ = fy_stats(tid, fy)
    c = st.columns(4)
    c[0].metric("Total Emissions (tCO2e)", f"{tot['a']:.2f}"); c[1].metric("Verified", f"{tot['v']:.2f}")
    c[2].metric(f"Intensity FY {fy}: actual / target", f"{ver / cf[0]['production']:.3f} / {cf[0]['target_gei']:.3f}" if cf and cf[0]["production"] else "Not set"); c[3].metric("Credits Balance", f"{balance(tid):.2f}")
    m = df(q("SELECT month, SUM(tco2e) tco2e FROM emissions WHERE tenant_id=? GROUP BY month ORDER BY month", (tid,)))
    k = df(q("SELECT kind, SUM(tco2e) tco2e FROM emissions WHERE tenant_id=? GROUP BY kind", (tid,)))
    if not m.empty:
        a, b = st.columns(2); a.subheader("Monthly emissions"); a.bar_chart(m.set_index("month"), color="#1b8a5a"); b.subheader("By fuel / source type"); b.bar_chart(k.set_index("kind"), color="#1b8a5a")
    else: st.info("No data yet. Add your first entry on the Emissions page.")

def emissions(tid):
    st.subheader("Add activity data")
    with st.form("em"):
        c = st.columns(4)
        d = c[0].date_input("Month"); src = c[1].text_input("Source (Boiler, Plant 1...)")
        kind = c[2].selectbox("Type", list(FACTORS)); qty = c[3].number_input("Quantity", min_value=0.0)
        ev = st.file_uploader("Evidence (bill, meter reading, invoice)", type=["pdf", "png", "jpg", "jpeg", "xlsx", "csv"])
        if st.form_submit_button("Save"):
            if qty <= 0: st.error("Quantity must be greater than zero")
            else:
                t = qty * FACTORS[kind] / 1000
                q("INSERT INTO emissions(tenant_id,month,source,kind,qty,tco2e,evidence,entered_by) VALUES(?,?,?,?,?,?,?,?)", (tid, d.strftime("%Y-%m"), src, kind, qty, t, save_ev(tid, ev), st.session_state.user["email"]))
                log(f"Emission added {t:.3f} tCO2e"); st.session_state.flash = f"Saved: {t:.3f} tCO2e"; st.rerun()
    with st.expander("📂 Bulk upload (CSV)"):
        st.download_button("Template download", "month,source,type,quantity\n2026-01,Plant 1,Electricity (kWh),10000\n", "template.csv")
        f = st.file_uploader("CSV file", type="csv")
        if f and st.button("Import CSV"):
            d = pd.read_csv(f)
            if not {"month", "source", "type", "quantity"} <= set(d.columns): st.error("Columns: month, source, type, quantity")
            else:
                n, bad = 0, []
                for i, r in d.iterrows():
                    try:
                        m = str(r["month"]); qty = float(r["quantity"])
                        assert r["type"] in FACTORS and qty > 0 and len(m) == 7 and m[4] == "-"
                        q("INSERT INTO emissions(tenant_id,month,source,kind,qty,tco2e,entered_by) VALUES(?,?,?,?,?,?,?)", (tid, m, str(r["source"]), r["type"], qty, qty * FACTORS[r["type"]] / 1000, st.session_state.user["email"])); n += 1
                    except Exception: bad.append(i + 2)
                log(f"CSV import {n} rows"); st.success(f"{n} rows imported")
                if bad: st.warning(f"Invalid rows (spreadsheet row numbers): {bad}")
    ed = q("SELECT id,kind,qty FROM emissions WHERE tenant_id=? AND verified!=1 ORDER BY id DESC", (tid,))
    if ed:
        with st.expander("✏️ Edit or delete an entry (only before verification)"):
            c = st.columns(4); i = int(c[0].selectbox("Entry ID", [e["id"] for e in ed])); r = next(e for e in ed if e["id"] == i)
            nq = c[1].number_input("New quantity", min_value=0.0, value=float(r["qty"]))
            if c[2].button("Update") and nq > 0:
                q("UPDATE emissions SET qty=?,tco2e=?,verified=0,note='' WHERE id=? AND tenant_id=? AND verified!=1", (nq, nq * FACTORS[r["kind"]] / 1000, i, tid)); log(f"Entry {i} updated"); st.session_state.flash = "Entry updated"; st.rerun()
            if c[3].button("Delete"):
                q("DELETE FROM emissions WHERE id=? AND tenant_id=? AND verified!=1", (i, tid)); log(f"Entry {i} deleted"); st.session_state.flash = "Entry deleted"; st.rerun()
    st.dataframe(df(q("SELECT id,month,source,kind,qty,tco2e,CASE verified WHEN 1 THEN 'Verified' WHEN 2 THEN 'Rejected' ELSE 'Pending' END status,note,entered_by,evidence!='' has_evidence FROM emissions WHERE tenant_id=? ORDER BY id DESC", (tid,))), use_container_width=True)

def verify(tid):
    d = df(q("SELECT id,month,source,kind,qty,tco2e,entered_by,evidence!='' has_evidence FROM emissions WHERE tenant_id=? AND verified=0", (tid,)))
    st.dataframe(d, use_container_width=True)
    if d.empty: st.info("No entries pending verification."); return
    u = st.session_state.user; i = int(st.selectbox("Entry ID", d["id"].tolist()))
    row = q("SELECT evidence,entered_by FROM emissions WHERE id=? AND tenant_id=?", (i, tid))[0]
    if row["evidence"] and os.path.exists(row["evidence"]): st.download_button("📎 Download evidence", open(row["evidence"], "rb").read(), os.path.basename(row["evidence"]))
    else: st.warning("No evidence attached to this entry")
    note = st.text_input("Remark (required for rejection)"); c = st.columns(2)
    if c[0].button("Approve"):
        if row["entered_by"] == u["email"]: st.error("You cannot approve your own entry (maker-checker rule)")
        else: q("UPDATE emissions SET verified=1,note=? WHERE id=? AND tenant_id=?", (note, i, tid)); log(f"Verified entry {i}"); st.session_state.flash = f"Entry {i} approved"; st.rerun()
    if c[1].button("Reject"):
        if not note: st.error("Please add a remark")
        else: q("UPDATE emissions SET verified=2,note=? WHERE id=? AND tenant_id=?", (note, i, tid)); log(f"Rejected entry {i}"); st.session_state.flash = f"Entry {i} rejected"; st.rerun()

def compliance(tid):
    fy = st.selectbox("Compliance year (financial year)", fy_list(), index=2)
    r = q("SELECT * FROM cfg WHERE tenant_id=? AND fy=?", (tid, fy)); cf = r[0] if r else None
    c = st.columns(3)
    sec = c[0].selectbox("Sector", SECTORS, index=SECTORS.index(cf["sector"]) if cf else 0)
    prod = c[1].number_input("Production (tonnes of product)", min_value=0.0, value=float(cf["production"]) if cf else 0.0)
    tgt = c[2].number_input("Target GHG intensity (tCO2e per tonne)", min_value=0.0, format="%.4f", value=float(cf["target_gei"]) if cf else 0.0)
    st.caption("Under CCTS, obligated entities are measured on GHG emission intensity. Enter the target notified for your entity by BEE / MoEFCC.")
    if st.button("Save compliance data"):
        q("INSERT OR REPLACE INTO cfg VALUES(?,?,?,?,?)", (tid, fy, sec, prod, tgt)); log(f"Compliance data saved {fy}"); st.session_state.flash = "Compliance data saved"; st.rerun()
    if not cf: st.info("Save production and target intensity to see your compliance position."); return
    ver, pend = fy_stats(tid, fy); P, T = cf["production"], cf["target_gei"]
    allowed = P * T; gap = allowed - ver
    m = st.columns(4); m[0].metric("Allowed emissions (tCO2e)", f"{allowed:.2f}"); m[1].metric("Verified emissions", f"{ver:.2f}")
    m[2].metric("Actual intensity", f"{ver / P:.4f}" if P else "-"); m[3].metric("Target intensity", f"{T:.4f}")
    if P <= 0 or ver == 0 or pend: st.warning(f"Credits can be issued only when production is entered and all entries for {fy} are verified. Pending or rejected entries: {pend}")
    elif gap > 0:
        st.success(f"Intensity is below target: {gap:.2f} credits eligible for issuance")
        if not q("SELECT 1 FROM ledger WHERE tenant_id=? AND note=?", (tid, f"ISSUE-{fy}")) and st.button("Issue credits"):
            q("INSERT INTO ledger(tenant_id,kind,qty,note,ts) VALUES(?,?,?,?,?)", (tid, "ISSUE", round(gap, 2), f"ISSUE-{fy}", now())); log(f"Issued {gap:.2f} credits {fy}"); st.session_state.flash = f"{gap:.2f} credits issued"; st.rerun()
    else:
        ret = -q("SELECT COALESCE(SUM(qty),0) r FROM ledger WHERE tenant_id=? AND kind='RETIRE' AND note=?", (tid, f"RETIRE-{fy}"))[0]["r"]
        left = round(-gap - ret, 2)
        if left <= 0: st.success(f"Compliant: shortfall of {-gap:.2f} is covered by {ret:.2f} retired credits")
        else: st.error(f"Shortfall: {-gap:.2f}. Retired so far: {ret:.2f}. Remaining to cover: {left:.2f}. Buy credits on the Marketplace, then retire them in Wallet.")

def wallet(tid):
    b = balance(tid); st.metric("Available Credits", f"{b:.2f}")
    st.dataframe(df(q("SELECT ts,kind,qty,note FROM ledger WHERE tenant_id=? ORDER BY id DESC", (tid,))), use_container_width=True)
    c = st.columns(2); fy = c[0].selectbox("Retire against compliance year", fy_list(), index=2)
    r = c[1].number_input("Credits to retire", min_value=0.0, max_value=float(max(b, 0)))
    if st.button("Retire") and r > 0:
        q("INSERT INTO ledger(tenant_id,kind,qty,note,ts) VALUES(?,?,?,?,?)", (tid, "RETIRE", -r, f"RETIRE-{fy}", now())); log(f"Retired {r} for {fy}"); st.session_state.flash = f"{r:.2f} credits retired for FY {fy}"; st.rerun()

def match(tid, side, qty, price):
    opp, cmp, od = ("sell", "<=", "ASC") if side == "buy" else ("buy", ">=", "DESC")
    with db() as c:
        rows = c.execute(f"SELECT * FROM orders WHERE status='open' AND side=? AND tenant_id!=? AND price{cmp}? ORDER BY price {od}, id", (opp, tid, price)).fetchall()
        for r in rows:
            if qty <= 0: break
            f = min(qty, r["qty"]); by, sl = (tid, r["tenant_id"]) if side == "buy" else (r["tenant_id"], tid)
            c.execute("INSERT INTO ledger(tenant_id,kind,qty,note,ts) VALUES(?,?,?,?,?)", (by, "BUY", f, f"@{r['price']}", now()))
            c.execute("INSERT INTO ledger(tenant_id,kind,qty,note,ts) VALUES(?,?,?,?,?)", (sl, "SELL", -f, f"@{r['price']}", now()))
            c.execute("INSERT INTO trades(buyer,seller,qty,price,ts) VALUES(?,?,?,?,?)", (by, sl, f, r["price"], now()))
            left = r["qty"] - f
            c.execute("UPDATE orders SET qty=?, status=? WHERE id=?", (left, "open" if left > 0 else "filled", r["id"])); qty -= f
        if qty > 0: c.execute("INSERT INTO orders(tenant_id,side,qty,price) VALUES(?,?,?,?)", (tid, side, qty, price))

def market(tid):
    res = q("SELECT COALESCE(SUM(qty),0) r FROM orders WHERE tenant_id=? AND side='sell' AND status='open'", (tid,))[0]["r"]
    avail = balance(tid) - res; st.info(f"Credits available to sell: {avail:.2f}")
    c = st.columns(4); side = c[0].selectbox("Side", ["buy", "sell"]); qty = c[1].number_input("Qty", min_value=0.0)
    price = c[2].number_input("Price ₹/credit", min_value=0.0)
    if c[3].button("Place order") and qty > 0 and price > 0:
        if side == "sell" and qty > avail: st.error("Insufficient credits available")
        else: match(tid, side, qty, price); log(f"Order {side} {qty}@{price}"); st.rerun()
    a, b = st.columns(2)
    a.subheader("Order Book"); a.dataframe(df(q("SELECT side,qty,price FROM orders WHERE status='open' ORDER BY price")), use_container_width=True)
    b.subheader("My Trades"); b.dataframe(df(q("SELECT ts,CASE WHEN buyer=? THEN 'BUY' ELSE 'SELL' END side,qty,price FROM trades WHERE buyer=? OR seller=? ORDER BY id DESC", (tid, tid, tid))), use_container_width=True)
    mine = q("SELECT id,side,qty,price FROM orders WHERE tenant_id=? AND status='open'", (tid,))
    if mine:
        oid = st.selectbox("Cancel order ID", [m["id"] for m in mine])
        if st.button("Cancel"): q("UPDATE orders SET status='cancelled' WHERE id=? AND tenant_id=?", (oid, tid)); st.rerun()

def users(tid):
    with st.form("nu"):
        c = st.columns(3); e = c[0].text_input("Email"); p = c[1].text_input("Password", type="password")
        r = c[2].selectbox("Role", ["manager", "trader", "verifier", "admin"])
        if st.form_submit_button("Add user"):
            try: add_user(tid, e, p, r); log(f"User added {e}"); st.rerun()
            except sqlite3.IntegrityError: st.error("Email already exists")
    ul = q("SELECT email,role FROM users WHERE tenant_id=?", (tid,))
    st.dataframe(df(ul), use_container_width=True)
    st.subheader("Password reset (forgot password)")
    c = st.columns(3); e = c[0].selectbox("User", [x["email"] for x in ul]); n = c[1].text_input("New password", type="password", key="ur")
    if c[2].button("Reset") and len(n) >= 8: set_pw(e, n, tid); log(f"Password reset {e}"); st.success("Password reset successfully")

def audit(tid): st.dataframe(df(q("SELECT ts,who,action FROM audit WHERE tenant_id=? ORDER BY id DESC LIMIT 500", (tid,))), use_container_width=True)

GUIDE = {
 "admin": "**Getting started**\n\n1. **Users:** add a verifier, managers and traders.\n2. **Emissions:** enter activity data or bulk-upload a CSV.\n3. **Compliance:** enter the financial-year production and the GHG intensity target notified for your entity.\n4. **Verify:** your verifier reviews and approves the data.\n5. **Compliance:** once all data is verified, click *Issue credits*. Credits = (target intensity - actual intensity) x production.\n6. **Wallet / Marketplace:** retire credits, or buy and sell them.\n7. **Reports:** download CSV reports and the retirement certificate.",
 "manager": "Enter monthly activity data on the **Emissions** page or bulk-upload a CSV. You can view the **Wallet** and download **Reports**.",
 "trader": "Place buy or sell orders on the **Marketplace**. Selling requires credits in your wallet. Orders are matched automatically when prices cross.",
 "verifier": "Open **Verify** to review pending emission entries and approve them. Only approved data counts towards compliance and credit issuance.",
 "superadmin": "On the **Clients** page you can view companies, suspend or activate them, reset admin passwords, load demo data and download a database backup."}
def guide(tid):
    st.markdown(GUIDE[st.session_state.user["role"]])
    st.info("**How are credits earned?** Under CCTS, compliance is measured as GHG emission intensity (tCO2e per tonne of product). Example: production 100 t at target 0.40 allows 40 tCO2e; verified emissions of 21.12 earn 18.88 credits. If emissions exceed the allowance there is a shortfall, and credits must be purchased on the Marketplace. Retired credits are permanently used and cannot be resold.")

def seed_demo():
    fy = cur_fy(); sy = fy[:4]
    for nm, em, sec, tg in (("Demo Steel Ltd", "steel", "Iron & Steel", 0.40), ("Demo Cement Ltd", "cement", "Cement", 0.15)):
        if q("SELECT 1 FROM tenants WHERE name=?", (nm,)): continue
        q("INSERT INTO tenants(name) VALUES(?)", (nm,)); tid = q("SELECT id FROM tenants WHERE name=?", (nm,))[0]["id"]
        for role, pre in (("admin", "admin"), ("verifier", "ver"), ("trader", "trader")): add_user(tid, f"{pre}@demo{em}.com", "Demo@1234", role)
        for i, (k, v) in enumerate([("Electricity (kWh)", 12000), ("Diesel (litre)", 1500), ("Coal (kg)", 3000)]):
            q("INSERT INTO emissions(tenant_id,month,source,kind,qty,tco2e,verified,entered_by) VALUES(?,?,?,?,?,?,1,?)", (tid, f"{sy}-0{i + 4}", "Plant 1", k, v, v * FACTORS[k] / 1000, f"admin@demo{em}.com"))
        q("INSERT INTO cfg VALUES(?,?,?,?,?)", (tid, fy, sec, 100, tg))
        if em == "steel":
            q("INSERT INTO ledger(tenant_id,kind,qty,note,ts) VALUES(?,?,?,?,?)", (tid, "ISSUE", 18.88, f"ISSUE-{fy}", now()))
            q("INSERT INTO orders(tenant_id,side,qty,price) VALUES(?,?,?,?)", (tid, "sell", 10, 850))

def reports(tid):
    em = df(q("SELECT month,source,kind,qty,tco2e,verified FROM emissions WHERE tenant_id=?", (tid,)))
    lg = df(q("SELECT ts,kind,qty,note FROM ledger WHERE tenant_id=?", (tid,)))
    c = st.columns(2)
    c[0].download_button("⬇ Emissions report (CSV)", em.to_csv(index=False), "emissions.csv")
    c[1].download_button("⬇ Credit ledger (CSV)", lg.to_csv(index=False), "ledger.csv")
    ret = -q("SELECT COALESCE(SUM(qty),0) r FROM ledger WHERE tenant_id=? AND kind='RETIRE'", (tid,))[0]["r"]
    name = st.session_state.user["tname"]; cid = f"CCTS-{tid}-{dt.date.today():%Y%m%d}"
    st.metric("Total credits retired", f"{ret:.2f}")
    html = f"<html><body style='font-family:Arial;text-align:center;border:6px double #2e7d32;padding:40px'><h1>Carbon Credit Retirement Certificate</h1><h2>{name}</h2><p>has retired</p><h1>{ret:.2f} tCO2e</h1><p>Date: {dt.date.today()}</p><p>Certificate ID: {cid}</p><small>Demo certificate - not an official registry document</small></body></html>"
    st.download_button("⬇ Retirement certificate (HTML)", html, f"{cid}.html", mime="text/html")

def profile(tid):
    u = st.session_state.user
    o = st.text_input("Current password", type="password"); n = st.text_input("New password (min 8)", type="password")
    if st.button("Change password"):
        r = q("SELECT salt,pw FROM users WHERE id=?", (u["id"],))[0]
        if hp(o, r["salt"]) != r["pw"]: st.error("Current password is incorrect")
        elif len(n) < 8: st.error("Minimum 8 characters required")
        else: set_pw(u["email"], n, u["tenant_id"]); log("Password changed"); st.success("Password changed successfully")

def clients(_):
    if "flash" in st.session_state: st.success(st.session_state.pop("flash"))
    t = q("SELECT COUNT(*) n, COALESCE(SUM(qty*price),0) v FROM trades")[0]
    m = st.columns(3); m[0].metric("Clients", q("SELECT COUNT(*) n FROM tenants WHERE id!=1")[0]["n"]); m[1].metric("Trades", t["n"]); m[2].metric("Trade value (₹)", f"{t['v']:.0f}")
    b = st.columns(2)
    b[0].download_button("💾 Database backup", open(DB, "rb").read(), "ccts_backup.db")
    if b[1].button("🧪 Load demo data (Demo Steel / Demo Cement)"): seed_demo(); st.session_state.flash = "Demo data loaded. Password for all demo users: Demo@1234"; st.rerun()
    d = df(q("SELECT t.id,t.name,t.active,(SELECT COUNT(*) FROM users WHERE tenant_id=t.id) users,(SELECT COALESCE(SUM(qty),0) FROM ledger WHERE tenant_id=t.id) credits FROM tenants t WHERE t.id!=1"))
    d["status"] = d["active"].map({1: "🟢 Active", 0: "🔴 Suspended"}) if not d.empty else []
    st.dataframe(d, use_container_width=True)
    if not d.empty:
        tid = st.selectbox("Client ID", d["id"].tolist()); c = st.columns(2)
        name = d.loc[d["id"] == tid, "name"].iloc[0]
        if c[0].button("Suspend", key="sus"):
            q("UPDATE tenants SET active=0 WHERE id=?", (int(tid),)); st.session_state.flash = f"{name} has been suspended"; st.rerun()
        if c[1].button("Activate", key="act"):
            q("UPDATE tenants SET active=1 WHERE id=?", (int(tid),)); st.session_state.flash = f"{name} has been activated"; st.rerun()
        st.subheader("Client admin password reset")
        ad = [a["email"] for a in q("SELECT email FROM users WHERE tenant_id=? AND role='admin'", (int(tid),))]
        c = st.columns(3); e = c[0].selectbox("Admin email", ad); n = c[1].text_input("New password", type="password", key="rp")
        if c[2].button("Reset password") and len(n) >= 8: set_pw(e, n, int(tid)); st.session_state.flash = f"Password reset for {e}"; st.rerun()

PAGES = {"Dashboard": dashboard, "Emissions": emissions, "Verify": verify, "Compliance": compliance, "Wallet": wallet,
         "Marketplace": market, "Users": users, "Audit Log": audit, "Clients": clients, "Reports": reports, "Profile": profile, "Guide": guide}

# ---------- MAIN ----------
init()
if "user" not in st.session_state: auth_page(); st.stop()
u = st.session_state.user
chk = q("SELECT t.active FROM users x JOIN tenants t ON t.id=x.tenant_id WHERE x.id=?", (u["id"],))
if not chk or not chk[0]["active"]: st.session_state.clear(); st.rerun()
st.sidebar.title(f"🌍 {BRAND}"); st.sidebar.write(f"**{u['tname']}**\n\n{u['email']} ({u['role']})")
page = st.sidebar.radio("Menu", MENU[u["role"]])
if st.sidebar.button("Logout"): st.session_state.clear(); st.rerun()
st.title(page)
if page != "Clients" and "flash" in st.session_state: st.success(st.session_state.pop("flash"))
PAGES[page](u["tenant_id"])

