
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3, os, csv, io
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

if __name__=="__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
