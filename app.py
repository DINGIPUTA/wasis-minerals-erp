
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, Response
import sqlite3, os, csv, io
from jinja2 import DictLoader
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")
DB = os.path.join(os.path.dirname(__file__), "stone_trade.db")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL, username TEXT UNIQUE NOT NULL,
      password TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'staff',
      active INTEGER NOT NULL DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS ships(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ship_name TEXT NOT NULL,
      supplier TEXT, arrival_date TEXT, quantity REAL NOT NULL DEFAULT 0,
      unloaded REAL NOT NULL DEFAULT 0, cost_per_ton REAL NOT NULL DEFAULT 0,
      notes TEXT
    );
    CREATE TABLE IF NOT EXISTS stock(
      id INTEGER PRIMARY KEY AUTOINCREMENT, product TEXT NOT NULL,
      quantity REAL NOT NULL DEFAULT 0, unit_cost REAL NOT NULL DEFAULT 0,
      location TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS customers(
      id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
      phone TEXT, address TEXT, opening_due REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS sales(
      id INTEGER PRIMARY KEY AUTOINCREMENT, invoice TEXT UNIQUE NOT NULL,
      customer_id INTEGER NOT NULL, product TEXT NOT NULL,
      quantity REAL NOT NULL, price REAL NOT NULL, truck_no TEXT,
      delivery_date TEXT, paid REAL NOT NULL DEFAULT 0,
      created_by INTEGER, FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS payments(
      id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER NOT NULL,
      amount REAL NOT NULL, payment_date TEXT, method TEXT, note TEXT,
      created_by INTEGER, FOREIGN KEY(customer_id) REFERENCES customers(id)
    );
    CREATE TABLE IF NOT EXISTS expenses(
      id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
      amount REAL NOT NULL, expense_date TEXT, note TEXT, created_by INTEGER
    );
    CREATE TABLE IF NOT EXISTS trucks(
      id INTEGER PRIMARY KEY AUTOINCREMENT, truck_no TEXT NOT NULL,
      driver TEXT, phone TEXT, rent REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS ship_costs(
      id INTEGER PRIMARY KEY AUTOINCREMENT, ship_id INTEGER NOT NULL,
      category TEXT NOT NULL, amount REAL NOT NULL DEFAULT 0,
      note TEXT, FOREIGN KEY(ship_id) REFERENCES ships(id)
    );
    CREATE TABLE IF NOT EXISTS deliveries(
      id INTEGER PRIMARY KEY AUTOINCREMENT, sale_id INTEGER, truck_no TEXT,
      driver TEXT, freight REAL NOT NULL DEFAULT 0, loading_cost REAL NOT NULL DEFAULT 0,
      unloading_cost REAL NOT NULL DEFAULT 0, delivery_date TEXT,
      FOREIGN KEY(sale_id) REFERENCES sales(id)
    );
    """)
    if con.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        con.execute("INSERT INTO users(name,username,password,role) VALUES(?,?,?,?)",
                    ("Administrator","admin",generate_password_hash("admin123"),"admin"))
    con.commit(); con.close()

def login_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if "uid" not in session:
            return redirect(url_for("login"))
        return f(*a, **kw)
    return wrap

def admin_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if session.get("role") != "admin":
            flash("Admin permission required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*a, **kw)
    return wrap

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        con=db(); u=con.execute("SELECT * FROM users WHERE username=? AND active=1",(request.form["username"],)).fetchone(); con.close()
        if u and check_password_hash(u["password"], request.form["password"]):
            session.update(uid=u["id"], name=u["name"], role=u["role"])
            return redirect(url_for("dashboard"))
        flash("Username or password is incorrect.","danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    con=db()
    stats = {
      "stock": con.execute("SELECT COALESCE(SUM(quantity),0) v FROM stock").fetchone()["v"],
      "sales": con.execute("SELECT COALESCE(SUM(quantity*price),0) v FROM sales").fetchone()["v"],
      "due": con.execute("""SELECT COALESCE(SUM(c.opening_due),0)+
        COALESCE((SELECT SUM(s.quantity*s.price-s.paid) FROM sales s WHERE s.customer_id=c.id),0)-
        COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.customer_id=c.id),0) v
        FROM customers c""").fetchone()["v"],
      "customers": con.execute("SELECT COUNT(*) v FROM customers").fetchone()["v"],
      "staff": con.execute("SELECT COUNT(*) v FROM users WHERE active=1").fetchone()["v"]
    }
    recent=con.execute("""SELECT s.invoice,c.name,s.product,s.quantity,s.price,s.delivery_date
                          FROM sales s JOIN customers c ON c.id=s.customer_id
                          ORDER BY s.id DESC LIMIT 8""").fetchall()
    con.close()
    return render_template("dashboard.html", stats=stats, recent=recent)

@app.route("/ships", methods=["GET","POST"])
@login_required
def ships():
    con=db()
    if request.method=="POST":
        con.execute("""INSERT INTO ships(ship_name,supplier,arrival_date,quantity,unloaded,cost_per_ton,notes)
                       VALUES(?,?,?,?,?,?,?)""",
                    (request.form["ship_name"],request.form["supplier"],request.form["arrival_date"],
                     float(request.form["quantity"] or 0),float(request.form["unloaded"] or 0),
                     float(request.form["cost_per_ton"] or 0),request.form["notes"]))
        con.commit()
    rows=con.execute("SELECT * FROM ships ORDER BY id DESC").fetchall(); con.close()
    return render_template("ships.html", rows=rows)

@app.route("/stock", methods=["GET","POST"])
@login_required
def stock():
    con=db()
    if request.method=="POST":
        product=request.form["product"]; qty=float(request.form["quantity"] or 0)
        cost=float(request.form["unit_cost"] or 0); loc=request.form["location"]
        old=con.execute("SELECT id,quantity,unit_cost FROM stock WHERE product=? AND COALESCE(location,'')=?",(product,loc)).fetchone()
        if old:
            total=old["quantity"]+qty
            avg=((old["quantity"]*old["unit_cost"])+(qty*cost))/total if total else cost
            con.execute("UPDATE stock SET quantity=?,unit_cost=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(total,avg,old["id"]))
        else:
            con.execute("INSERT INTO stock(product,quantity,unit_cost,location) VALUES(?,?,?,?)",(product,qty,cost,loc))
        con.commit()
    rows=con.execute("SELECT * FROM stock ORDER BY product").fetchall(); con.close()
    return render_template("stock.html", rows=rows)

@app.route("/customers", methods=["GET","POST"])
@login_required
def customers():
    con=db()
    if request.method=="POST":
        con.execute("INSERT INTO customers(name,phone,address,opening_due) VALUES(?,?,?,?)",
                    (request.form["name"],request.form["phone"],request.form["address"],float(request.form["opening_due"] or 0)))
        con.commit()
    rows=con.execute("SELECT * FROM customers ORDER BY name").fetchall(); con.close()
    return render_template("customers.html", rows=rows)

@app.route("/sales", methods=["GET","POST"])
@login_required
def sales():
    con=db()
    if request.method=="POST":
        con.execute("""INSERT INTO sales(invoice,customer_id,product,quantity,price,truck_no,delivery_date,paid,created_by)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (request.form["invoice"],int(request.form["customer_id"]),request.form["product"],
                     float(request.form["quantity"]),float(request.form["price"]),request.form["truck_no"],
                     request.form["delivery_date"],float(request.form["paid"] or 0),session["uid"]))
        # reduce stock by product (simple FIFO-like quantity reduction)
        con.execute("UPDATE stock SET quantity=MAX(quantity-?,0), updated_at=CURRENT_TIMESTAMP WHERE product=?",
                    (float(request.form["quantity"]),request.form["product"]))
        con.commit()
    rows=con.execute("""SELECT s.*,c.name customer FROM sales s JOIN customers c ON c.id=s.customer_id
                        ORDER BY s.id DESC""").fetchall()
    cs=con.execute("SELECT * FROM customers ORDER BY name").fetchall()
    con.close()
    return render_template("sales.html", rows=rows, customers=cs)

@app.route("/payments", methods=["GET","POST"])
@login_required
def payments():
    con=db()
    if request.method=="POST":
        con.execute("""INSERT INTO payments(customer_id,amount,payment_date,method,note,created_by)
                       VALUES(?,?,?,?,?,?)""",
                    (int(request.form["customer_id"]),float(request.form["amount"]),request.form["payment_date"],
                     request.form["method"],request.form["note"],session["uid"]))
        con.commit()
    rows=con.execute("""SELECT p.*,c.name customer FROM payments p JOIN customers c ON c.id=p.customer_id
                        ORDER BY p.id DESC""").fetchall()
    cs=con.execute("SELECT * FROM customers ORDER BY name").fetchall(); con.close()
    return render_template("payments.html", rows=rows, customers=cs)

@app.route("/trucks", methods=["GET","POST"])
@login_required
def trucks():
    con=db()
    if request.method=="POST":
        con.execute("INSERT INTO trucks(truck_no,driver,phone,rent) VALUES(?,?,?,?)",
                    (request.form["truck_no"],request.form["driver"],request.form["phone"],float(request.form["rent"] or 0)))
        con.commit()
    rows=con.execute("SELECT * FROM trucks ORDER BY truck_no").fetchall(); con.close()
    return render_template("trucks.html", rows=rows)

@app.route("/expenses", methods=["GET","POST"])
@login_required
def expenses():
    con=db()
    if request.method=="POST":
        con.execute("INSERT INTO expenses(category,amount,expense_date,note,created_by) VALUES(?,?,?,?,?)",
                    (request.form["category"],float(request.form["amount"]),request.form["expense_date"],request.form["note"],session["uid"]))
        con.commit()
    rows=con.execute("SELECT * FROM expenses ORDER BY id DESC").fetchall(); con.close()
    return render_template("expenses.html", rows=rows)

@app.route("/staff", methods=["GET","POST"])
@login_required
@admin_required
def staff():
    con=db()
    if request.method=="POST":
        try:
            con.execute("INSERT INTO users(name,username,password,role) VALUES(?,?,?,?)",
                        (request.form["name"],request.form["username"],generate_password_hash(request.form["password"]),request.form["role"]))
            con.commit(); flash("Staff user created.","success")
        except sqlite3.IntegrityError: flash("Username already exists.","danger")
    rows=con.execute("SELECT id,name,username,role,active FROM users ORDER BY id").fetchall(); con.close()
    return render_template("staff.html", rows=rows)


@app.route("/ship-costs/<int:ship_id>", methods=["GET","POST"])
@login_required
def ship_costs(ship_id):
    con=db()
    ship=con.execute("SELECT * FROM ships WHERE id=?",(ship_id,)).fetchone()
    if not ship:
        con.close(); return "Ship not found",404
    if request.method=="POST":
        con.execute("INSERT INTO ship_costs(ship_id,category,amount,note) VALUES(?,?,?,?)",
                    (ship_id,request.form["category"],float(request.form["amount"] or 0),request.form["note"]))
        con.commit()
    costs=con.execute("SELECT * FROM ship_costs WHERE ship_id=? ORDER BY id DESC",(ship_id,)).fetchall()
    total=con.execute("SELECT COALESCE(SUM(amount),0) v FROM ship_costs WHERE ship_id=?",(ship_id,)).fetchone()["v"]
    effective=(ship["quantity"] or 0)
    cost_per_ton=((ship["quantity"] or 0)*(ship["cost_per_ton"] or 0)+total)/effective if effective else 0
    con.close()
    return render_template("ship_costs.html",ship=ship,costs=costs,total=total,cost_per_ton=cost_per_ton)

@app.route("/ledger/<int:customer_id>")
@login_required
def ledger(customer_id):
    con=db()
    c=con.execute("SELECT * FROM customers WHERE id=?",(customer_id,)).fetchone()
    sales_rows=con.execute("""SELECT delivery_date date, invoice ref, quantity*price debit, paid credit,
                              'Sale' kind FROM sales WHERE customer_id=?""",(customer_id,)).fetchall()
    pay_rows=con.execute("""SELECT payment_date date, 'PAY-'||id ref, 0 debit, amount credit,
                            'Payment' kind FROM payments WHERE customer_id=?""",(customer_id,)).fetchall()
    entries=sorted([dict(x) for x in sales_rows]+[dict(x) for x in pay_rows], key=lambda x:(x["date"] or "",x["ref"]))
    balance=c["opening_due"] or 0
    for e in entries:
        balance += (e["debit"] or 0) - (e["credit"] or 0)
        e["balance"]=balance
    con.close()
    return render_template("ledger.html",customer=c,entries=entries,balance=balance)

@app.route("/export/<name>")
@login_required
def export_csv(name):
    con=db()
    if name=="sales":
        rows=con.execute("""SELECT s.invoice,c.name customer,s.product,s.quantity,s.price,
                            s.quantity*s.price total,s.paid,(s.quantity*s.price-s.paid) due,
                            s.truck_no,s.delivery_date FROM sales s JOIN customers c ON c.id=s.customer_id
                            ORDER BY s.id DESC""").fetchall()
        headers=["Invoice","Customer","Product","Qty","Rate","Total","Paid","Due","Truck","Date"]
    elif name=="stock":
        rows=con.execute("SELECT product,quantity,unit_cost,location,updated_at FROM stock ORDER BY product").fetchall()
        headers=["Product","Qty","Unit Cost","Location","Updated"]
    elif name=="customers":
        rows=con.execute("SELECT id,name,phone,address,opening_due FROM customers ORDER BY name").fetchall()
        headers=["ID","Customer","Phone","Address","Opening Due"]
    else:
        con.close(); return "Unknown export",404
    out=io.StringIO(); w=csv.writer(out); w.writerow(headers)
    for r in rows: w.writerow(list(r))
    con.close()
    data=io.BytesIO(("\ufeff"+out.getvalue()).encode("utf-8"))
    return send_file(data, mimetype="text/csv; charset=utf-8", as_attachment=True, download_name=f"{name}.csv")

@app.route("/reports")
@login_required
def reports():
    con=db()
    product=con.execute("""SELECT product,SUM(quantity) qty,SUM(quantity*price) revenue
                           FROM sales GROUP BY product ORDER BY revenue DESC""").fetchall()
    cust=con.execute("""SELECT c.name,
       c.opening_due + COALESCE((SELECT SUM(s.quantity*s.price-s.paid) FROM sales s WHERE s.customer_id=c.id),0)
       - COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.customer_id=c.id),0) due
       FROM customers c ORDER BY due DESC""").fetchall()
    exp=con.execute("SELECT COALESCE(SUM(amount),0) v FROM expenses").fetchone()["v"]
    revenue=con.execute("SELECT COALESCE(SUM(quantity*price),0) v FROM sales").fetchone()["v"]
    con.close()
    return render_template("reports.html", product=product, cust=cust, expense=exp, revenue=revenue)


# --- Embedded templates/assets: single-file mobile deployment ---
_EMBEDDED_TEMPLATES = {'base.html': '\n<!doctype html><html lang="bn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">\n<title>ওয়াসিস মিনারেল এন্ড মেটালাস লিমিটেড ERP</title><meta name="theme-color" content="#16232e"><link rel="manifest" href="/static/manifest.json"><link rel="stylesheet" href="/static/style.css"></head><body>\n{% if session.uid %}<div class="mobile-top"><button class="menu-btn" onclick="document.querySelector(\'aside\').classList.toggle(\'open\')">☰</button><div class="brand">ওয়াসিস মিনারেল এন্ড মেটালাস লিমিটেড</div></div><aside><h2>ওয়াসিস মিনারেল এন্ড মেটালাস লিমিটেড</h2>\n<a href="/">Dashboard</a><a href="/ships">জাহাজ</a><a href="/stock">স্টক</a><a href="/customers">কাস্টমার</a><a href="/sales">বিক্রি/ডেলিভারি</a><a href="/payments">পেমেন্ট</a><a href="/trucks">গাড়ি</a><a href="/expenses">খরচ</a><a href="/reports">রিপোর্ট</a><a href="/profit-loss">Profit & Loss</a>{% if session.role==\'admin\' %}<a href="/staff">স্টাফ</a>{% endif %}\n<div class="user">{{session.name}} ({{session.role}})<br><a href="/logout">Logout</a></div></aside><main>{% endif %}\n{% with messages=get_flashed_messages(with_categories=true) %}{% for cat,msg in messages %}<div class="alert {{cat}}">{{msg}}</div>{% endfor %}{% endwith %}\n{% block content %}{% endblock %}</main><script>if("serviceWorker" in navigator){navigator.serviceWorker.register("/static/sw.js").catch(()=>{});}document.addEventListener("click",e=>{if(e.target.closest("main")){const a=document.querySelector("aside");if(a)a.classList.remove("open");}});</script></body></html>\n', 'customers.html': '{% extends "base.html" %}{% block content %}<h1>কাস্টমার</h1><form method="post" class="form"><input name="name" placeholder="কোম্পানির নাম" required><input name="phone" placeholder="মোবাইল"><input name="address" placeholder="ঠিকানা"><input name="opening_due" type="number" step="0.01" placeholder="Opening Due"><button>Save</button></form><table><tr><th>Name</th><th>Phone</th><th>Address</th><th>Opening Due</th></tr>{% for r in rows %}<tr><td>{{r.name}}</td><td>{{r.phone}}</td><td>{{r.address}}</td><td>{{r.opening_due}}</td></tr>{% endfor %}</table>{% endblock %}', 'dashboard.html': '{% extends "base.html" %}{% block content %}<h1>Dashboard</h1><div class="grid">\n<div class="stat">স্টক<br><b>{{"%.2f"|format(stats.stock)}} টন</b></div><div class="stat">মোট বিক্রি<br><b>৳ {{ "%.2f"|format(stats.sales) }}</b></div><div class="stat">আনুমানিক বাকি<br><b>৳ {{ "%.2f"|format(stats.due) }}</b></div><div class="stat">কাস্টমার<br><b>{{stats.customers}}</b></div><div class="stat">Active Staff<br><b>{{stats.staff}}</b></div></div>\n<h2>সাম্প্রতিক ডেলিভারি</h2><table><tr><th>Invoice</th><th>Customer</th><th>Product</th><th>Qty</th><th>Amount</th><th>Date</th></tr>{% for r in recent %}<tr><td>{{r.invoice}}</td><td>{{r.name}}</td><td>{{r.product}}</td><td>{{r.quantity}}</td><td>{{r.quantity*r.price}}</td><td>{{r.delivery_date}}</td></tr>{% endfor %}</table>{% endblock %}', 'expenses.html': '{% extends "base.html" %}{% block content %}<h1>খরচ</h1><form method="post" class="form"><input name="category" placeholder="খরচের ধরন" required><input name="amount" type="number" step="0.01" placeholder="Amount" required><input name="expense_date" type="date"><input name="note" placeholder="Note"><button>Save Expense</button></form><table><tr><th>Category</th><th>Amount</th><th>Date</th><th>Note</th></tr>{% for r in rows %}<tr><td>{{r.category}}</td><td>{{r.amount}}</td><td>{{r.expense_date}}</td><td>{{r.note}}</td></tr>{% endfor %}</table>{% endblock %}', 'invoice.html': '<!doctype html><html lang="bn"><head><meta charset="utf-8"><title>Invoice {{r.invoice}}</title><style>\nbody{font-family:Arial,"Noto Sans Bengali",sans-serif;margin:35px;color:#111}.head{text-align:center;border-bottom:2px solid #111;margin-bottom:20px}.row{display:flex;justify-content:space-between}table{width:100%;border-collapse:collapse;margin-top:25px}th,td{border:1px solid #888;padding:10px;text-align:left}.total{text-align:right;font-size:20px;font-weight:bold}.print{margin:15px 0;padding:10px}@media print{.print{display:none}}\n</style></head><body><div class="head"><h1>ওয়াসিস মিনারেল এন্ড মেটালাস লিমিটেড</h1><p>Import • Export • Stone Supply</p></div>\n<div class="row"><div><b>Customer:</b> {{r.customer}}<br>{{r.phone}}<br>{{r.address}}</div><div><b>Invoice:</b> {{r.invoice}}<br><b>Date:</b> {{r.delivery_date}}</div></div>\n<table><tr><th>Product</th><th>Quantity (Ton)</th><th>Rate/Ton</th><th>Total</th></tr><tr><td>{{r.product}}</td><td>{{r.quantity}}</td><td>৳ {{r.price}}</td><td>৳ {{r.quantity*r.price}}</td></tr></table>\n<p class="total">Total: ৳ {{r.quantity*r.price}}<br>Paid: ৳ {{r.paid}}<br>Due: ৳ {{r.quantity*r.price-r.paid}}</p>\n<button class="print" onclick="window.print()">Print Invoice</button><p>Authorized Signature: __________________</p></body></html>', 'ledger.html': '{% extends "base.html" %}{% block content %}\n<h1>Customer Ledger: {{customer.name}}</h1><div class="stat">Current Due<br><b>৳ {{ "%.2f"|format(balance) }}</b></div>\n<table><tr><th>Date</th><th>Reference</th><th>Type</th><th>Debit</th><th>Credit</th><th>Balance</th></tr>\n{% for e in entries %}<tr><td>{{e.date}}</td><td>{{e.ref}}</td><td>{{e.kind}}</td><td>{{e.debit}}</td><td>{{e.credit}}</td><td>{{e.balance}}</td></tr>{% endfor %}</table>\n{% endblock %}', 'login.html': '\n<!doctype html><html lang="bn"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Login</title><link rel="stylesheet" href="/static/style.css"></head>\n<body class="login"><form method="post" class="card"><h1>ওয়াসিস মিনারেল এন্ড মেটালাস লিমিটেড ERP</h1><p>কোম্পানির সফটওয়্যারে লগইন করুন</p><input name="username" placeholder="Username" required><input name="password" type="password" placeholder="Password" required><button>Login</button><small>Default: admin / admin123</small></form></body></html>\n', 'payments.html': '{% extends "base.html" %}{% block content %}<h1>পেমেন্ট</h1><form method="post" class="form"><select name="customer_id">{% for c in customers %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select><input name="amount" type="number" step="0.01" placeholder="Amount" required><input name="payment_date" type="date"><input name="method" placeholder="Cash/Bank/MFS"><input name="note" placeholder="Note"><button>Save Payment</button></form><table><tr><th>Customer</th><th>Amount</th><th>Date</th><th>Method</th><th>Note</th></tr>{% for r in rows %}<tr><td>{{r.customer}}</td><td>{{r.amount}}</td><td>{{r.payment_date}}</td><td>{{r.method}}</td><td>{{r.note}}</td></tr>{% endfor %}</table>{% endblock %}', 'profit_loss.html': '{% extends "base.html" %}{% block content %}<h1>Profit & Loss</h1>\n<p><a href="/profit-loss?period=today">আজ</a> | <a href="/profit-loss?period=month">এই মাস</a></p>\n<div class="grid"><div class="stat">Sales Revenue<br><b>৳ {{ "%.2f"|format(revenue) }}</b></div>\n<div class="stat">Stock Cost<br><b>৳ {{ "%.2f"|format(stock_cost) }}</b></div>\n<div class="stat">Delivery Cost<br><b>৳ {{ "%.2f"|format(delivery) }}</b></div>\n<div class="stat">Other Expenses<br><b>৳ {{ "%.2f"|format(expenses) }}</b></div>\n<div class="stat">Net Profit<br><b>৳ {{ "%.2f"|format(profit) }}</b></div></div>\n<table><tr><th>Particular</th><th>Amount</th></tr><tr><td>Sales Revenue</td><td>{{revenue}}</td></tr><tr><td>Stock Cost</td><td>{{stock_cost}}</td></tr><tr><td>Delivery Cost</td><td>{{delivery}}</td></tr><tr><td>Other Expenses</td><td>{{expenses}}</td></tr><tr><th>Net Profit</th><th>{{profit}}</th></tr></table>{% endblock %}', 'reports.html': '{% extends "base.html" %}{% block content %}<h1>রিপোর্ট</h1><div class="grid"><div class="stat">Revenue<br><b>৳ {{ "%.2f"|format(revenue) }}</b></div><div class="stat">Expenses<br><b>৳ {{ "%.2f"|format(expense) }}</b></div><div class="stat">Gross before stock cost<br><b>৳ {{ "%.2f"|format(revenue-expense) }}</b></div></div><h2>Product Sales</h2><table><tr><th>Product</th><th>Qty</th><th>Revenue</th></tr>{% for r in product %}<tr><td>{{r.product}}</td><td>{{r.qty}}</td><td>{{r.revenue}}</td></tr>{% endfor %}</table><h2>Customer Due</h2><table><tr><th>Customer</th><th>Due</th></tr>{% for r in cust %}<tr><td>{{r.name}}</td><td>{{r.due}}</td></tr>{% endfor %}</table>{% endblock %}', 'sales.html': '{% extends "base.html" %}{% block content %}<h1>বিক্রি / ডেলিভারি</h1><form method="post" class="form"><input name="invoice" placeholder="Invoice No" required><select name="customer_id" required>{% for c in customers %}<option value="{{c.id}}">{{c.name}}</option>{% endfor %}</select><input name="product" placeholder="পাথর" required><input name="quantity" type="number" step="0.01" placeholder="টন" required><input name="price" type="number" step="0.01" placeholder="প্রতি টন দাম" required><input name="truck_no" placeholder="গাড়ি নম্বর"><input name="delivery_date" type="date"><input name="paid" type="number" step="0.01" placeholder="আজকে পাওয়া টাকা"><button>Save Delivery</button></form><table><tr><th>Invoice</th><th>Customer</th><th>Product</th><th>Qty</th><th>Rate</th><th>Truck</th><th>Date</th><th>Invoice</th><th>Delivery Cost</th></tr>{% for r in rows %}<tr><td>{{r.invoice}}</td><td>{{r.customer}}</td><td>{{r.product}}</td><td>{{r.quantity}}</td><td>{{r.price}}</td><td>{{r.truck_no}}</td><td>{{r.delivery_date}}</td><td><a href="/invoice/{{r.id}}" target="_blank">Print</a></td>\n<td><details><summary>Add</summary><form method="post" action="/delivery-cost/{{r.id}}" class="mini">\n<input name="truck_no" placeholder="Truck"><input name="driver" placeholder="Driver">\n<input name="freight" type="number" step="0.01" placeholder="Freight"><input name="loading_cost" type="number" step="0.01" placeholder="Loading">\n<input name="unloading_cost" type="number" step="0.01" placeholder="Unloading"><input name="delivery_date" type="date">\n<button>Save</button></form></details></td></tr>{% endfor %}</table>{% endblock %}', 'ship_costs.html': '{% extends "base.html" %}{% block content %}\n<h1>জাহাজ Cost: {{ship.ship_name}}</h1>\n<div class="grid"><div class="stat">Base Cost/Ton<br><b>৳ {{ "%.2f"|format(ship.cost_per_ton) }}</b></div>\n<div class="stat">Extra Costs<br><b>৳ {{ "%.2f"|format(total) }}</b></div>\n<div class="stat">Effective Cost/Ton<br><b>৳ {{ "%.2f"|format(cost_per_ton) }}</b></div></div>\n<form method="post" class="form"><input name="category" placeholder="যেমন: Unloading/Freight/Port" required><input name="amount" type="number" step="0.01" placeholder="Amount" required><input name="note" placeholder="Note"><button>Add Cost</button></form>\n<table><tr><th>Category</th><th>Amount</th><th>Note</th></tr>{% for r in costs %}<tr><td>{{r.category}}</td><td>{{r.amount}}</td><td>{{r.note}}</td></tr>{% endfor %}</table>\n{% endblock %}', 'ships.html': '{% extends "base.html" %}{% block content %}<h1>জাহাজ / Import</h1><form method="post" class="form"><input name="ship_name" placeholder="জাহাজের নাম" required><input name="supplier" placeholder="Supplier"><input name="arrival_date" type="date"><input name="quantity" type="number" step="0.01" placeholder="মোট টন"><input name="unloaded" type="number" step="0.01" placeholder="আনলোড টন"><input name="cost_per_ton" type="number" step="0.01" placeholder="Cost/ton"><input name="notes" placeholder="নোট"><button>Save</button></form><table><tr><th>Ship</th><th>Supplier</th><th>Date</th><th>Qty</th><th>Unloaded</th><th>Cost/Ton</th><th>Costs</th><th>Stock In</th></tr>{% for r in rows %}<tr><td>{{r.ship_name}}</td><td>{{r.supplier}}</td><td>{{r.arrival_date}}</td><td>{{r.quantity}}</td><td>{{r.unloaded}}</td><td>{{r.cost_per_ton}}</td><td><a href="/ship-costs/{{r.id}}">Add/View Costs</a></td>\n<td>{% if r.quantity-r.unloaded>0 %}<form method="post" action="/ships/{{r.id}}/stock-in" class="mini">\n<input name="qty" type="number" step="0.01" max="{{r.quantity-r.unloaded}}" placeholder="Ton" required>\n<input name="product" placeholder="Product" value="Imported Stone"><input name="location" placeholder="Location" value="Main Stock">\n<button>Stock In</button></form>{% else %}Complete{% endif %}</td></tr>{% endfor %}</table>{% endblock %}', 'staff.html': '{% extends "base.html" %}{% block content %}<h1>Staff / Users</h1><form method="post" class="form"><input name="name" placeholder="নাম" required><input name="username" placeholder="Username" required><input name="password" type="password" placeholder="Password" required><select name="role"><option>staff</option><option>manager</option><option>accounts</option><option>store</option><option>sales</option><option>admin</option></select><button>Create User</button></form><table><tr><th>Name</th><th>Username</th><th>Role</th><th>Active</th></tr>{% for r in rows %}<tr><td>{{r.name}}</td><td>{{r.username}}</td><td>{{r.role}}</td><td>{{r.active}}</td></tr>{% endfor %}</table>{% endblock %}', 'stock.html': '{% extends "base.html" %}{% block content %}<h1>স্টক</h1><form method="post" class="form"><input name="product" placeholder="পাথরের ধরন/সাইজ" required><input name="quantity" type="number" step="0.01" placeholder="পরিমাণ টন" required><input name="unit_cost" type="number" step="0.01" placeholder="Cost/Ton"><input name="location" placeholder="গুদাম/সাইট"><button>Stock In</button></form><table><tr><th>Product</th><th>Qty</th><th>Unit Cost</th><th>Location</th></tr>{% for r in rows %}<tr><td>{{r.product}}</td><td>{{r.quantity}}</td><td>{{r.unit_cost}}</td><td>{{r.location}}</td></tr>{% endfor %}</table>{% endblock %}', 'trucks.html': '{% extends "base.html" %}{% block content %}<h1>গাড়ি / Truck</h1><form method="post" class="form"><input name="truck_no" placeholder="গাড়ি নম্বর" required><input name="driver" placeholder="Driver"><input name="phone" placeholder="Phone"><input name="rent" type="number" step="0.01" placeholder="ভাড়া"><button>Save</button></form><table><tr><th>Truck</th><th>Driver</th><th>Phone</th><th>Rent</th></tr>{% for r in rows %}<tr><td>{{r.truck_no}}</td><td>{{r.driver}}</td><td>{{r.phone}}</td><td>{{r.rent}}</td></tr>{% endfor %}</table>{% endblock %}'}
_EMBEDDED_CSS = '*{box-sizing:border-box}html{font-size:16px}body{margin:0;font-family:Arial,"Noto Sans Bengali",sans-serif;background:#f4f6f8;color:#18212b;overflow-x:hidden}aside{position:fixed;left:0;top:0;bottom:0;width:235px;background:#16232e;color:#fff;padding:18px 12px;overflow-y:auto;z-index:20}aside h2{font-size:18px;line-height:1.35;margin:0 0 15px;padding:0 8px}aside a{display:block;color:#dce7ef;text-decoration:none;padding:11px 10px;border-radius:8px;margin:2px 0}aside a:hover{background:#263b4b}.user{position:absolute;bottom:14px;font-size:12px;color:#b8c6d1;padding:0 8px}.user a{padding:5px 0;color:#fff}main{margin-left:235px;padding:24px;max-width:1500px}h1{margin-top:0}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:25px}.stat,.card{background:#fff;padding:18px;border-radius:12px;box-shadow:0 2px 9px #00000012}.stat b{font-size:23px;line-height:2}.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:9px;background:#fff;padding:14px;border-radius:10px;margin-bottom:20px}input,select,button,textarea{padding:12px;border:1px solid #ccd5dc;border-radius:7px;font-size:15px;min-height:44px}button{background:#1f6feb;color:#fff;border:0;cursor:pointer}table{width:100%;border-collapse:collapse;background:#fff;margin-bottom:25px}th,td{padding:10px;border-bottom:1px solid #e6ebef;text-align:left}th{background:#eef3f7}.alert{padding:12px;margin-bottom:15px;border-radius:7px;background:#fee}.success{background:#e5f7e9}.danger{background:#ffe8e8}.login{display:grid;place-items:center;min-height:100vh;background:#eef2f5;padding:15px}.login .card{width:min(390px,94vw);display:grid;gap:12px}.login small{color:#687783}.mini{display:flex;flex-wrap:wrap;gap:4px}.mini input{padding:6px;min-width:80px}.mini button{padding:6px 9px}a{color:#1f6feb}.mobile-top{display:none}.menu-btn{display:none}.table-wrap{width:100%;overflow-x:auto;-webkit-overflow-scrolling:touch;border-radius:10px;margin-bottom:20px}.table-wrap table{min-width:650px;margin-bottom:0}.btn{display:inline-block;padding:10px 13px;border-radius:7px;background:#1f6feb;color:#fff;text-decoration:none}.btn.secondary{background:#64748b}.brand{font-weight:700}.pwa-note{font-size:13px;color:#667085}\n@media(max-width:700px){aside{position:fixed;left:-280px;width:270px;height:100%;transition:left .2s;box-shadow:4px 0 20px #0003}aside.open{left:0}.user{position:static;margin-top:15px}.mobile-top{display:flex;position:sticky;top:0;z-index:15;background:#16232e;color:#fff;padding:10px 12px;align-items:center;gap:10px;box-shadow:0 2px 8px #0002}.menu-btn{display:block;background:#fff;color:#16232e;border:0;min-height:40px;padding:8px 12px;border-radius:7px;font-size:20px}.mobile-top .brand{font-size:14px;line-height:1.2}main{margin-left:0;padding:14px}.grid{grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.stat{padding:13px}.stat b{font-size:18px}.form{grid-template-columns:1fr;padding:12px}.form button{width:100%}table{font-size:13px}.login .card{padding:18px}.login h1{font-size:21px}.card{padding:14px}}\n'
_EMBEDDED_MANIFEST = '{\n  "name": "ওয়াসিস মিনারেল এন্ড মেটালাস লিমিটেড ERP",\n  "short_name": "Wasis ERP",\n  "start_url": "/",\n  "display": "standalone",\n  "background_color": "#f4f6f8",\n  "theme_color": "#16232e",\n  "lang": "bn"\n}\n'
_EMBEDDED_SW = "const CACHE='wasis-erp-v1';\nself.addEventListener('install',e=>self.skipWaiting());\nself.addEventListener('activate',e=>self.clients.claim());\nself.addEventListener('fetch',e=>{ if(e.request.method==='GET' && e.request.url.includes('/static/')) e.respondWith(caches.open(CACHE).then(c=>c.match(e.request).then(r=>r||fetch(e.request).then(x=>{c.put(e.request,x.clone());return x})))); });\n"
app.jinja_loader = DictLoader(_EMBEDDED_TEMPLATES)

def _embedded_static(filename):
    if filename == "style.css":
        return Response(_EMBEDDED_CSS, mimetype="text/css")
    if filename == "manifest.json":
        return Response(_EMBEDDED_MANIFEST, mimetype="application/manifest+json")
    if filename == "sw.js":
        return Response(_EMBEDDED_SW, mimetype="application/javascript")
    return Response("Not found", status=404)

app.view_functions["static"] = _embedded_static

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
